# SPDX-License-Identifier: GPL-3.0-only
"""Optional fixed Seed-VC worker for live PCM; no audio devices or downloads."""
import argparse
from contextlib import redirect_stdout
from pathlib import Path
import sys
import time

# The optional interpreter loads the application's light protocol, not its model.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src-python'))
from models.voice_conversion import protocol as p  # noqa: E402


def convert_packet(vc, info, pcm, session, sequence):
    import numpy as np
    from scipy.signal import resample_poly
    p.require_input(info, pcm, session, sequence, time.monotonic_ns())
    if vc.engine.config.samplerate != 22050 or vc.engine.block_frame != 1764:
        raise p.ProtocolError('vc_engine_format_invalid')
    data = resample_poly(np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768, 147, 320)
    output = vc.convert(data)
    if output is None:
        raise p.ProtocolError('vc_conversion_failed')
    converted = resample_poly(output, 320, 147)
    audio = (np.clip(converted, -1, 1) * 32767).astype('<i2').tobytes()
    result = dict(info, type='output', state=vc.status)
    p.require_output(result, audio, info, pcm, time.monotonic_ns())
    return result, audio


def _write(stream, info, pcm=b''):
    pending = memoryview(p.encode_packet(info, pcm))
    while pending:
        count = stream.write(pending)
        if count is None or count <= 0:
            raise p.ProtocolError('vc_worker_output_closed')
        pending = pending[count:]
    stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'assets', 'reference'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    ready = p.ready_info(args.session)
    output = sys.stdout.buffer
    with redirect_stdout(sys.stderr):
        from .loader import create_engine
        from .blocks import BlockSession
        from .profiles import PROFILES
        import numpy as np
        from scipy.signal import resample_poly
        resample_poly(np.zeros(p.FRAMES, dtype=np.float32), 147, 320)
        engine, _, _ = create_engine(args.engine, args.assets, args.reference)
        engine.set_config(**PROFILES['low'])
        engine._prepare_buffers(channels=1)
        if engine.config.samplerate != 22050 or engine.block_frame != 1764:
            raise p.ProtocolError('vc_engine_format_invalid')
        vc = BlockSession(engine)
        for _ in range(3):
            if vc.convert(np.zeros(engine.block_frame, dtype=np.float32)) is None:
                raise p.ProtocolError('vc_warmup_failed')
        engine._prepare_buffers(channels=1)
        _write(output, ready)
        sequence = 0
        while True:
            info, pcm = p.read_packet(sys.stdin.buffer, timeout=10 if sequence == 0 else 1)
            result, audio = convert_packet(vc, info, pcm, args.session, sequence)
            _write(output, result, audio)
            sequence += 1


if __name__ == '__main__':
    main()
