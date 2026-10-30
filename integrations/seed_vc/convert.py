# SPDX-License-Identifier: GPL-3.0-only
"""Offline block-conversion measurement, without an OS audio device."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import wave

from .blocks import BlockSession
from .loader import create_engine
from .offline import validate_reference
from .profiles import PROFILES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'assets', 'reference', 'input', 'output', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--profile', choices=PROFILES, default='baseline')
    args = parser.parse_args()
    source_metadata = validate_reference(args.input)
    if args.output.exists() or args.report.exists():
        raise FileExistsError('new_output_paths_required')
    engine, checkpoints, reference = create_engine(args.engine, args.assets, args.reference)
    import librosa
    import numpy as np
    import torch
    engine.set_config(**PROFILES[args.profile])
    engine._prepare_buffers(channels=1)
    rate, size = engine.config.samplerate, engine.block_frame
    samples, _ = librosa.load(str(args.input), sr=rate)
    # Pre-roll for model warmup; tail to flush the fixed right context.
    samples = np.pad(samples, (rate * 3, rate * 3))
    samples = np.pad(samples, (0, -len(samples) % size))
    vc = BlockSession(engine)
    rows, outputs = [], []
    for offset in range(0, len(samples), size):
        torch.cuda.synchronize()
        start = time.monotonic_ns()
        out = vc.convert(samples[offset:offset + size])
        torch.cuda.synchronize()
        end = time.monotonic_ns()
        row = {'index': len(rows), 'start_ns': start, 'end_ns': end,
               'processing_ms': (end - start) / 1e6, 'status': vc.status}
        rows.append(row)
        print(json.dumps(row), flush=True)
        if out is None:
            break
        outputs.append(out.copy())
    joined = np.concatenate(outputs) if outputs else np.empty(0, dtype=np.float32)
    pcm = (np.clip(joined, -1, 1) * 32767).astype('<i2').tobytes()
    with args.output.open('xb') as stream:
        args.output.chmod(0o600)
        with wave.open(stream, 'wb') as output:
            output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            output.writeframes(pcm)
    steady = [r['processing_ms'] for r in rows[3:]]
    report = {'scope': 'offline model block processing only; no OS/VRChat latency', 'profile': args.profile,
        'source': source_metadata, 'reference': reference, 'checkpoints': checkpoints,
        'sample_rate': rate, 'block_samples': size, 'block_ms': size / rate * 1000,
        'diffusion_steps': engine.config.diffusion_steps, 'fp16': engine.fp16,
        'extra_time_ce': engine.config.extra_time_ce, 'extra_time': engine.config.extra_time,
        'extra_time_right': engine.config.extra_time_right, 'crossfade_time': engine.config.crossfade_time,
        'max_prompt_length': engine.config.max_prompt_length,
        'warmup_blocks_excluded': 3, 'blocks': rows,
        'processing_p50_ms': float(np.percentile(steady, 50)) if steady else None,
        'processing_p95_ms': float(np.percentile(steady, 95)) if steady else None,
        'blocks_over_duration': sum(t > size / rate * 1000 for t in steady),
        'converted_blocks': sum(r['status'] == 'converted' for r in rows),
        'nonzero_samples': int(np.count_nonzero(np.abs(joined) > .002)),
        'output_sha256': hashlib.sha256(pcm).hexdigest(), 'output_duration_s': len(joined) / rate,
        'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
        'audio_device_module_loaded': 'sounddevice' in sys.modules, 'failure': vc.error}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    return 1 if vc.status == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
