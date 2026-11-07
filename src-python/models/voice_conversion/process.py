"""Single-use external VC worker owner; the application never imports Torch.

Capture delivery never waits for inference. Only validated, fresh worker output
reaches the explicitly bound managed sink. No original-audio fallback exists.
"""
from collections import deque
from queue import Empty, Full, Queue
import subprocess
from threading import Lock, Thread, current_thread
import time
from uuid import uuid4

try:
    from models.audio_routing.devices_pipewire import PipeWireOutput
except ImportError:  # fcntl. Windows writes through its device route instead.
    PipeWireOutput = None
from models.audio_routing.pipewire_graph import graph_source
from models.audio_routing.monitor_output import MonitorTee, parse_monitor
from models.audio_routing.source_bridge import _read_graph, _sink, select_source
from models.transcription.capture_pipewire import (
    CaptureError, PipeWireCapture, _validate, capture_error_code,
)
from models.owned_child import PipeWriter
from models.tts.speechcpp_tts import CancelToken, SpeechError
from . import protocol as p


# Device route: a block older than this is dropped instead of sent. More than half
# of six seconds of blocks late means this PC cannot keep up, and the voice stops.
LATE_NS = 240_000_000
LATE_WINDOW = 75


class _PipeWireRoute:
    """The managed sink; its OS gate owns mute, so writes need no gating here."""
    gates_output = False
    ready_timeout = 60
    input_blocks = 1
    drops_late_blocks = False

    def observe(self):
        return graph_source().subscribe()

    def bind(self, source, *, wait=True):
        return _binding(source, wait=wait)

    def output(self, sink):
        return _output(sink)

    def capture(self, source, on_audio, on_error):
        return PipeWireCapture(source, 'mic', on_audio, on_error)


def _route(output):
    if output is None:
        return _PipeWireRoute()
    from models.audio_routing.windows_route import WindowsRoute
    return WindowsRoute(output)


def _binding(source, *, wait=True):
    graph = _read_graph(wait=wait)
    if select_source(graph, source.name) != source:
        raise p.ProtocolError('vc_source_changed')
    return _sink(graph)


def _output(endpoint):
    return PipeWireOutput(endpoint.name, p.RATE, 1,
                          expected_identity=(endpoint.cookie, endpoint.serial))


class _Deadline:
    def __init__(self, token, end_ns, check_graph=lambda: None):
        self.token, self.end_ns = token, end_ns
        self.check_graph = check_graph

    def check(self):
        self.token.check()
        self.check_graph()
        p.require_fresh(self.end_ns, time.monotonic_ns())

    def commit_audio_write(self, pcm, write):
        # Stop and the nonblocking write use the same cancellation lock. Check
        # age after acquiring it too: waiting for readiness is not a commit.
        def fresh_write():
            self.check_graph()
            p.require_fresh(self.end_ns, time.monotonic_ns())
            return write()
        return self.token.commit_audio_write(pcm, fresh_write)


class VCProcess:
    def __init__(self, *, engine, monitor=None, output=None):
        self.engine = engine
        self._route = _route(output)
        # Optional local copy of the converted output; never on its critical path.
        self._monitor_choice = parse_monitor(monitor)
        self._monitor = None
        self._monitor_error = None
        self._monitor_lock = Lock()
        self._monitor_muted = True
        self._monitor_after_ns = 0
        self._monitor_retiring = False
        self._monitor_sink = None
        self._lock = Lock()
        self._queue = Queue(maxsize=self._route.input_blocks)
        self._partial = bytearray()
        self._first = self._last = self._sequence = self._sent = 0
        self._late = deque(maxlen=LATE_WINDOW)
        self._token = CancelToken()
        self._thread = self._capture = self._child = self._output = self._stdin = None
        self._requested = self._active = self._verified = self._pending = False
        self._error = None
        self._cleanup_ok = True
        self._state = 'off'
        self._session = uuid4().hex
        self._blocks = 0

    def _launch_worker(self):
        raise NotImplementedError

    def start(self, *, source):
        _validate(source, 'mic')
        with self._lock:
            if self._thread is not None or self._token.is_set():
                raise RuntimeError('vc_single_use')
            self._requested = self._pending = True
            self._state = 'preparing'
            self._thread = Thread(target=self._run, args=(source,), name='vrct-vc', daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._requested = self._active = self._verified = False
            self._token.cancel()
            self._partial.clear()
            capture = self._capture
        if capture is not None:
            capture.request_stop()

    def close(self, timeout=3):
        self.stop()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        return (thread is None or not thread.is_alive()) and self._cleanup_ok

    def health(self):
        with self._lock:
            return dict(requested=self._requested, active=self._active,
                        pending=self._pending, stopping=bool(self._thread and self._thread.is_alive()
                                                            and not self._requested),
                        conversion_verified=self._verified, error=self._error,
                        state=self._state, converted_blocks=self._blocks,
                        monitor_error=self._monitor_error)

    def _monitor_failed(self, code):
        # Monitor thread. A notice only: conversion and the managed sink go on.
        with self._lock:
            self._monitor_error = code

    def _monitor_ready(self):
        with self._lock:
            self._monitor_error = None

    def _open_monitor(self, sink):
        with self._monitor_lock:
            self._monitor_sink = sink.name

    def set_monitor_muted(self, muted):
        with self._monitor_lock:
            # Every control revision is a boundary, even if mute/resume were
            # coalesced in transit. Never reuse a cancelled tee or its queue.
            self._monitor_muted = muted
            self._monitor_after_ns = time.monotonic_ns()
            if self._monitor is not None:
                self._monitor.close(drain=False)
                self._monitor_retiring = True

    def _offer_monitor(self, converted, start_ns):
        with self._monitor_lock:
            if self._monitor_muted or start_ns < self._monitor_after_ns:
                return
            if self._monitor_retiring:
                # Never wait for a device on the conversion path, or overlap
                # a fresh monitor with an old device still being cancelled.
                if not self._monitor.join(0):
                    return
                self._monitor = None
                self._monitor_retiring = False
            if self._monitor is None:
                self._create_monitor()
            if self._monitor is not None:
                self._monitor.offer(converted, p.RATE, 1)

    def _audible(self, converted):
        if not self._route.gates_output:
            return converted
        with self._monitor_lock:
            return bytes(len(converted)) if self._monitor_muted else converted

    def _create_monitor(self):
        choice = self._monitor_choice
        if choice is None or self._monitor_sink is None:
            return
        try:
            self._monitor = MonitorTee(choice['device'], choice['volume'], exclude=(self._monitor_sink,),
                                       on_error=self._monitor_failed, on_ready=self._monitor_ready)
        except Exception:
            self._monitor_failed('monitor_output_error')

    def _fail(self, code):
        with self._lock:
            if not self._token.is_set():
                self._error = code
                self._state = 'failed'
        self.stop()

    def _capture_failed(self, code):
        safe = capture_error_code(code)
        self._fail('vc_capture_failed' if safe == 'asr_capture_failed' else safe)

    def _audio(self, captured):
        fault = None
        with self._lock:
            if not self._requested or self._token.is_set():
                return False
            audio, stamp = captured.audio, captured.captured_ns
            if (audio.sample_rate != p.RATE or audio.channels != 1 or len(audio.pcm) != 1920
                    or type(stamp) is not int or not self._last < stamp <= time.monotonic_ns()):
                fault = 'vc_capture_invalid'
            else:
                self._last = stamp
                if not self._partial:
                    self._first = stamp
                self._partial.extend(audio.pcm)
                if len(self._partial) == p.PCM_BYTES:
                    info = dict(p.input_info(self._session, self._sequence, self._first),
                                pcm_bytes=p.PCM_BYTES)
                    try:
                        self._queue.put_nowait((info, bytes(self._partial)))
                    except Full:
                        if not self._route.drops_late_blocks or self._replace_oldest(info):
                            fault = 'vc_capture_overrun'
                    self._sequence += 1
                    self._partial.clear()
        if fault:
            self._fail(fault)
            return False
        return True

    def _too_late(self, late):
        self._late.append(late)
        return sum(self._late) > LATE_WINDOW // 2

    def _replace_oldest(self, info):
        # Capture thread, the only producer, holding the lock.
        try:
            self._queue.get_nowait()
        except Empty:
            pass
        self._queue.put_nowait((info, bytes(self._partial)))
        return self._too_late(True)

    def _next_block(self, info):
        """Device route: this block as the worker's next one, or None if it came too late.

        A stall on a busy PC costs a gap in the voice rather than the whole session.
        The worker checks that sequence numbers run on, so they are given here.
        """
        with self._lock:
            late = time.monotonic_ns() - info['end_ns'] > LATE_NS
            if self._too_late(late):
                raise p.ProtocolError('vc_capture_overrun')
            if late:
                return None
            info = dict(info, sequence=self._sent)
            self._sent += 1
            return info

    def _send(self, info, pcm, deadline):
        wire = memoryview(p.encode_packet(info, pcm))
        while wire:
            deadline.check()
            if self._child.poll() is not None:
                raise p.ProtocolError('vc_worker_eof')
            if not self._stdin.wait(.02):
                continue
            deadline.check()
            try:
                count = self._stdin.write(wire)
                if count <= 0:
                    raise p.ProtocolError('vc_worker_eof')
                wire = wire[count:]
            except BlockingIOError:
                continue

    def _run(self, source):
        observer = None
        try:
            observer = self._route.observe()
            sink = self._route.bind(source)
            self._token.check()
            self._child = self._launch_worker()
            self._stdin = PipeWriter(self._child.stdin)
            info, pcm = p.read_packet(self._child.stdout, timeout=self._route.ready_timeout,
                                      check=self._token.check)
            p.require_ready(info, pcm, self._session, engine=self.engine)
            self._token.check()
            if self._route.bind(source) != sink:
                raise p.ProtocolError('vc_sink_changed')
            self._output = self._route.output(sink)
            self._open_monitor(sink)
            self._token.check()
            capture = self._route.capture(source, self._audio, self._capture_failed)
            with self._lock:
                self._capture = capture
                if self._token.is_set():
                    capture.request_stop()
            self._token.check()
            capture.start()
            with self._lock:
                self._token.check()
                self._active, self._pending, self._state = True, False, 'ready'
            def check_binding():
                if self._route.bind(source, wait=False) != sink:
                    raise p.ProtocolError('vc_sink_changed')

            while True:
                self._token.check()
                if self._child.poll() is not None:
                    raise p.ProtocolError('vc_worker_eof')
                check_binding()
                try:
                    info, pcm = self._queue.get(timeout=.02)
                except Empty:
                    continue
                if self._route.drops_late_blocks:
                    info = self._next_block(info)
                    if info is None:
                        continue
                deadline = _Deadline(self._token, info['end_ns'], check_binding)
                deadline.check()
                self._send(info, pcm, deadline)
                result, converted = p.read_packet(self._child.stdout, timeout=1, check=deadline.check)
                state = p.require_output(result, converted, info, pcm, time.monotonic_ns())
                deadline.check()
                self._output.write(self._audible(converted), deadline)
                # Queue only, after the managed write: the same block, no added wait.
                self._offer_monitor(converted, info['start_ns'])
                deadline.check()
                with self._lock:
                    self._token.check()
                    if state == 'converted':
                        self._verified = True
                        self._blocks += 1
                    self._state = 'converted' if state == 'converted' else 'idle'
        except CaptureError as exc:
            self._capture_failed(str(exc))
        except Exception as exc:
            code = str(exc) if isinstance(exc, (p.ProtocolError, SpeechError)) else 'vc_worker_failed'
            self._fail(code)
        finally:
            self.stop()
            for cleanup in (self._stop_capture, self._stop_output, self._stop_monitor, self._stop_child):
                try:
                    cleanup()
                except Exception:
                    with self._lock:
                        self._error = self._error or 'vc_cleanup_failed'
                        self._cleanup_ok = False
            if observer is not None:
                observer.close()
            with self._lock:
                self._pending = False
                self._state = 'failed' if self._error else 'stopped'
                while not self._queue.empty():
                    self._queue.get_nowait()

    def _stop_capture(self):
        if self._capture is not None:
            self._capture.stop()

    def _stop_monitor(self):
        # After the managed output. The monitor thread reaps its own device; a
        # slow monitor never marks VC cleanup as incomplete.
        with self._monitor_lock:
            self._monitor_muted = True
            monitor = self._monitor
            if monitor is not None:
                monitor.close(drain=False)
        if monitor is not None:
            monitor.join(1.5)

    def _stop_output(self):
        if self._output is not None:
            self._output.close(drain=False, token=self._token)

    def _stop_child(self):
        if self._child is not None:
            try:
                if self._child.poll() is None:
                    self._child.terminate()
                    try:
                        self._child.wait(.5)
                    except subprocess.TimeoutExpired:
                        self._child.kill()
                        self._child.wait(.5)
            finally:
                if self._stdin is not None:
                    self._stdin.close()
                self._child.stdin.close()
                self._child.stdout.close()
