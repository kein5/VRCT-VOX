"""Fixed transport entry: capture/inference/output never share the UI heap."""
import os
import select
import sys
import time

from .direct_voice import create_worker_process
from .router_protocol import Reader, encode
from models.audio_routing.source_bridge import parse_source


def main():
    process = None
    try:
        reader = Reader(sys.stdin.buffer)
        request = reader.read(timeout=5)
        if not isinstance(request, dict) or set(request) != {'kind', 'source', 'options'} or request['kind'] != 'start':
            raise ValueError('vc_router_request_invalid')
        if reader.pending or select.select([sys.stdin.buffer], [], [], 0)[0]:
            return 1  # Extra buffered control or Stop before capture starts.
        source = parse_source(request['source'])
        process = create_worker_process(request['options'])
        process.start(source=source)
        os.set_blocking(sys.stdout.fileno(), False)
        while True:
            state = process.health()
            frame = encode(dict(kind='health', sent_ns=time.monotonic_ns(), **state))
            # Health is a replaceable snapshot. An unread health pipe must never
            # delay control EOF/Stop or the audio thread. Writes below PIPE_BUF
            # are atomic: EAGAIN drops this snapshot, never half a JSON frame.
            if len(frame) > 4096:
                return 1
            try:
                os.write(sys.stdout.fileno(), frame)
            except BlockingIOError:
                pass
            if state['error']:
                return 1
            if select.select([sys.stdin.buffer], [], [], .05)[0]:
                # Closing the owned control pipe is Stop. Any extra command is
                # invalid too: a router is single-use and never changes source.
                if os.read(sys.stdin.fileno(), 1):
                    return 1
                return 0
    except (EOFError, OSError, ValueError, RuntimeError):
        return 1
    finally:
        if process is not None and not process.close(timeout=2):
            # Exiting also invokes the existing native parent-death chain.
            # The supervisor's nonzero status reports incomplete cleanup.
            raise SystemExit(2)


if __name__ == '__main__':
    raise SystemExit(main())
