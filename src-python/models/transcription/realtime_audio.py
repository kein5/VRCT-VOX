"""Continuous PCM ingress. Capture must timestamp the first sample of each chunk."""

import asyncio
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic_ns

import numpy as np

from models.voice_events import AudioFrame

RATE = 24000
MAX_AGE_NS = 250_000_000


@dataclass(frozen=True)
class CapturedAudio:
    audio: AudioFrame
    captured_ns: int


def _format(rate, channels):
    if (
        type(rate) is not int
        or not 8000 <= rate <= 192000
        or type(channels) is not int
        or channels not in (1, 2)
    ):
        raise ValueError("invalid_pcm_format")


def _samples(audio, rate, channels):
    if (
        not isinstance(audio, AudioFrame)
        or type(audio.pcm) is not bytes
        or type(audio.sample_rate) is not int
        or type(audio.channels) is not int
        or (audio.sample_rate, audio.channels) != (rate, channels)
    ):
        raise ValueError("capture_format_changed")
    count = len(audio.pcm) // (2 * channels)
    if not rate * 0.005 <= count <= rate * 0.1:
        raise ValueError("invalid_chunk_size")
    return count


class Pcm24kStream:
    """Single-worker resampler; close drops its tail, it never flushes after stop."""

    def __init__(self, rate, channels):
        _format(rate, channels)
        # Optional until this engine is selected; legacy startup needs no soxr.
        import soxr

        self.rate, self.channels = rate, channels
        self._stream = soxr.ResampleStream(rate, RATE, 1, dtype="float32", quality="HQ")
        self._markers = deque()
        self._input_count = self._output_count = 0
        self._last_stamp = -1

    def close(self):
        self._stream = None
        self._markers.clear()

    def process(self, audio, captured_ns):
        if self._stream is None:
            raise ValueError("resampler_closed")
        count = _samples(audio, self.rate, self.channels)
        if type(captured_ns) is not int or captured_ns <= self._last_stamp:
            raise ValueError("invalid_capture_timestamp")
        self._last_stamp = captured_ns
        self._markers.append((self._input_count, captured_ns))
        self._input_count += count
        samples = (
            np.frombuffer(audio.pcm, dtype="<i2")
            .reshape(-1, self.channels)
            .astype(np.float32)
        )
        # Float mixing avoids int16 overflow and native INT16-output dithering.
        mono = samples.mean(axis=1) / 32768
        output = self._stream.resample_chunk(mono)
        if self._stream.delay() > RATE * 0.2 or len(self._markers) > 64:
            self.close()
            raise ValueError("resampler_backlog")
        if not np.isfinite(output).all():
            self.close()
            raise ValueError("invalid_resampler_output")
        pcm = np.rint(output * 32768).clip(-32768, 32767).astype("<i2").tobytes()
        result = []
        for offset in range(0, len(pcm), 960):
            input_index = self._output_count * self.rate // RATE
            while len(self._markers) > 1 and self._markers[1][0] <= input_index:
                self._markers.popleft()
            start, stamp = self._markers[0]
            stamp += (input_index - start) * 1_000_000_000 // self.rate
            block = pcm[offset : offset + 960]
            result.append(CapturedAudio(AudioFrame(block, RATE), stamp))
            self._output_count += len(block) // 2
        return tuple(result)


class RealtimeIngress:
    """Thread-safe bounded push; one async pump owns conversion and client feed.

    This doesn't open a device. Producers must report real format and sample
    timestamps. Overflow fails the session instead of skipping a word silently.
    """

    def __init__(self, rate, channels, *, clock_ns=monotonic_ns):
        _format(rate, channels)
        self.rate, self.channels = rate, channels
        self._clock = clock_ns
        self._lock = Lock()
        self._queue = deque()
        self._samples_queued = 0
        self._last_stamp = -1
        self._reason = None
        self._pumping = False

    @property
    def error(self):
        with self._lock:
            return self._reason

    def _close_locked(self, reason):
        if self._reason is None:
            self._reason = reason
        self._queue.clear()
        self._samples_queued = 0

    def close(self):
        with self._lock:
            self._close_locked("stopped")

    def push(self, audio, captured_ns):
        with self._lock:
            if self._reason is not None:
                return False
            try:
                count = _samples(audio, self.rate, self.channels)
                if (
                    type(captured_ns) is not int
                    or captured_ns <= self._last_stamp
                    or not 0 <= self._clock() - captured_ns <= MAX_AGE_NS
                ):
                    raise ValueError("invalid_capture")
            except (ValueError, TypeError):
                self._close_locked("invalid_capture")
                return False
            if len(self._queue) >= 20 or self._samples_queued + count > self.rate * 0.2:
                self._close_locked("input_overflow")
                return False
            self._last_stamp = captured_ns
            self._samples_queued += count
            self._queue.append(CapturedAudio(audio, captured_ns))
            return True

    async def pump(self, client):
        with self._lock:
            if self._pumping:
                raise RuntimeError("single_consumer_required")
            self._pumping = True
        converter = None
        try:
            converter = Pcm24kStream(self.rate, self.channels)
            while True:
                with self._lock:
                    if self._reason is not None:
                        if self._reason != "stopped":
                            raise ValueError(self._reason)
                        return
                    item = self._queue.popleft() if self._queue else None
                    if item is not None:
                        self._samples_queued -= len(item.audio.pcm) // (
                            2 * self.channels
                        )
                if item is None:
                    await asyncio.sleep(0.005)
                    continue
                if not 0 <= self._clock() - item.captured_ns <= MAX_AGE_NS:
                    raise ValueError("stale_capture")
                for block in converter.process(item.audio, item.captured_ns):
                    if self.error is not None:
                        break
                    if not 0 <= self._clock() - block.captured_ns <= MAX_AGE_NS:
                        raise ValueError("stale_capture")
                    await client.feed(block.audio, block.captured_ns)
        except asyncio.CancelledError:
            raise
        except Exception:
            with self._lock:
                self._close_locked("input_failed")
            raise
        finally:
            self.close()
            if converter is not None:
                converter.close()
            await client.stop()
