#!/usr/bin/env python3
"""Prepare a blind listening comparison between the reference and the Rust runtime.

For every voice model and input clip this writes three conversions of the same audio
with the same settings:

    reference_a.wav   the reference implementation, noise seed 7
    reference_b.wav   the reference implementation, noise seed 8 (the control)
    ours.wav          the Rust runtime (`rvc-infer --seed 7`)

and an ABX page (`index.html`) that plays them without saying which is which. Synthesis
noise is random, so two runs of the reference already differ slightly; the control pair
shows how well those can be told apart, which is the yardstick for "reference against
Rust". The final judgement of specification section 13.2 ("the same voice and the same
phrasing") is asked per model on the same page.

Run with the reference environment's interpreter (see ../README.md):

    <reference>/venv/bin/python make_listening_set.py
    <reference>/venv/bin/python make_listening_set.py --voice my.pth my.index --input me.wav

Without arguments it uses the pinned public models and clips. Your own models and
recordings can be added with --voice and --input; everything is written under
<reference>/listening (or --out), outside the repository, and nothing is uploaded.
Open <out>/index.html in a browser to listen.
"""
import argparse
import base64
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dump_reference import Reference  # noqa: E402
from setup_reference import reference_dir  # noqa: E402

CRATE = HERE.parent
SEEDS = (7, 8)


def prepare_input(source, target):
    """Any audio file to 16 kHz mono 16-bit, the form both implementations are given."""
    import librosa
    import soundfile
    audio, rate = soundfile.read(source, dtype='float32', always_2d=True)
    audio = audio.mean(axis=1)
    if rate != 16000:
        audio = librosa.resample(audio, orig_sr=rate, target_sr=16000, res_type='soxr_hq')
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    soundfile.write(target, audio, 16000, subtype='PCM_16')
    # Read back what was written, so the reference sees exactly the samples in the file.
    return soundfile.read(target, dtype='float32')[0]


def reference_convert(reference, checkpoint, net, audio, *, index, index_rate, protect, transpose, speaker, seed, chunk):
    torch = reference.torch
    torch.manual_seed(seed)
    version, if_f0, rate = checkpoint.get('version', 'v1'), checkpoint.get('f0', 1), checkpoint['config'][-1]
    pipe = reference.pipeline_module.Pipeline(rate, reference.config(*chunk))
    output = pipe.pipeline(reference.hubert, net, speaker, audio.copy(), [0, 0, 0], transpose, 'rmvpe',
                           str(index) if index else '', index_rate, if_f0, rate, 0, 1.0, version, protect)
    return np.asarray(output), rate


def write_page(out, manifest):
    """The ABX page with the audio inside it.

    Carrying the audio makes the page work wherever it is opened (a file viewer that
    cannot load neighbouring files, or file:// in a browser). The WAV files stay next to
    it for other players.
    """
    audio = {}
    for case in manifest['cases']:
        for key in ('input', 'reference_a', 'reference_b', 'ours'):
            audio[case[key]] = base64.b64encode((out / case[key]).read_bytes()).decode('ascii')
    page = (HERE / 'listening_page.html').read_text(encoding='utf-8')
    start, end = page.index('/*MANIFEST*/'), page.index('/*END*/') + len('/*END*/')
    embedded = json.dumps({**manifest, 'audio': audio}, ensure_ascii=False).replace('</', '<\\/')
    (out / 'index.html').write_text(page[:start] + embedded + page[end:], encoding='utf-8')


def runtime_binary():
    subprocess.run(['cargo', 'build', '--release', '--locked', '--bin', 'rvc-infer'], cwd=CRATE, check=True)
    return CRATE / 'target' / 'release' / 'rvc-infer'


def main():
    root = reference_dir()
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--voice', nargs='+', action='append', metavar=('PTH', 'INDEX'),
                        help='a voice model and optionally its index; repeat for more models')
    parser.add_argument('--input', action='append', type=Path, help='an audio file to convert; repeat for more')
    parser.add_argument('--transpose', action='append', type=int, help='key change in semitones; repeat to compare several')
    parser.add_argument('--index-rate', type=float, default=0.75)
    parser.add_argument('--protect', type=float, default=0.33)
    parser.add_argument('--speaker', type=int, default=0)
    parser.add_argument('--trials', type=int, default=6, help='ABX trials per pair (default 6)')
    parser.add_argument('--chunk', default='3,10,60,65', help='split settings in seconds: pad,query,center,max')
    parser.add_argument('--out', type=Path, default=root / 'listening')
    parser.add_argument('--page-only', action='store_true', help='rebuild index.html from an existing set without converting again')
    arguments = parser.parse_args()
    if arguments.page_only:
        manifest = json.loads((arguments.out / 'manifest.json').read_text(encoding='utf-8'))
        write_page(arguments.out.resolve(), manifest)
        print(f'Rebuilt {arguments.out.resolve() / "index.html"}.')
        return

    voices = [(Path(parts[0]), Path(parts[1]) if len(parts) > 1 else None) for parts in arguments.voice or []]
    if not voices:
        voices = [(root / 'model' / 'model.pth', root / 'model' / 'model.index'),
                  (root / 'fixtures' / 'models' / 'pretrained_v2_40k.pth', None)]
    inputs = arguments.input or [root / 'audio' / 'speech.wav', root / 'audio' / 'speech2.wav']
    transposes = arguments.transpose or [0]
    chunk = tuple(int(part) for part in arguments.chunk.split(','))
    for path in [voice for voice, _ in voices] + [index for _, index in voices if index] + inputs:
        if not path.is_file():
            raise SystemExit(f'missing file: {path} (run setup_reference.py and dump_reference.py first)')
    hubert, rmvpe = root / 'assets' / 'hubert_base' / 'hubert.onnx', root / 'assets' / 'rmvpe' / 'rmvpe.onnx'
    if not hubert.is_file():
        raise SystemExit('hubert.onnx is missing; run export_hubert_onnx.py first')

    voices = [(voice.resolve(), index.resolve() if index else None) for voice, index in voices]
    inputs = [path.resolve() for path in inputs]
    out = arguments.out.resolve()
    binary = runtime_binary()
    reference = Reference(root)  # changes the working directory to the engine
    import soundfile
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cases = []
    for voice_number, (voice, index) in enumerate(voices):
        checkpoint = reference.torch.load(voice, map_location='cpu', weights_only=True)
        net = reference.synthesizer(checkpoint)
        version, if_f0, rate = checkpoint.get('version', 'v1'), checkpoint.get('f0', 1), checkpoint['config'][-1]
        index_rate = arguments.index_rate if index else 0.0
        for input_number, source in enumerate(inputs):
            # Pitch-free models ignore the key change, so one setting is enough for them.
            for transpose in transposes if if_f0 == 1 else transposes[:1]:
                name = f'case{len(cases) + 1:02d}'
                folder = out / name
                folder.mkdir()
                audio = prepare_input(source, folder / 'input.wav')
                options = dict(index=index, index_rate=index_rate, protect=arguments.protect, transpose=transpose,
                               speaker=arguments.speaker, chunk=chunk)
                for label, seed in zip(('reference_a', 'reference_b'), SEEDS):
                    converted, _ = reference_convert(reference, checkpoint, net, audio, seed=seed, **options)
                    soundfile.write(folder / f'{label}.wav', converted, rate, subtype='PCM_16')
                command = [str(binary), '--model', str(voice), '--hubert', str(hubert), '--rmvpe', str(rmvpe),
                           '--input', str(folder / 'input.wav'), '--output', str(folder / 'ours.wav'),
                           '--seed', str(SEEDS[0]), '--index-rate', str(index_rate), '--protect', str(arguments.protect),
                           '--transpose', str(transpose), '--speaker', str(arguments.speaker), '--chunk', arguments.chunk]
                if index:
                    command += ['--index', str(index)]
                subprocess.run(command, check=True, stderr=subprocess.DEVNULL)
                details = [version, f'{rate // 1000} kHz', 'F0 あり' if if_f0 == 1 else 'F0 なし']
                details.append(f'インデックス {index_rate:g}' if index else 'インデックスなし')
                if if_f0 == 1 and transpose:
                    details.append(f'キー {transpose:+d}')
                cases.append({
                    'id': name, 'label': f'{voice.stem}（{"、".join(details)}）', 'input_label': f'{source.stem}（{len(audio) / 16000:.1f} 秒）',
                    'input': f'{name}/input.wav', 'reference_a': f'{name}/reference_a.wav',
                    'reference_b': f'{name}/reference_b.wav', 'ours': f'{name}/ours.wav',
                })
                print(f'{name}: model {voice_number + 1}, input {input_number + 1}, transpose {transpose}', flush=True)
    manifest = {'created': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), 'trials': arguments.trials, 'cases': cases}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_page(out, manifest)
    print(f'{len(cases)} case(s) written. Open {out / "index.html"} in a browser.')


if __name__ == '__main__':
    main()
