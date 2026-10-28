"""Single-use Linux capture owner; no default-device fallback or PCM logging.

Callbacks run on the capture thread and must return promptly. on_audio returns
False to reject input (for example, a closed RealtimeIngress). stop() reaps the
native helper even if a callback misbehaves; a busy callback is reported rather
than claiming that all Python delivery has stopped.
"""
import os
from pathlib import Path
import select
import subprocess
import sys
from threading import Event, Lock, Thread, current_thread, get_native_id
import time
from uuid import uuid4

from models.audio_routing.source_bridge import Endpoint, _endpoint, _node, _read_graph
from .capture_packets import CapturePackets

HELPER = Path(__file__).resolve().parents[3] / 'build' / 'vrct-asr-capture'
EXCLUDED = ('vrct.managed.', 'vrct.source-bridge.', 'vrct.asr.capture.')
_NATIVE_ERRORS = frozenset('asr_capture_' + code for code in (
    'owner_gone stalled core_changed core_error stream_disconnected clock_changed '
    'latency_removed format_removed format_invalid latency_invalid latency_changed '
    'stream_identity_invalid clock_snapshot_inconsistent clock_position_missing '
    'clock_invalid buffer_corrupted discontinuity buffer_invalid timestamp_invalid '
    'stale_buffer pipe_blocked endpoint_changed unexpected_link endpoint_removed '
    'link_removed endpoint_missing stream_create_failed stream_connect_failed'
).split())
_ERRORS = _NATIVE_ERRORS | frozenset('asr_capture_' + code for code in (
    'single_use start_timeout stopped consumer_busy consumer_closed helper_closed failed'
).split())


class CaptureError(RuntimeError):
    """A fixed diagnostic code without device names, PCM, or exception bodies."""


def capture_error_code(code):
    return code if isinstance(code, str) and code in _ERRORS else 'asr_capture_failed'


class _NativeDiagnostics:
    """Drain stderr without storing arbitrary driver messages or unbounded lines."""
    def __init__(self):
        self.code = None
        self._line = bytearray()
        self._overflow = False

    def read(self, stream):
        # Bound work per capture iteration too; stdout delivery must not starve.
        for _ in range(16):
            try:
                raw = os.read(stream.fileno(), 4096)
            except BlockingIOError:
                break
            if not raw:
                break
            for byte in raw:
                if byte == 10:
                    if not self._overflow:
                        code = self._line.decode('ascii', errors='replace')
                        if code in _NATIVE_ERRORS and self.code is None:
                            self.code = code
                    self._line.clear()
                    self._overflow = False
                elif not self._overflow:
                    if len(self._line) < 96:
                        self._line.append(byte)
                    else:
                        self._line.clear()
                        self._overflow = True
        return self.code


def _validate(endpoint, source):
    if (source not in ('mic', 'speaker') or not isinstance(endpoint, Endpoint)
            or type(endpoint.cookie) is not int or not 0 <= endpoint.cookie < 2**32
            or type(endpoint.serial) is not int or not 0 <= endpoint.serial < 2**64
            or not isinstance(endpoint.name, str) or not endpoint.name
            or '\0' in endpoint.name or len(endpoint.name.encode('utf-8')) > 512
            or endpoint.name.startswith(EXCLUDED)
            or endpoint.media_class != ('Audio/Source' if source == 'mic' else 'Audio/Sink')):
        raise ValueError('asr_capture_endpoint_invalid')


def _select(graph, name, source):
    endpoint = _endpoint(graph, name, 'Audio/Source' if source == 'mic' else 'Audio/Sink')
    _validate(endpoint, source)
    props = _node(graph, name)['info']['props']
    if any(key in props for key in ('vrct.managed.route', 'vrct.source.bridge', 'vrct.asr.capture')):
        raise ValueError('asr_capture_feedback_endpoint')
    return endpoint


def enumerate_endpoints(source):
    """Explicit microphone sources or speaker sinks; never resolve a default."""
    if sys.platform != 'linux' or source not in ('mic', 'speaker'):
        raise ValueError('asr_capture_source_invalid')
    graph = _read_graph()
    result = []
    for item in graph:
        if item.get('type') != 'PipeWire:Interface:Node':
            continue
        props = item.get('info', {}).get('props', {})
        name = props.get('node.name')
        try:
            endpoint = _select(graph, name, source)
        except (RuntimeError, ValueError, KeyError, TypeError):
            continue
        label = props.get('node.description')
        result.append({'endpoint': endpoint, 'label': label if isinstance(label, str) and label else name})
    return result


class PipeWireCapture:
    def __init__(self, endpoint, source, on_audio, on_error, *, helper=HELPER):
        _validate(endpoint, source)
        if sys.platform != 'linux':
            raise RuntimeError('asr_capture_linux_only')
        self.endpoint, self.source = endpoint, source
        self._on_audio, self._on_error = on_audio, on_error
        self._helper = Path(helper)
        self._stop = Event()
        self._ready = Event()
        self._lock = Lock()
        self._reap_lock = Lock()
        self._thread = self._process = None
        self._error = None

    def start(self):
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                raise CaptureError('asr_capture_single_use')
            self._thread = Thread(target=self._run, name='asr-capture', daemon=True)
            self._thread.start()
        if not self._ready.wait(5):
            self.stop()
            raise CaptureError('asr_capture_start_timeout')
        if self._error or self._stop.is_set():
            self.stop()
            raise CaptureError(self._error or 'asr_capture_stopped')

    def _reap(self):
        with self._reap_lock:
            with self._lock:
                process = self._process
            if process is None:
                return
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(.2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(.2)
                except ProcessLookupError:
                    pass

    def request_stop(self):
        """Invalidate pending startup/delivery without joining or touching a driver."""
        self._stop.set()
        self._ready.set()

    def stop(self):
        self.request_stop()
        self._reap()
        with self._lock:
            thread = self._thread
        if thread and thread is not current_thread():
            thread.join(.5)
            if thread.is_alive():
                raise CaptureError('asr_capture_consumer_busy')

    def _launch(self):
        if _select(_read_graph(), self.endpoint.name, self.source) != self.endpoint:
            raise CaptureError('asr_capture_endpoint_changed')
        fd = os.pidfd_open(get_native_id(), os.O_EXCL)
        try:
            with self._lock:
                if self._stop.is_set():
                    return None
                self._process = subprocess.Popen([
                    str(self._helper), str(os.getpid()), str(fd), str(self.endpoint.cookie),
                    str(self.endpoint.serial), self.endpoint.name, self.source, uuid4().hex,
                ], pass_fds=(fd,), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, bufsize=0)
                return self._process
        finally:
            os.close(fd)

    def _run(self):
        decoder = CapturePackets()
        diagnostics = _NativeDiagnostics()
        process = None
        try:
            process = self._launch()
            if process is None:
                return
            os.set_blocking(process.stderr.fileno(), False)
            while not self._stop.is_set():
                if code := diagnostics.read(process.stderr):
                    raise CaptureError(code)
                if process.poll() is not None:
                    raise CaptureError(diagnostics.read(process.stderr) or 'asr_capture_helper_closed')
                if not select.select([process.stdout], [], [], .05)[0]:
                    continue
                raw = os.read(process.stdout.fileno(), 4096)
                if not raw:
                    raise CaptureError(diagnostics.read(process.stderr) or 'asr_capture_helper_closed')
                for frame in decoder.feed(raw, time.monotonic_ns()):
                    if self._stop.is_set():
                        break
                    if self._on_audio(frame) is False:
                        raise CaptureError('asr_capture_consumer_closed')
                    self._ready.set()
        except Exception as exc:
            if not self._stop.is_set():
                self._error = capture_error_code(str(exc)) if isinstance(exc, CaptureError) else 'asr_capture_failed'
                self._stop.set()
                self._ready.set()
                try:
                    self._on_error(self._error)
                except Exception:
                    pass
        finally:
            self._stop.set()
            self._ready.set()
            decoder.close()
            self._reap()
            if process:
                process.stdout.close()
                process.stderr.close()
