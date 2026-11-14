"""Fixed transport entry: capture/inference/output never share the UI heap."""
import sys
import time

from .direct_voice import create_worker_process
from .router_protocol import Reader, control_kind, encode, speech_pcm, validate_monitor_control
from models.audio_routing.monitor_output import parse_monitor
from models.audio_routing.source_bridge import parse_source
from models.owned_child import PipeWriter, wait_readable


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
                or set(request) - {'kind', 'source', 'options', 'monitor', 'monitor_control', 'output'}):
            raise ValueError('vc_router_request_invalid')
        monitor = parse_monitor(request.get('monitor'))
        output = request.get('output')
        if output is not None and (not isinstance(output, str) or not output or len(output) > 512):
            raise ValueError('vc_router_request_invalid')
        # With a device route the mute intent gates the main output, not only a monitor.
        controlled = monitor is not None or output is not None
        control = request.get('monitor_control', dict(kind='monitor_mute', muted=True, revision=0))
        muted, revision = validate_monitor_control(control)
        suppressed = control.get('suppressed', False)
        # Drain controls already sent during launch, including EOF/Stop, before
        # creating any capture or inference resources. Speech cannot play yet.
        while reader.pending or wait_readable(sys.stdin.buffer, 0):
            try:
                frame = reader.read(timeout=1)
            except EOFError:
                return 0
            if control_kind(frame) != 'monitor_mute':
                continue
            muted, updated = validate_monitor_control(frame)
            if updated <= revision:
                raise ValueError('vc_router_request_invalid')
            revision, suppressed = updated, frame.get('suppressed', False)
        source = parse_source(request['source'])
        extra = {} if monitor is None else {'monitor': monitor}
        if output is not None:
            extra['output'] = output
        process = create_worker_process(request['options'], **extra)
        if controlled:
            process.set_monitor_muted(muted)
        process.set_direct_suppressed(suppressed)
        process.start(source=source)
        health = PipeWriter(sys.stdout)
        while True:
            # Speech arrives in 80 ms frames; read all that is there before the next snapshot.
            while reader.pending or wait_readable(sys.stdin.buffer, .05):
                try:
                    frame = reader.read(timeout=1)
                except EOFError:
                    return 0  # Closing the owned control pipe is Stop.
                kind = control_kind(frame)
                if kind == 'speech':
                    process.speech_chunk(speech_pcm(frame))  # Beyond its bound it is dropped.
                elif kind == 'speech_end':
                    process.speech_end()
                elif kind == 'speech_cancel':
                    process.speech_cancel()
                else:
                    muted, updated = validate_monitor_control(frame)
                    if updated <= revision:
                        raise ValueError('vc_router_request_invalid')
                    if controlled:
                        process.set_monitor_muted(muted)
                    process.set_direct_suppressed(frame.get('suppressed', False))
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
                health.write(frame)
            except BlockingIOError:
                pass
            if state['error']:
                health.flush(.2)
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
