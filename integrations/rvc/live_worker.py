# SPDX-License-Identifier: MIT
"""Fixed local RVC worker: binary PCM pipes, no devices and no downloads."""
import argparse
from contextlib import redirect_stdout
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src-python'))
from models.voice_conversion import protocol as p
from models.voice_conversion.settings import start_options


def convert_packet(vc, info, pcm, session, sequence):
    import numpy as np
    p.require_input(info, pcm, session, sequence, time.monotonic_ns())
    data = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
    output = vc.convert(data)
    if output.shape != (p.FRAMES,) or not np.isfinite(output).all():
        raise p.ProtocolError('vc_conversion_invalid')
    audio = np.clip(np.rint(output * 32768), -32768, 32767).astype('<i2').tobytes()
    result = dict(info, type='output', state='converted')
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
    for name in ('engine', 'assets', 'model', 'session'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--index', default='')
    parser.add_argument('--pitch', type=int, default=0)
    parser.add_argument('--index-rate', type=float, default=0)
    args = parser.parse_args()
    start_options('converted', dict(engine='rvc', runtime=args.engine, model=args.model,
                                   index=args.index, pitch=args.pitch, index_rate=args.index_rate))
    ready = p.ready_info(args.session, engine='rvc')
    output = sys.stdout.buffer
    with redirect_stdout(sys.stderr):
        from .loader import create_engine
        import numpy as np
        engine = create_engine(args.engine, args.assets, args.model, args.index, args.pitch, args.index_rate)
        from .blocks import BlockSession
        vc = BlockSession(engine)
        tone = (.1 * np.sin(np.arange(p.FRAMES) * (2*np.pi*220/p.RATE))).astype(np.float32)
        for _ in range(3):
            vc.convert(tone)
        vc.reset()
        _write(output, ready)
        sequence = 0
        while True:
            info, pcm = p.read_packet(sys.stdin.buffer, timeout=10 if sequence == 0 else 1)
            result, audio = convert_packet(vc, info, pcm, args.session, sequence)
            _write(output, result, audio)
            sequence += 1


if __name__ == '__main__':
    main()
