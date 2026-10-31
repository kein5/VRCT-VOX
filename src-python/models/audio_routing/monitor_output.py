"""Optional local monitor of the speech written to the virtual microphone.

The main write path only appends PCM to a bounded queue here. Device lookup,
opening, volume and writes run on a monitor-owned thread with its own token:
a missing, unplugged or stalled monitor never delays, cancels or fails the
main output, and never commits the main token's start deadline.
"""
from array import array
from collections import deque
import sys
from threading import Condition, Thread

from models.tts.speechcpp_tts import CancelToken, SpeechError

# Endpoints that feed the virtual microphone. A monitor there would be heard
# by VRChat twice and, through the managed mix, by microphone ASR.
VIRTUAL_PREFIXES = ('vrct.managed.', 'vrct.source-bridge.')
MONITOR_NODE = 'vrct.tts.monitor'


def check_monitor_target(target, exclude=()):
    if not target:
        raise SpeechError('output_missing')
    if target.startswith(VIRTUAL_PREFIXES) or target in exclude:
        raise SpeechError('feedback_blocked')
    return target


def monitor_spec(choice):
    """VoiceSettings.monitor_choice as the bounded dict that crosses process boundaries."""
    return None if choice is None else parse_monitor({'device': choice[0], 'volume': choice[1]})


def parse_monitor(value):
    """None (disabled) or {'device', 'volume'}; '' device is the OS default."""
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'device', 'volume'}
            or not isinstance(value['device'], str) or len(value['device']) > 512
            or any(ord(c) < 32 for c in value['device']) or value['device'].startswith(VIRTUAL_PREFIXES)
            or type(value['volume']) is not int or not 0 <= value['volume'] <= 100):
        raise ValueError('vc_monitor_invalid')
    return dict(value)


def open_monitor_output(device, rate, channels, *, exclude=()):
    """Empty device means the OS default output, resolved off the main path."""
    if sys.platform == 'win32':
        from .devices_windows import WindowsOutput, default_output
        return WindowsOutput(check_monitor_target(device or default_output(), exclude), rate, channels,
                             strict_underflow=False)
    if sys.platform.startswith('linux'):
        from .devices_pipewire import PipeWireOutput, default_output
        return PipeWireOutput(check_monitor_target(device or default_output(), exclude), rate, channels,
                              node_name=MONITOR_NODE)
    raise SpeechError('unsupported_platform')


def scale_pcm(pcm, volume):
    """Signed 16-bit little-endian PCM; attenuation only, so no clipping."""
    if volume >= 100:
        return pcm
    samples = array('h')
    samples.frombytes(pcm[:len(pcm) // 2 * 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    scaled = array('h', [int(s * volume / 100) for s in samples])
    if sys.byteorder == 'big':
        scaled.byteswap()
    return scaled.tobytes()


def error_code(exc):
    # Device names and driver messages stay out of status and logs.
    return 'monitor_' + str(exc) if isinstance(exc, SpeechError) else 'monitor_output_error'


class MonitorTee:
    def __init__(self, device, volume=100, *, exclude=(), output_factory=open_monitor_output,
                 on_error=None, on_ready=None, max_buffer_ms=500):
        self.device, self.volume = device, volume
        self._exclude = tuple(value for value in exclude if value)
        self._factory = output_factory
        self._on_error, self._on_ready = on_error, on_ready
        self._max_buffer_ms = max_buffer_ms
        self._condition = Condition()
        self._queue = deque()
        self._queued = 0
        self._closed = self._failed = False
        self._token = CancelToken()
        self.dropped = 0
        self.error = None
        self._thread = Thread(target=self._run, name='vrct-vox-monitor', daemon=True)
        self._thread.start()

    def offer(self, pcm, rate, channels):
        """Called after each main write: O(1), never blocks on or raises from the device."""
        with self._condition:
            if self._closed or self._failed:
                return
            self._queue.append((pcm, rate, channels))
            self._queued += len(pcm)
            # A late or slow monitor drops its oldest audio instead of growing.
            limit = max(1, rate * channels * 2 * self._max_buffer_ms // 1000)
            while self._queued > limit and len(self._queue) > 1:
                self._queued -= len(self._queue.popleft()[0])
                self.dropped += 1
            self._condition.notify()

    def close(self, *, drain):
        """Nonblocking. drain plays what is queued; otherwise stop at once."""
        with self._condition:
            self._closed = True
            if not drain:
                self._queue.clear()
                self._queued = 0
            self._condition.notify_all()
        if not drain:
            self._token.cancel()

    def join(self, timeout=None):
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _fail(self, exc):
        with self._condition:
            if self._failed or self._token.is_set():
                return
            self._failed = True
            self.error = error_code(exc)
            self._queue.clear()
            self._queued = 0
        if self._on_error is not None:
            try:
                self._on_error(self.error)
            except Exception:
                pass

    def _run(self):
        sink = stream_format = None
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._queue or self._closed)
                    if not self._queue or self._token.is_set():
                        break
                    pcm, rate, channels = self._queue.popleft()
                    self._queued -= len(pcm)
                if sink is None:
                    sink = self._factory(self.device, rate, channels, exclude=self._exclude)
                    stream_format = (rate, channels)
                    if self._on_ready is not None:
                        self._on_ready()
                if (rate, channels) != stream_format:
                    continue  # The main path rejects format changes first.
                sink.write(scale_pcm(pcm, self.volume), self._token)
        except Exception as exc:
            self._fail(exc)
        finally:
            if sink is not None:
                try:
                    sink.close(drain=not self._failed and not self._token.is_set(), token=self._token)
                except Exception as exc:
                    self._fail(exc)
