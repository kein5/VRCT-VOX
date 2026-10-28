"""Single-use external VC worker owner; the application never imports Torch.

Capture delivery never waits for inference. Only validated, fresh worker output
reaches the explicitly bound managed sink. No original-audio fallback exists.
"""
import os
from queue import Empty, Full, Queue
import select
import subprocess
from threading import Lock, Thread, current_thread
import time
from uuid import uuid4

from models.audio_routing.devices_pipewire import PipeWireOutput
from models.audio_routing.source_bridge import _read_graph, _sink, select_source
from models.transcription.capture_pipewire import (
    CaptureError, PipeWireCapture, _validate, capture_error_code,
)
from models.tts.speechcpp_tts import CancelToken, SpeechError
from . import protocol as p

def _binding(source):
    graph = _read_graph()
    if select_source(graph, source.name) != source:
        raise p.ProtocolError('vc_source_changed')
    return _sink(graph)


def _output(endpoint):
    return PipeWireOutput(endpoint.name, p.RATE, 1,
                          expected_identity=(endpoint.cookie, endpoint.serial))


class _Deadline:
    def __init__(self, token, end_ns):
        self.token, self.end_ns = token, end_ns

    def check(self):
        self.token.check()
        p.require_fresh(self.end_ns, time.monotonic_ns())

    def commit_audio_write(self, pcm, write):
        # Stop and the nonblocking write use the same cancellation lock. Check
        # age after acquiring it too: waiting for readiness is not a commit.
        def fresh_write():
            p.require_fresh(self.end_ns, time.monotonic_ns())
            return write()
        return self.token.commit_audio_write(pcm, fresh_write)


class VCProcess:
    def __init__(self, *, engine):
        self.engine = engine
        self._lock = Lock()
        self._queue = Queue(maxsize=1)
        self._partial = bytearray()
        self._first = self._last = self._sequence = 0
        self._token = CancelToken()
        self._thread = self._capture = self._child = self._output = None
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
                        state=self._state, converted_blocks=self._blocks)

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
                        fault = 'vc_capture_overrun'
                    self._sequence += 1
                    self._partial.clear()
        if fault:
            self._fail(fault)
            return False
        return True

    def _send(self, info, pcm, deadline):
        wire = memoryview(p.encode_packet(info, pcm))
        while wire:
            deadline.check()
            if self._child.poll() is not None:
                raise p.ProtocolError('vc_worker_eof')
            if not select.select([], [self._child.stdin], [], .02)[1]:
                continue
            deadline.check()
            try:
                count = os.write(self._child.stdin.fileno(), wire)
                if count <= 0:
                    raise p.ProtocolError('vc_worker_eof')
                wire = wire[count:]
            except BlockingIOError:
                continue

    def _run(self, source):
        try:
            sink = _binding(source)
            self._token.check()
            self._child = self._launch_worker()
            os.set_blocking(self._child.stdin.fileno(), False)
            info, pcm = p.read_packet(self._child.stdout, timeout=60, check=self._token.check)
            p.require_ready(info, pcm, self._session, engine=self.engine)
            self._token.check()
            if _binding(source) != sink:
                raise p.ProtocolError('vc_sink_changed')
            self._output = _output(sink)
            self._token.check()
            capture = PipeWireCapture(source, 'mic', self._audio,
                                      self._capture_failed)
            with self._lock:
                self._capture = capture
                if self._token.is_set():
                    capture.request_stop()
            self._token.check()
            capture.start()
            with self._lock:
                self._token.check()
                self._active, self._pending, self._state = True, False, 'ready'
            checked = 0
            while True:
                self._token.check()
                if self._child.poll() is not None:
                    raise p.ProtocolError('vc_worker_eof')
                if time.monotonic() - checked >= .1:
                    if _binding(source) != sink:
                        raise p.ProtocolError('vc_sink_changed')
                    checked = time.monotonic()
                try:
                    info, pcm = self._queue.get(timeout=.02)
                except Empty:
                    continue
                deadline = _Deadline(self._token, info['end_ns'])
                deadline.check()
                self._send(info, pcm, deadline)
                result, converted = p.read_packet(self._child.stdout, timeout=1, check=deadline.check)
                state = p.require_output(result, converted, info, pcm, time.monotonic_ns())
                deadline.check()
                self._output.write(converted, deadline)
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
            for cleanup in (self._stop_capture, self._stop_output, self._stop_child):
                try:
                    cleanup()
                except Exception:
                    with self._lock:
                        self._error = self._error or 'vc_cleanup_failed'
                        self._cleanup_ok = False
            with self._lock:
                self._pending = False
                self._state = 'failed' if self._error else 'stopped'
                while not self._queue.empty():
                    self._queue.get_nowait()

    def _stop_capture(self):
        if self._capture is not None:
            self._capture.stop()

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
                self._child.stdin.close()
                self._child.stdout.close()
