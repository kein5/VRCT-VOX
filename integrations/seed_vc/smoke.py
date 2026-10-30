# SPDX-License-Identifier: GPL-3.0-only
"""Consented model-load/VAD test. Does not open an audio device or claim VC."""
import argparse
import json
from pathlib import Path
import time
import sys

from .loader import create_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'assets', 'reference', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    engine, checkpoints, metadata = create_engine(args.engine, args.assets, args.reference)
    import librosa
    import torch
    import torchaudio
    loaded = time.monotonic()
    samples, _ = librosa.load(str(args.reference), sr=16000)
    chunk_size = 200
    step = chunk_size * 16
    cache, segments, chunks = {}, [], 0
    for offset in range(0, len(samples), step):
        result = engine.vad_model.generate(input=samples[offset:offset + step], cache=cache,
            is_final=offset + step >= len(samples), chunk_size=chunk_size)
        segments.extend(result[0]['value'])
        chunks += 1
    torch.cuda.synchronize()
    report = {'model_ready': True, 'converted': False, 'checkpoints': checkpoints,
        'reference': metadata, 'vad_chunks': chunks, 'vad_segments': len(segments),
        'load_s': loaded - started, 'vad_test_s': time.monotonic() - loaded,
        'torch': torch.__version__, 'torchaudio': torchaudio.__version__,
        'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(),
        'audio_device_module_loaded': 'sounddevice' in sys.modules,
        'peak_allocated_bytes': torch.cuda.max_memory_allocated()}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
