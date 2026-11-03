"""Fixed transport entry: capture/inference/output never share the UI heap."""
import os
import select
import sys
import time

from .direct_voice import create_worker_process
from .router_protocol import Reader, encode, validate_monitor_control
from models.audio_routing.monitor_output import parse_monitor
from models.audio_routing.source_bridge import parse_source


def main():
    process = None
    graph = observer = None
    try:
        from models.audio_routing.pipewire_graph_pipe import receive_from_parent
        graph = receive_from_parent()
        if graph is not None:
            observer = graph.subscribe()
        reader = Reader(sys.stdin.buffer)
        request = reader.read(timeout=5)
        if (not isinstance(request, dict) or request.get('kind') != 'start'
                or not {'kind', 'source', 'options'} <= set(request)
                or set(request) - {'kind', 'source', 'options', 'monitor', 'monitor_control'}):
            raise ValueError('vc_router_request_invalid')
        monitor = parse_monitor(request.get('monitor'))
        muted, revision = validate_monitor_control(request.get('monitor_control',
            dict(kind='monitor_mute', muted=True, revision=0)))
        # Drain controls already sent during launch, including EOF/Stop, before
        # creating any capture or inference resources.
        while reader.pending or select.select([sys.stdin.buffer], [], [], 0)[0]:
            try:
                muted, updated = validate_monitor_control(reader.read(timeout=1))
            except EOFError:
                return 0
            if updated <= revision:
                raise ValueError('vc_router_request_invalid')
            revision = updated
        source = parse_source(request['source'])
        process = (create_worker_process(request['options']) if monitor is None
                   else create_worker_process(request['options'], monitor=monitor))
        if monitor is not None:
            process.set_monitor_muted(muted)
        process.start(source=source)
        os.set_blocking(sys.stdout.fileno(), False)
        while True:
            if reader.pending or select.select([sys.stdin.buffer], [], [], .05)[0]:
                try:
                    muted, updated = validate_monitor_control(reader.read(timeout=1))
                except EOFError:
                    return 0  # Closing the owned control pipe is Stop.
                if updated <= revision:
                    raise ValueError('vc_router_request_invalid')
                if monitor is not None:
                    process.set_monitor_muted(muted)
                revision = updated
            state = process.health()
            state['monitor_revision'] = revision
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
    except (EOFError, OSError, ValueError, RuntimeError):
        return 1
    finally:
        if observer is not None:
            observer.close()
        if graph is not None:
            graph.close()
        if process is not None and not process.close(timeout=2):
            # Exiting also invokes the existing native parent-death chain.
            # The supervisor's nonzero status reports incomplete cleanup.
            raise SystemExit(2)


if __name__ == '__main__':
    raise SystemExit(main())
