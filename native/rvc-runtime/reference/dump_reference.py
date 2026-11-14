#!/usr/bin/env python3
"""Run the reference implementation and record what the conformance tests compare.

The reference is used as a black box: this script only calls its public entry points
and records the values that cross them (the filtered audio handed to the F0 extractor,
the F0 track, the HuBERT features, the neighbours the index returned, the synthesizer
inputs and outputs). Nothing from the reference is copied into the runtime.

Run it with the reference environment's interpreter:

    <reference>/venv/bin/python dump_reference.py

It writes `<reference>/fixtures/<case>/` (NumPy arrays plus `case.json`). The arrays hold
model activations and audio derived from the CC BY 4.0 clip and voice model; they stay
in the cache directory and are not committed.
"""
import argparse
import json
import os
import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_reference import reference_dir  # noqa: E402

# Standard v2 structures per output rate, as the pretrained base models use them.
STRUCTURES = {
    32000: dict(upsample_rates=[10, 8, 2, 2], upsample_kernel_sizes=[20, 16, 4, 4], spec_channels=513),
    40000: dict(upsample_rates=[10, 10, 2, 2], upsample_kernel_sizes=[16, 16, 4, 4], spec_channels=1025),
    48000: dict(upsample_rates=[12, 10, 2, 2], upsample_kernel_sizes=[24, 20, 4, 4], spec_channels=1025),
}


def structure(sample_rate, speakers=109):
    extra = STRUCTURES[sample_rate]
    return [extra['spec_channels'], 32, 192, 192, 768, 2, 6, 3, 0, '1', [3, 7, 11],
            [[1, 3, 5], [1, 3, 5], [1, 3, 5]], extra['upsample_rates'], 512,
            extra['upsample_kernel_sizes'], speakers, 256, sample_rate]


class Reference:
    """The reference engine with its models loaded on the CPU in single precision."""

    def __init__(self, root):
        self.root = root
        engine = root / 'engine'
        os.chdir(engine)
        sys.path.insert(0, str(engine))
        os.environ['rmvpe_root'] = str(root / 'assets' / 'rmvpe')
        import torch
        torch.set_grad_enabled(False)
        torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
        import infer.hubert as hubert
        import infer.vc.pipeline as pipeline
        import infer.module.models as models
        self.torch, self.hubert_module, self.pipeline_module, self.models = torch, hubert, pipeline, models
        hubert.HUBERT_MODEL_PATH = root / 'assets' / 'hubert_base'
        self.hubert = hubert.load_hubert_model('cpu', False)

    def config(self, x_pad, x_query, x_center, x_max):
        return types.SimpleNamespace(x_pad=x_pad, x_query=x_query, x_center=x_center, x_max=x_max,
                                     is_half=False, device='cpu', dml=False)

    def synthesizer(self, checkpoint):
        version, f0 = checkpoint.get('version', 'v1'), checkpoint.get('f0', 1)
        name = ('SynthesizerTrnMs768NSFsid' if version == 'v2' else 'SynthesizerTrnMs256NSFsid') + ('' if f0 == 1 else '_nono')
        config = list(checkpoint['config'])
        config[-3] = checkpoint['weight']['emb_g.weight'].shape[0]
        arguments = config if f0 == 1 else config[:-1]
        net = getattr(self.models, name)(*arguments, is_half=False)
        if hasattr(net, 'enc_q'):
            del net.enc_q
        net.load_state_dict({key: value.float() for key, value in checkpoint['weight'].items()}, strict=True)
        return net.eval()

    def random_checkpoint(self, version, f0, sample_rate, seed):
        """A voice model with randomly initialised weights, saved the way real ones are."""
        torch = self.torch
        torch.manual_seed(seed)
        config = structure(sample_rate, speakers=4)
        name = ('SynthesizerTrnMs768NSFsid' if version == 'v2' else 'SynthesizerTrnMs256NSFsid') + ('' if f0 else '_nono')
        net = getattr(self.models, name)(*(config if f0 else config[:-1]), is_half=False)
        weight = {key: value.half() for key, value in net.state_dict().items() if not key.startswith('enc_q')}
        return {'weight': weight, 'config': config, 'f0': int(f0), 'version': version, 'info': 'random', 'sr': f'{sample_rate // 1000}k'}

    def pretrained_checkpoint(self, path, sample_rate):
        """The published v2 base generator as an inference model (weights unchanged, half precision)."""
        state = self.torch.load(path, map_location='cpu', weights_only=True)['model']
        weight = {key: value.half() for key, value in state.items() if not key.startswith('enc_q')}
        return {'weight': weight, 'config': structure(sample_rate), 'f0': 1, 'version': 'v2', 'info': 'pretrained_v2 base', 'sr': f'{sample_rate // 1000}k'}


def run_case(reference, name, *, model_path, audio, index_path=None, index_rate=0.0, protect=0.33,
             transpose=0, sid=0, noise='zero', seed=0, rms_mix_rate=1.0, resample_sr=0,
             chunk=(3, 10, 60, 65)):
    torch, pipeline_module = reference.torch, reference.pipeline_module
    out = reference.root / 'fixtures' / name
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = torch.load(model_path, map_location='cpu', weights_only=True)
    net = reference.synthesizer(checkpoint)
    version, if_f0, tgt_sr = checkpoint.get('version', 'v1'), checkpoint.get('f0', 1), checkpoint['config'][-1]
    record = {'hubert': [], 'synth': [], 'search': [], 'f0': []}

    # --- observation points -------------------------------------------------------
    real_features = pipeline_module.extract_hubert_features

    def features(model, source, version, padding_mask=None):
        result = real_features(model, source, version, padding_mask)
        record['hubert'].append((source.detach().cpu().numpy().copy(), result.detach().cpu().numpy().copy()))
        return result

    real_read_index = pipeline_module.faiss.read_index

    class Index:
        def __init__(self, path):
            self.inner = real_read_index(path)
            self.ntotal = self.inner.ntotal

        def reconstruct_n(self, start, count):
            return self.inner.reconstruct_n(start, count)

        def search(self, queries, k):
            scores, ids = self.inner.search(queries, k)
            record['search'].append((np.array(queries).copy(), scores.copy(), ids.copy()))
            return scores, ids

    real_infer = net.infer

    def infer(*arguments, **keywords):
        result = real_infer(*arguments, **keywords)
        tensors = [value.detach().cpu().numpy().copy() for value in arguments if hasattr(value, 'detach')]
        record['synth'].append((tensors, result[0].detach().cpu().numpy().copy() if isinstance(result, tuple) else result.detach().cpu().numpy().copy()))
        return result

    real_randn_like, real_rand, real_randn = torch.randn_like, torch.rand, torch.randn
    if noise == 'zero':
        torch.randn_like = lambda tensor, *a, **k: torch.zeros_like(tensor)
        torch.rand = lambda *size, **k: torch.zeros(*size, **{key: k[key] for key in ('device', 'dtype') if key in k})
        torch.randn = lambda *size, **k: torch.zeros(*size, **{key: k[key] for key in ('device', 'dtype') if key in k})
    else:
        torch.manual_seed(seed)

    pipe = pipeline_module.Pipeline(tgt_sr, reference.config(*chunk))
    real_get_f0 = pipe.get_f0

    def get_f0(x, p_len, f0_up_key, f0_method):
        rmvpe_before = getattr(pipe, 'model_rmvpe', None)
        result = real_get_f0(x, p_len, f0_up_key, f0_method)
        record['f0'].append((np.asarray(x).copy(), [np.asarray(value).copy() for value in result]))
        return result

    pipeline_module.extract_hubert_features = features
    pipeline_module.faiss.read_index = Index
    net.infer = infer
    pipe.get_f0 = get_f0
    try:
        times = [0, 0, 0]
        output = pipe.pipeline(reference.hubert, net, sid, audio.copy(), times, transpose, 'rmvpe',
                               str(index_path) if index_path else '', index_rate, if_f0, tgt_sr, resample_sr,
                               rms_mix_rate, version, protect)
        # The raw extractor output (before interpolation, key change and quantisation).
        raw_f0 = None
        if record['f0'] and getattr(pipe, 'model_rmvpe', None) is not None:
            raw_f0 = pipe.model_rmvpe.infer_from_audio(record['f0'][0][0], thred=0.03)
    finally:
        torch.randn_like, torch.rand, torch.randn = real_randn_like, real_rand, real_randn
        pipeline_module.extract_hubert_features = real_features
        pipeline_module.faiss.read_index = real_read_index

    np.save(out / 'input_16k.npy', audio.astype(np.float32))
    np.save(out / 'output.npy', np.asarray(output))
    if record['f0']:
        filtered, (coarse, pitchf, *_rest) = record['f0'][0]
        np.save(out / 'f0_input.npy', filtered.astype(np.float64))
        np.save(out / 'coarse.npy', np.asarray(coarse).astype(np.int64))
        np.save(out / 'pitchf.npy', np.asarray(pitchf).astype(np.float32))
        if raw_f0 is not None:
            np.save(out / 'f0_raw.npy', np.asarray(raw_f0).astype(np.float32))
    for number, (source, feats) in enumerate(record['hubert']):
        np.save(out / f'hubert_input_{number}.npy', source.astype(np.float32).reshape(-1))
        np.save(out / f'hubert_{number}.npy', feats.astype(np.float32).reshape(-1, feats.shape[-1]))
    for number, (queries, scores, ids) in enumerate(record['search']):
        np.save(out / f'search_queries_{number}.npy', queries.astype(np.float32))
        np.save(out / f'search_scores_{number}.npy', scores.astype(np.float32))
        np.save(out / f'search_ids_{number}.npy', ids.astype(np.int64))
    for number, (tensors, audio_out) in enumerate(record['synth']):
        # Call order of the synthesizer: features, length, [coarse pitch, continuous pitch,] speaker.
        np.save(out / f'synth_feats_{number}.npy', tensors[0].astype(np.float32).reshape(-1, tensors[0].shape[-1]))
        if if_f0 == 1:
            np.save(out / f'synth_pitch_{number}.npy', tensors[2].astype(np.int64).reshape(-1))
            np.save(out / f'synth_pitchf_{number}.npy', tensors[3].astype(np.float32).reshape(-1))
        np.save(out / f'synth_audio_{number}.npy', audio_out.astype(np.float32).reshape(-1))
    case = {
        'model': str(model_path), 'index': str(index_path) if index_path else None, 'index_rate': index_rate,
        'protect': protect, 'transpose': transpose, 'sid': sid, 'noise': noise, 'seed': seed,
        'rms_mix_rate': rms_mix_rate, 'resample_sr': resample_sr, 'chunk': list(chunk),
        'version': version, 'f0': int(if_f0), 'sample_rate': int(tgt_sr),
        'segments': len(record['synth']), 'output_dtype': str(np.asarray(output).dtype),
    }
    (out / 'case.json').write_text(json.dumps(case, indent=2) + '\n')
    print(f'{name}: {len(record["synth"])} segment(s), output {np.asarray(output).shape} {np.asarray(output).dtype}', flush=True)


def load_speech(root):
    import soundfile
    audio, rate = soundfile.read(root / 'audio' / 'speech.wav', dtype='float32')
    assert rate == 16000 and audio.ndim == 1
    return audio


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--only', help='run only the cases whose name contains this text')
    arguments = parser.parse_args()
    root = reference_dir()
    reference = Reference(root)
    torch = reference.torch
    speech = load_speech(root)
    models = root / 'fixtures' / 'models'
    models.mkdir(parents=True, exist_ok=True)

    pretrained = root / 'model' / 'f0G40k.pth'
    v2_40k = models / 'pretrained_v2_40k.pth'
    if pretrained.exists() and not v2_40k.exists():
        torch.save(reference.pretrained_checkpoint(pretrained, 40000), v2_40k)
    randoms = {}
    for version, f0, rate in (('v2', True, 40000), ('v2', True, 32000), ('v2', False, 48000), ('v1', True, 40000), ('v1', False, 32000)):
        path = models / f'random_{version}_{"f0" if f0 else "nof0"}_{rate // 1000}k.pth'
        if not path.exists():
            torch.save(reference.random_checkpoint(version, f0, rate, seed=1234), path)
        randoms[(version, f0, rate)] = path

    voice, index = root / 'model' / 'model.pth', root / 'model' / 'model.index'
    # A long input that forces the reference to split at quiet points (41 s threshold below).
    gap = np.zeros(8000, dtype=np.float32)
    long_speech = np.concatenate([np.concatenate([speech * scale, gap]) for scale in (1.0, 0.7, 0.9, 0.5, 0.8, 0.6, 1.0, 0.75, 0.85, 0.65, 0.95, 0.55, 0.7)])
    cases = [
        ('saisho_48k_zero', dict(model_path=voice, audio=speech, index_path=index, index_rate=0.75, protect=0.33)),
        ('saisho_48k_noindex_zero', dict(model_path=voice, audio=speech, index_rate=0.0, protect=0.5, transpose=12)),
        ('saisho_48k_seeded', dict(model_path=voice, audio=speech, index_path=index, index_rate=0.75, noise='seeded', seed=7)),
        ('saisho_48k_post', dict(model_path=voice, audio=speech * 0.3, index_path=index, index_rate=0.5, protect=0.2,
                                 transpose=-5, rms_mix_rate=0.25, resample_sr=44100)),
        ('saisho_48k_long_zero', dict(model_path=voice, audio=long_speech, index_path=index, index_rate=0.75,
                                      chunk=(1, 6, 38, 41))),
        ('pretrained_40k_zero', dict(model_path=v2_40k, audio=speech, sid=0)),
        ('pretrained_40k_seeded', dict(model_path=v2_40k, audio=speech, sid=0, noise='seeded', seed=7)),
    ]
    for (version, f0, rate), path in randoms.items():
        cases.append((path.stem + '_zero', dict(model_path=path, audio=speech, sid=2, transpose=3 if f0 else 0)))
    for name, options in cases:
        if arguments.only and arguments.only not in name:
            continue
        if not Path(options['model_path']).exists():
            print(f'{name}: skipped, model file is missing', flush=True)
            continue
        run_case(reference, name, **options)


if __name__ == '__main__':
    main()
