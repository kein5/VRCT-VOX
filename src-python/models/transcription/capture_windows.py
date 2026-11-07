"""WASAPI capture with the PipeWireCapture contract: 20 ms frames of 48 kHz mono.

PortAudio's callback only queues. Conversion and delivery run on this object's
own thread, so a slow consumer never stalls the driver. A speaker is read through
its loopback twin, which delivers nothing while the device plays nothing; that
gap is filled with silence so a session can still hear an utterance end.
"""
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
import time

import numpy as np

from models.audio_routing.devices_windows import (
    capture_device, default_endpoint as _default_endpoint, enumerate_endpoints as _enumerate_endpoints,
    prepare_audio_thread,
)
from models.voice_events import AudioFrame
from pyaudio_lock import pyaudio_op_lock
from .capture_pipewire import CaptureError, _validate, capture_error_code
from .realtime_audio import CapturedAudio

RATE = 48000
FRAME_BYTES = 1920
_STALL_NS = 2_000_000_000
_SILENCE_AFTER_NS = 60_000_000
# time.monotonic_ns() advances in ~16 ms ticks here. A stamp must never read
# later than the clock, or the first check that compares them rejects the frame.
_CLOCK_TICK_NS = 20_000_000


def enumerate_endpoints(source):
    if source not in ('mic', 'speaker'):
        raise ValueError('asr_capture_source_invalid')
    return _enumerate_endpoints(source)


def default_endpoint(source):
    if source not in ('mic', 'speaker'):
        raise ValueError('asr_capture_source_invalid')
    return _default_endpoint(source)


class FrameBuilder:
    """Device PCM in, stamped 48 kHz mono frames out."""
    def __init__(self, rate, channels):
        self.rate, self.channels = rate, channels
        self._pcm = bytearray()
        self._last = 0
        self._resampler = None
        if rate != RATE:
            import soxr
            self._resampler = soxr.ResampleStream(rate, RATE, 1, dtype='float32')

    def feed(self, data, received_ns):
        samples = np.frombuffer(data, dtype='<i2').reshape(-1, self.channels).astype(np.float32)
        mono = samples.mean(axis=1) / 32768
        if self._resampler is not None:
            mono = self._resampler.resample_chunk(mono)
        self._pcm.extend(np.rint(mono * 32768).clip(-32768, 32767).astype('<i2').tobytes())
        frames = []
        while len(self._pcm) >= FRAME_BYTES:
            block = bytes(self._pcm[:FRAME_BYTES])
            del self._pcm[:FRAME_BYTES]
            # Everything after this frame's first sample arrived by received_ns.
            age_ns = (len(self._pcm) + FRAME_BYTES) // 2 * 1_000_000_000 // RATE
            self._last = max(self._last + 1, received_ns - age_ns - _CLOCK_TICK_NS)
            frames.append(CapturedAudio(AudioFrame(block, RATE), self._last))
        return frames


class WindowsCapture:
    def __init__(self, endpoint, source, on_audio, on_error):
        _validate(endpoint, source)
        self.endpoint, self.source = endpoint, source
        self._on_audio, self._on_error = on_audio, on_error
        self._stop = Event()
        self._ready = Event()
        self._lock = Lock()
        self._thread = None
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
            error = self._error
            try:
                self.stop()
            except CaptureError:
                pass  # The start already failed; report why, not the slow teardown.
            raise CaptureError(error or 'asr_capture_stopped')

    def request_stop(self):
        """Invalidate pending startup/delivery without joining or touching a driver."""
        self._stop.set()
        self._ready.set()

    def stop(self):
        self.request_stop()
        with self._lock:
            thread = self._thread
        if thread and thread is not current_thread():
            thread.join(1)
            if thread.is_alive():
                raise CaptureError('asr_capture_consumer_busy')

    def _deliver(self, builder, data, received_ns):
        for frame in builder.feed(data, received_ns):
            if self._stop.is_set():
                return
            if self._on_audio(frame) is False:
                raise CaptureError('asr_capture_consumer_closed')
            self._ready.set()

    def _pump(self, stream, buffers, builder):
        last_ns = time.monotonic_ns()
        while not self._stop.is_set():
            try:
                data, received_ns = buffers.get(timeout=.02)
            except Empty:
                now = time.monotonic_ns()
                if not stream.is_active():
                    raise CaptureError('asr_capture_stream_disconnected') from None
                if self.source == 'speaker':
                    if now - last_ns >= _SILENCE_AFTER_NS:
                        gap = (now - last_ns) * builder.rate // 1_000_000_000
                        self._deliver(builder, bytes(gap * builder.channels * 2), now)
                        last_ns = now
                elif now - last_ns >= _STALL_NS:
                    raise CaptureError('asr_capture_stalled') from None
                continue
            if data is None:
                raise CaptureError('asr_capture_pipe_blocked')
            last_ns = received_ns
            self._deliver(builder, data, received_ns)

    def _run(self):
        pa = stream = None
        try:
            import pyaudiowpatch as audio
            prepare_audio_thread()
            buffers = Queue(maxsize=64)

            def queued(data, _count, _time, _status):
                try:
                    buffers.put_nowait((data, time.monotonic_ns()))
                except Full:
                    # Delivery fell a third of a second behind. Say so instead of
                    # skipping audio, which would silently lose speech.
                    try:
                        buffers.get_nowait()
                        buffers.put_nowait((None, 0))
                    except (Empty, Full):
                        pass
                return None, audio.paContinue

            with pyaudio_op_lock:
                pa = audio.PyAudio()
                try:
                    info = capture_device(pa, audio, self.endpoint, self.source)
                except (LookupError, OSError):
                    raise CaptureError('asr_capture_endpoint_missing') from None
                rate, channels = int(info['defaultSampleRate']), int(info['maxInputChannels'])
                try:
                    stream = pa.open(format=audio.paInt16, channels=channels, rate=rate, input=True,
                                     input_device_index=int(info['index']), frames_per_buffer=max(1, rate // 100),
                                     stream_callback=queued)
                except OSError:
                    raise CaptureError('asr_capture_stream_create_failed') from None
            self._pump(stream, buffers, FrameBuilder(rate, channels))
        except Exception as exc:
            if not self._stop.is_set():
                self._error = capture_error_code(str(exc)) if isinstance(exc, CaptureError) else 'asr_capture_failed'
                self.request_stop()
                try:
                    self._on_error(self._error)
                except Exception:
                    pass
        finally:
            self.request_stop()
            with pyaudio_op_lock:
                try:
                    if stream is not None:
                        stream.stop_stream()
                        stream.close()
                except OSError:
                    pass  # An unplugged device has nothing left to stop.
                if pa is not None:
                    pa.terminate()
