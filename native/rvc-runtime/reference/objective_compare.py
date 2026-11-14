#!/usr/bin/env python3
"""Objective comparison of the Rust runtime with the reference implementation.

Synthesis draws random noise, so two runs of the reference already differ. The
yardstick is therefore the reference's own spread: every model and input is converted
with several noise seeds by the reference and by the runtime, and each measure is
compared between "reference against reference" pairs and "runtime against reference"
pairs. The runtime passes a measure when it sits within the reference's spread.

Measures (all computed locally, models pinned in setup_reference.py):

  same voice        speaker-embedding cosine similarity (SpeechBrain ECAPA-TDNN, VoxCeleb)
  same phrasing     character error rate between Whisper-small transcripts, and of each
                    output against the transcript of the input
  naturalness       TorchAudio-Squim subjective MOS estimate (clean input as reference)
  timbre            MFCC distortion (the mel-cepstral distortion formula on MFCCs) and
                    log-spectral distance
  intonation        F0 voicing agreement and pitch difference in cents (RMVPE)
  loudness          RMS level difference

Run with the reference environment's interpreter:

    <reference>/venv/bin/python objective_compare.py
    <reference>/venv/bin/python objective_compare.py --voice my.pth my.index --input me.wav --language ja

Writes <reference>/objective (or --out): the converted audio, report.json and report.md.
--reuse measures the audio of an earlier run again without converting.
Transcripts are used for the error rates only; they are neither printed nor stored.
"""
import argparse
import datetime
import itertools
import json
import math
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dump_reference import Reference  # noqa: E402
from make_listening_set import prepare_input, reference_convert, runtime_binary  # noqa: E402
from setup_reference import reference_dir  # noqa: E402

SEEDS = (7, 8, 9, 10)


def to_16k(audio, rate):
    import librosa
    audio = np.asarray(audio, dtype=np.float32)
    return audio if rate == 16000 else librosa.resample(audio, orig_sr=rate, target_sr=16000, res_type='soxr_hq')


def normalise_text(text):
    """Lower case without punctuation, symbols or spaces, for character error rates."""
    text = unicodedata.normalize('NFKC', text).lower()
    return ''.join(c for c in text if not unicodedata.category(c).startswith(('P', 'S', 'Z')) and not c.isspace())


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def cer(hypothesis, reference):
    hypothesis, reference = normalise_text(hypothesis), normalise_text(reference)
    return edit_distance(hypothesis, reference) / max(len(reference), 1)


class Measures:
    def __init__(self, root, reference, language):
        import torch
        import torchaudio
        from speechbrain.lobes.features import Fbank
        from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        assets = root / 'assets' / 'eval'
        # ECAPA-TDNN with the layout of the published hyperparameters; only the embedding weights are loaded.
        self.fbank = Fbank(n_mels=80)
        self.ecapa = ECAPA_TDNN(input_size=80, channels=[1024, 1024, 1024, 1024, 3072], kernel_sizes=[5, 3, 3, 3, 1],
                                dilations=[1, 2, 3, 4, 1], attention_channels=128, lin_neurons=192)
        self.ecapa.load_state_dict(torch.load(assets / 'ecapa' / 'embedding_model.ckpt', map_location='cpu', weights_only=True), strict=True)
        self.ecapa.eval()
        self.squim = torchaudio.models.squim_subjective_base()
        self.squim.load_state_dict(torch.load(assets / 'squim' / 'squim_subjective_bvcc_daps.pth', map_location='cpu', weights_only=True), strict=True)
        self.squim.eval()
        folder = assets / 'whisper-small'
        self.processor = WhisperProcessor.from_pretrained(folder, local_files_only=True)
        self.whisper = WhisperForConditionalGeneration.from_pretrained(folder, local_files_only=True).eval()
        self.language = language
        from infer.rmvpe import RMVPE  # the reference's extractor, already importable through Reference
        self.rmvpe = RMVPE(str(root / 'assets' / 'rmvpe' / 'rmvpe.pt'), False, 'cpu')
        del reference

    def speaker(self, audio):
        torch = self.torch
        with torch.no_grad():
            features = self.fbank(torch.from_numpy(audio)[None])
            features = features - features.mean(dim=1, keepdim=True)  # sentence mean normalisation
            embedding = self.ecapa(features).reshape(-1).numpy()
        return embedding / np.linalg.norm(embedding)

    def transcribe(self, audio):
        torch = self.torch
        options = {'task': 'transcribe'}
        if self.language:
            options['language'] = self.language
        parts = []
        for start in range(0, len(audio), 16000 * 30):
            window = audio[start:start + 16000 * 30]
            if len(window) < 1600:
                continue
            inputs = self.processor(window, sampling_rate=16000, return_tensors='pt')
            with torch.no_grad():
                ids = self.whisper.generate(inputs.input_features, **options)
            parts.append(self.processor.batch_decode(ids, skip_special_tokens=True)[0])
        return ' '.join(parts)

    def naturalness(self, audio, clean):
        torch = self.torch
        with torch.no_grad():
            return float(self.squim(torch.from_numpy(audio)[None], torch.from_numpy(clean)[None]).reshape(-1)[0])

    def pitch(self, audio):
        return np.asarray(self.rmvpe.infer_from_audio(audio, thred=0.03), dtype=np.float64)

    def describe(self, audio, rate, clean):
        """Everything measured on one output (transcript kept in memory only)."""
        audio16 = to_16k(audio, rate)
        return {'audio': np.asarray(audio, dtype=np.float32), 'rate': rate, 'audio16': audio16,
                'speaker': self.speaker(audio16), 'text': self.transcribe(audio16),
                'mos': self.naturalness(audio16, clean), 'f0': self.pitch(audio16), 'mfcc': mfcc(audio16)}


def mfcc(audio16):
    import librosa
    coefficients = librosa.feature.mfcc(y=audio16, sr=16000, n_mfcc=25, n_fft=1024, hop_length=160, n_mels=80)
    # librosa takes the cepstrum of a decibel spectrum; the distortion formula below expects
    # the natural logarithm, so convert back before using it.
    coefficients = coefficients / (10 / math.log(10))
    energy = librosa.feature.rms(y=audio16, frame_length=1024, hop_length=160)[0]
    return coefficients[1:], energy  # c0 (overall level) is left out, as for mel-cepstral distortion


def mfcc_distortion(a, b):
    (ca, _), (cb, energy) = a['mfcc'], b['mfcc']
    frames = min(ca.shape[1], cb.shape[1])
    keep = energy[:frames] > 10 ** (-50 / 20)  # skip near-silent frames of the second signal
    difference = ca[:, :frames][:, keep] - cb[:, :frames][:, keep]
    return float(np.mean(10 / math.log(10) * np.sqrt(2 * np.sum(difference ** 2, axis=0))))


def log_spectral_distance(a, b):
    import librosa
    count = min(len(a['audio']), len(b['audio']))
    sa = np.abs(librosa.stft(a['audio'][:count], n_fft=1024, hop_length=256)) ** 2
    sb = np.abs(librosa.stft(b['audio'][:count], n_fft=1024, hop_length=256)) ** 2
    keep = sb.mean(axis=0) > 1e-7
    difference = 10 * np.log10(np.maximum(sa, 1e-10)) - 10 * np.log10(np.maximum(sb, 1e-10))
    return float(np.sqrt((difference ** 2).mean(axis=0))[keep].mean())


def pitch_measures(a, b):
    fa, fb = a['f0'], b['f0']
    frames = min(len(fa), len(fb))
    fa, fb = fa[:frames], fb[:frames]
    voiced = (fa > 0) & (fb > 0)
    cents = np.abs(1200 * np.log2(fa[voiced] / fb[voiced])) if voiced.any() else np.array([0.0])
    return float(np.mean((fa > 0) == (fb > 0))), float(np.median(cents))


def level_difference(a, b):
    rms = lambda x: math.sqrt(float(np.mean(np.square(x, dtype=np.float64)))) + 1e-12
    return abs(20 * math.log10(rms(a['audio']) / rms(b['audio'])))


# name, label, higher is closer, function of a pair (first, second)
PAIR_MEASURES = (
    ('speaker', '話者類似度（コサイン）', True, lambda a, b: float(np.dot(a['speaker'], b['speaker']))),
    ('text', '文字起こしの文字誤り率', False, lambda a, b: cer(a['text'], b['text'])),
    ('mfcc', 'MFCC 歪み（MCD の式、dB 相当）', False, mfcc_distortion),
    ('lsd', 'log-spectral distance（dB）', False, log_spectral_distance),
    ('voicing', 'F0 の有声一致率', True, lambda a, b: pitch_measures(a, b)[0]),
    ('cents', 'F0 の差（cents、中央値）', False, lambda a, b: pitch_measures(a, b)[1]),
    ('level', '音量差（dB）', False, level_difference),
)
# name, label, function of one output and the input's description
SINGLE_MEASURES = (
    ('mos', '自然さの推定 MOS（Squim）', lambda item, source: item['mos']),
    ('input_cer', '入力の文字起こしに対する文字誤り率', lambda item, source: cer(item['text'], source['text'])),
)


def summary(values):
    return {'mean': float(np.mean(values)), 'min': float(np.min(values)), 'max': float(np.max(values)), 'count': len(values)}


def judge_case(references, ours, source):
    rows = []
    for name, label, higher, function in PAIR_MEASURES:
        within_reference = [function(a, b) for a, b in itertools.combinations(references, 2)]
        against = [function(item, reference) for item in ours for reference in references]
        spread, measured = summary(within_reference), summary(against)
        # Pass when the runtime is no further from the reference than the reference's
        # own runs are from each other.
        passed = measured['mean'] >= spread['min'] if higher else measured['mean'] <= spread['max']
        rows.append({'measure': name, 'label': label, 'kind': 'pair', 'reference': spread, 'ours': measured, 'within': bool(passed)})
    for name, label, function in SINGLE_MEASURES:
        spread = summary([function(item, source) for item in references])
        measured = summary([function(item, source) for item in ours])
        # One value per output: the runtime's mean must lie within the reference's range,
        # widened by half that range so that four samples do not make the test arbitrary.
        margin = (spread['max'] - spread['min']) / 2
        passed = spread['min'] - margin <= measured['mean'] <= spread['max'] + margin
        rows.append({'measure': name, 'label': label, 'kind': 'single', 'reference': spread, 'ours': measured, 'within': bool(passed)})
    return rows


def markdown(report):
    lines = [f"計測日時 {report['created']}。シード {', '.join(map(str, report['seeds']))} で本家と Rust をそれぞれ変換。",
             '「本家どうし」は本家のシード違いの組、「本家と Rust」は Rust の各出力と本家の各出力の組です（1 出力ごとの値は出力ごと）。', '']
    for case in report['cases']:
        lines += [f"#### {case['label']} ／ {case['input_label']}", '',
                  '| 指標 | 本家どうし 平均 [最小–最大] | 本家と Rust 平均 [最小–最大] | 判定 |', '|---|---|---|---|']
        for row in case['rows']:
            cell = lambda s: f"{s['mean']:.3f} [{s['min']:.3f}–{s['max']:.3f}]"
            lines.append(f"| {row['label']} | {cell(row['reference'])} | {cell(row['ours'])} | {'範囲内' if row['within'] else '**範囲外**'} |")
        lines.append('')
    total = sum(len(case['rows']) for case in report['cases'])
    passed = sum(row['within'] for case in report['cases'] for row in case['rows'])
    lines.append(f"範囲内 {passed} / {total} 項目。")
    return '\n'.join(lines) + '\n'


def main():
    root = reference_dir()
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--voice', nargs='+', action='append', metavar=('PTH', 'INDEX'))
    parser.add_argument('--input', action='append', type=Path)
    parser.add_argument('--transpose', type=int, default=0)
    parser.add_argument('--index-rate', type=float, default=0.75)
    parser.add_argument('--protect', type=float, default=0.33)
    parser.add_argument('--speaker', type=int, default=0)
    parser.add_argument('--language', help='Whisper language code (default: detect)')
    parser.add_argument('--chunk', default='3,10,60,65')
    parser.add_argument('--out', type=Path, default=root / 'objective')
    parser.add_argument('--reuse', action='store_true', help='measure the audio of an earlier run again instead of converting')
    arguments = parser.parse_args()

    voices = [(Path(parts[0]).resolve(), Path(parts[1]).resolve() if len(parts) > 1 else None) for parts in arguments.voice or []]
    if not voices:
        voices = [(root / 'model' / 'model.pth', root / 'model' / 'model.index'),
                  (root / 'fixtures' / 'models' / 'pretrained_v2_40k.pth', None)]
    inputs = [path.resolve() for path in (arguments.input or [root / 'audio' / 'speech.wav', root / 'audio' / 'speech2.wav'])]
    chunk = tuple(int(part) for part in arguments.chunk.split(','))
    out = arguments.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hubert, rmvpe = root / 'assets' / 'hubert_base' / 'hubert.onnx', root / 'assets' / 'rmvpe' / 'rmvpe.onnx'
    binary = runtime_binary()
    reference = Reference(root)
    measures = Measures(root, reference, arguments.language)
    import soundfile

    sources = []
    for number, path in enumerate(inputs):
        folder = out / f'input{number + 1}'
        folder.mkdir(exist_ok=True)
        sources.append((path, folder, prepare_input(path, folder / 'input.wav')))
    cases = []
    for voice, index in voices:
        checkpoint = reference.torch.load(voice, map_location='cpu', weights_only=True)
        net = reference.synthesizer(checkpoint)
        if_f0 = checkpoint.get('f0', 1)
        index_rate = arguments.index_rate if index else 0.0
        for number, (path, folder, audio) in enumerate(sources):
            # Naturalness needs clean speech that is not the clip itself; use another input when there is one.
            clean = sources[(number + 1) % len(sources)][2]
            source = {'text': measures.transcribe(audio)}
            options = dict(index=index, index_rate=index_rate, protect=arguments.protect, transpose=arguments.transpose,
                           speaker=arguments.speaker, chunk=chunk)
            case_folder = out / f'case{len(cases) + 1:02d}'
            case_folder.mkdir(exist_ok=True)
            references, ours = [], []
            for seed in SEEDS:
                target = case_folder / f'reference_seed{seed}.wav'
                if not (arguments.reuse and target.is_file()):
                    converted, rate = reference_convert(reference, checkpoint, net, audio, seed=seed, **options)
                    soundfile.write(target, converted, rate, subtype='PCM_16')
                written, written_rate = soundfile.read(target, dtype='float32')
                references.append(measures.describe(written, written_rate, clean))
                target = case_folder / f'ours_seed{seed}.wav'
                command = [str(binary), '--model', str(voice), '--hubert', str(hubert), '--rmvpe', str(rmvpe),
                           '--input', str(folder / 'input.wav'), '--output', str(target), '--seed', str(seed),
                           '--index-rate', str(index_rate), '--protect', str(arguments.protect),
                           '--transpose', str(arguments.transpose), '--speaker', str(arguments.speaker), '--chunk', arguments.chunk]
                if index:
                    command += ['--index', str(index)]
                if not (arguments.reuse and target.is_file()):
                    subprocess.run(command, check=True, stderr=subprocess.DEVNULL)
                written, written_rate = soundfile.read(target, dtype='float32')
                ours.append(measures.describe(written, written_rate, clean))
            details = [checkpoint.get('version', 'v1'), f"{checkpoint['config'][-1] // 1000} kHz", 'F0 あり' if if_f0 == 1 else 'F0 なし',
                       f'インデックス {index_rate:g}' if index else 'インデックスなし']
            case = {'id': case_folder.name, 'label': f"{voice.stem}（{'、'.join(details)}）",
                    'input_label': f'{path.stem}（{len(audio) / 16000:.1f} 秒）', 'rows': judge_case(references, ours, source)}
            cases.append(case)
            passed = sum(row['within'] for row in case['rows'])
            print(f"{case['id']}: {passed} / {len(case['rows'])} measures within the reference spread", flush=True)
    report = {'created': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), 'seeds': list(SEEDS), 'cases': cases}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'report.md').write_text(markdown(report), encoding='utf-8')
    print(f'Report: {out / "report.md"}')


if __name__ == '__main__':
    main()
