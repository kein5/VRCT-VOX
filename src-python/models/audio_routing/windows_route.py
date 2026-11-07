"""Windows direct voice. A chosen output device stands in for the managed sink.

Windows has no private virtual microphone to create, so the user's cable is the
route: voice is written to its playback end and VRChat records from the other.
No OS gate sits behind that device, so mute is applied here by writing silence.
Writing silence, rather than stopping, keeps the stream and its timing alive.
"""
from queue import Empty, Full, Queue
from threading import Lock, Thread, current_thread
import time

from models.tts.speechcpp_tts import CancelToken, SpeechError
from .devices_windows import WindowsOutput, enumerate_outputs, same_virtual_cable
from .source_bridge import Endpoint, _source_id

RATE = 48000
# A device that took nothing for this long is gone, not slow. A write to an
# unplugged device may never return, so no error would come from the stream.
OUTPUT_STALL_S = 2


class _NoObserver:
    def close(self):
        pass


def _check_devices(source, output):
    if output not in [row['id'] for row in enumerate_outputs((output,))]:
        raise RuntimeError('vc_output_missing')
    if same_virtual_cable(source.name, output):
        raise RuntimeError('vc_feedback_blocked')


def _replace_oldest(queue, item):
    """Speech that old is worth less than speech on time."""
    try:
        queue.get_nowait()
        queue.put_nowait(item)
    except (Empty, Full):
        pass


class QueuedOutput:
    """Device writes on their own thread.

    A PortAudio write blocks for about the length of the audio, so writing inside
    the conversion loop adds a block's duration to every block and overruns capture.
    The queue also absorbs a late block. When it is full the oldest block goes.
    """
    def __init__(self, device):
        self._output = WindowsOutput(device, RATE, 1, strict_underflow=False)
        self._queue = Queue(maxsize=4)
        self._token = CancelToken()
        self._failed = False
        self._written = time.monotonic()
        self._thread = Thread(target=self._run, name='vrct-vc-output', daemon=True)
        self._thread.start()

    def _run(self):
        try:
            while True:
                pcm = self._queue.get()
                if pcm is None:
                    return
                self._output.write(pcm, self._token)
                self._written = time.monotonic()
        except Exception:
            self._failed = True

    def write(self, pcm, token):
        token.check()
        if self._failed:
            raise SpeechError('vc_output_failed')
        try:
            self._queue.put_nowait(pcm)
        except Full:
            if time.monotonic() - self._written > OUTPUT_STALL_S:
                raise SpeechError('vc_output_failed') from None
            _replace_oldest(self._queue, pcm)

    def close(self, *, drain, token):
        self._token.cancel()
        while True:
            try:
                self._queue.put_nowait(None)
                break
            except Full:
                try:
                    self._queue.get_nowait()
                except Empty:
                    pass
        self._thread.join(1)
        self._output.close(drain=drain, token=token)


class WindowsRoute:
    """The capture and output of a converted voice, in place of the PipeWire graph."""
    gates_output = True
    # Loading Torch took 53 s here with warm caches; a real-time scan adds more.
    ready_timeout = 180
    input_blocks = 4
    drops_late_blocks = True

    def __init__(self, output):
        self.device = output
        self._sink = Endpoint(0, 0, output, 'Audio/Sink')

    def observe(self):
        return _NoObserver()

    def bind(self, source, *, wait=True):
        # Enumerating opens PortAudio, too slow for every audio block. A device
        # lost later surfaces as an error from its own stream.
        if wait:
            _check_devices(source, self.device)
        return self._sink

    def output(self, sink):
        return QueuedOutput(sink.name)

    def capture(self, source, on_audio, on_error):
        from models.transcription.capture_windows import WindowsCapture
        return WindowsCapture(source, 'mic', on_audio, on_error)


class WindowsBridge:
    """The original microphone to the output device, for when no conversion runs."""
    def __init__(self, output):
        self.device = output
        self._lock = Lock()
        self._queue = Queue(maxsize=8)
        self._token = CancelToken()
        self._thread = self._capture = self._source = None
        self._requested = self._active = self._pending = False
        self._muted = True
        self._error = None
        self._observation = 0
        self._written = time.monotonic()

    def set_monitor_muted(self, muted):
        with self._lock:
            self._muted = bool(muted)

    def health(self):
        with self._lock:
            self._observation = max(time.monotonic_ns(), self._observation + 1)
            return dict(requested=self._requested, active=self._active, pending=self._pending,
                        error=self._error, generation=0, conversion_verified=False,
                        source=_source_id(self._source) if self._source else None,
                        stopping=bool(self._thread and self._thread.is_alive() and not self._requested),
                        observation_id=str(self._observation))

    def start(self, *, source):
        with self._lock:
            if self._thread is not None or self._token.is_set():
                raise RuntimeError('source_bridge_stopping')
            self._source = source
            self._requested = self._pending = True
            self._thread = Thread(target=self._run, name='vrct-windows-bridge', daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._requested = self._active = False
            self._token.cancel()
            capture = self._capture
        if capture is not None:
            capture.request_stop()

    def close(self, timeout=3):
        self.stop()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def _fail(self, code):
        with self._lock:
            if not self._token.is_set():
                self._error = code
                self._requested = self._active = False
        self.stop()

    def _audio(self, captured):
        try:
            self._queue.put_nowait(captured.audio.pcm)
        except Full:
            if time.monotonic() - self._written > OUTPUT_STALL_S:
                self._fail('source_bridge_output_failed')
                return False
            # Python runs this bridge, so a busy PC can hold it up. Lose a little
            # audio and carry on: a stall of this size must not end the voice.
            _replace_oldest(self._queue, captured.audio.pcm)
        return True

    def _run(self):
        from models.transcription.capture_windows import WindowsCapture
        output = capture = None
        try:
            _check_devices(self._source, self.device)
            output = WindowsOutput(self.device, RATE, 1, strict_underflow=False)
            capture = WindowsCapture(self._source, 'mic', self._audio,
                                     lambda code: self._fail('source_bridge_capture_failed'))
            with self._lock:
                self._capture = capture
            self._token.check()
            capture.start()
            with self._lock:
                self._token.check()
                self._active, self._pending = True, False
            self._written = time.monotonic()
            while True:
                self._token.check()
                try:
                    pcm = self._queue.get(timeout=.05)
                except Empty:
                    continue
                with self._lock:
                    muted = self._muted
                output.write(bytes(len(pcm)) if muted else pcm, self._token)
                self._written = time.monotonic()
        except RuntimeError as exc:
            code = str(exc)
            self._fail(code if code.startswith(('vc_', 'source_bridge_')) else 'source_bridge_output_failed')
        except Exception:
            self._fail('source_bridge_output_failed')
        finally:
            self.stop()
            try:
                if capture is not None:
                    capture.stop()
            except Exception:
                pass
            try:
                if output is not None:
                    output.close(drain=False, token=self._token)
            except Exception:
                pass
            with self._lock:
                self._pending = False
