# SPDX-License-Identifier: GPL-3.0-only
"""External inference worker for permitted file-input PoC; no audio devices."""
import argparse
from contextlib import redirect_stdout
from pathlib import Path
import sys
from threading import Event, Thread
import time

from .blocks import BlockSession, require_fresh_block
from .loader import create_engine
from .offline import validate_reference
from .packets import write_packet
from .profiles import PROFILES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'assets', 'reference', 'input'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--profile', choices=PROFILES, default='baseline')
    args = parser.parse_args()
    stream = sys.stdout.buffer
    with redirect_stdout(sys.stderr):
        validate_reference(args.input)
        engine, _, _ = create_engine(args.engine, args.assets, args.reference)
        import librosa
        import numpy as np
        from scipy.signal import resample_poly
        engine.set_config(**PROFILES[args.profile])
        engine._prepare_buffers(channels=1)
        vc = BlockSession(engine)
        rate, size = engine.config.samplerate, engine.block_frame
        source, _ = librosa.load(str(args.input), sr=rate)
        # Warm three real inference blocks, then reset audio/VAD buffers.
        for _ in range(3):
            if vc.convert(np.zeros(size, dtype=np.float32)) is None:
                raise RuntimeError('vc_warmup_failed')
        engine._prepare_buffers(channels=1)
        start, stop, bypass, fault, hold, slow = (Event() for _ in range(6))

        def commands():
            for line in sys.stdin:
                command = line.strip()
                if command == 'start':
                    start.set()
                elif command == 'bypass':
                    bypass.set()
                elif command == 'fault':
                    fault.set()
                elif command == 'hold':
                    hold.set()
                elif command == 'slow':
                    slow.set()
                elif command == 'stop':
                    vc.stop()
                    stop.set()
                    return
            vc.stop()
            stop.set()

        Thread(target=commands, daemon=True).start()
        write_packet(stream, {'state': 'ready', 'block_ms': size / rate * 1000})
        while not start.wait(.02):
            if stop.is_set():
                return
        samples = np.pad(source, (0, rate * 4))
        samples = np.pad(samples, (0, -len(samples) % size))
        base = time.monotonic_ns()
        audible = np.flatnonzero(np.abs(source) > .002)
        source_onset_ns = base + int(audible[0] / rate * 1e9) if len(audible) else None
        for index, offset in enumerate(range(0, len(samples), size)):
            due = base + int((index + 1) * size / rate * 1e9)
            if stop.wait(max(0, (due - time.monotonic_ns()) / 1e9)):
                return
            if hold.is_set():
                stop.wait(30)
                return
            if bypass.is_set():
                engine.config.function = 'im'
            if fault.is_set():
                # Test-only real inference failure; exercise upstream catch/status.
                engine.model_set = (None, *engine.model_set[1:])
            before = time.monotonic_ns()
            lag_ms = (before - due) / 1e6
            try:
                require_fresh_block(due, before, size / rate * 1000)
                if slow.is_set():
                    time.sleep(3 * size / rate)
                output = vc.convert(samples[offset:offset + size])
                after = time.monotonic_ns()
                require_fresh_block(due, after, size / rate * 1000)
            except TimeoutError:
                write_packet(stream, {'state': 'overload', 'index': index,
                    'input_due_ns': due, 'input_ready_ns': before,
                    'inference_end_ns': time.monotonic_ns(), 'deadline_lag_ms': lag_ms})
                return
            info = {'state': vc.status, 'index': index, 'input_ready_ns': before,
                'input_due_ns': due, 'deadline_lag_ms': lag_ms,
                'inference_end_ns': after, 'source_onset_ns': source_onset_ns,
                'processing_ms': (after - before) / 1e6}
            if output is None:
                write_packet(stream, info)
                return
            converted = resample_poly(output, 320, 147)
            pcm = (np.clip(converted, -1, 1) * 32767).astype('<i2').tobytes()
            write_packet(stream, info, pcm)
        write_packet(stream, {'state': 'ended'})


if __name__ == '__main__':
    main()
