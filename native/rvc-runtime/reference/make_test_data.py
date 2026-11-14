#!/usr/bin/env python3
"""Generate the small committed fixtures under tests/data.

These let the model reader, the synthesizer graph and the index search be tested
without downloading anything: tiny voice models with random weights (built with the
reference's synthesizer classes and saved the way real models are), the reference's
output for random inputs with all noise set to zero, and a small FAISS index with the
neighbours FAISS returns. No trained weights or recorded audio are involved.

Run with the reference environment's interpreter; rewrites native/rvc-runtime/tests/data.
"""
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from setup_reference import reference_dir  # noqa: E402

DATA = HERE.parent / 'tests' / 'data'
# name: (version, f0, config). Channel counts are tiny; the layout is the real one.
MODELS = {
    'tiny_v2_f0_40k': ('v2', 1, [1025, 32, 4, 8, 16, 2, 2, 3, 0, '1', [3, 7, 11], [[1, 3, 5], [1, 3, 5], [1, 3, 5]],
                                 [10, 10, 2, 2], 16, [16, 16, 4, 4], 3, 4, 40000]),
    'tiny_v1_nof0_32k': ('v1', 0, [513, 32, 4, 8, 16, 2, 1, 3, 0, '2', [3, 5], [[1, 3], [1, 3]],
                                   [10, 8, 2, 2], 16, [20, 16, 4, 4], 2, 4, 32000]),
}
# Frame counts on both sides of the relative-attention window (10 frames either side).
LENGTHS = (5, 24)


def main():
    engine = reference_dir() / 'engine'
    os.chdir(engine)
    sys.path.insert(0, str(engine))
    import faiss
    import torch
    import infer.module.models as models
    torch.set_grad_enabled(False)
    DATA.mkdir(parents=True, exist_ok=True)
    zeros = lambda *size, **k: torch.zeros(*size, **{key: k[key] for key in ('device', 'dtype') if key in k})
    torch.randn_like, torch.rand, torch.randn = (lambda tensor, *a, **k: torch.zeros_like(tensor)), zeros, zeros
    rng = np.random.default_rng(20261115)
    for name, (version, f0, config) in MODELS.items():
        torch.manual_seed(len(name))
        kind = ('SynthesizerTrnMs768NSFsid' if version == 'v2' else 'SynthesizerTrnMs256NSFsid') + ('' if f0 else '_nono')
        net = getattr(models, kind)(*(config if f0 else config[:-1]), is_half=False).eval()
        weight = {key: value.half() for key, value in net.state_dict().items() if not key.startswith('enc_q')}
        torch.save({'weight': weight, 'config': config, 'f0': f0, 'version': version, 'info': 'random test weights'}, DATA / f'{name}.pth')
        # Run with the rounded weights, as a loader of the saved file would.
        net.load_state_dict({key: value.float() for key, value in weight.items()}, strict=False)
        width = 768 if version == 'v2' else 256
        for frames in LENGTHS:
            features = rng.standard_normal((1, frames, width)).astype(np.float32)
            speaker = torch.tensor([1])
            if f0:
                hz = rng.uniform(80, 400, frames).astype(np.float32)
                hz[frames // 2] = 0.0  # one unvoiced frame
                coarse = rng.integers(1, 256, frames).astype(np.int64)
                audio = net.infer(torch.from_numpy(features), torch.tensor([frames]), torch.from_numpy(coarse)[None],
                                  torch.from_numpy(hz)[None], speaker)[0]
                np.save(DATA / f'{name}_{frames}_coarse.npy', coarse)
                np.save(DATA / f'{name}_{frames}_hz.npy', hz)
            else:
                audio = net.infer(torch.from_numpy(features), torch.tensor([frames]), speaker)[0]
            np.save(DATA / f'{name}_{frames}_features.npy', features[0])
            np.save(DATA / f'{name}_{frames}_audio.npy', audio.numpy().reshape(-1))

    # A small inverted-file index like the ones voice model training writes.
    vectors = rng.standard_normal((600, 16)).astype(np.float32)
    index = faiss.index_factory(16, 'IVF12,Flat')
    index.train(vectors)
    index.nprobe = 1
    index.add(vectors)
    faiss.write_index(index, str(DATA / 'tiny_ivf.index'))
    queries = rng.standard_normal((40, 16)).astype(np.float32)
    distances, ids = index.search(queries, 8)
    np.save(DATA / 'tiny_ivf_queries.npy', queries)
    np.save(DATA / 'tiny_ivf_distances.npy', distances)
    np.save(DATA / 'tiny_ivf_ids.npy', ids.astype(np.int64))
    flat = faiss.IndexFlatL2(16)
    flat.add(vectors[:50])
    faiss.write_index(flat, str(DATA / 'tiny_flat.index'))
    empty = faiss.index_factory(16, 'IVF12,Flat')
    empty.train(vectors)
    faiss.write_index(empty, str(DATA / 'tiny_trained_only.index'))
    print('wrote', sorted(path.name for path in DATA.iterdir()))


if __name__ == '__main__':
    main()
