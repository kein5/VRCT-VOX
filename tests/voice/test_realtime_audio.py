import asyncio
import importlib
import time

import numpy as np
import pytest
import soxr

from models.voice_events import AudioFrame


def module():
    return importlib.import_module("models.transcription.realtime_audio")


def pcm(rate, frequency=1000, seconds=2, channels=1):
    signal = np.rint(
        np.sin(np.arange(int(rate * seconds)) * 2 * np.pi * frequency / rate) * 16000
    ).astype("<i2")
    if channels == 2:
        signal = np.column_stack([signal, signal]).reshape(-1)
    return AudioFrame(signal.tobytes(), rate, channels)


def convert(frame, block_ms=20):
    converter = module().Pcm24kStream(frame.sample_rate, frame.channels)
    width = frame.sample_rate * block_ms // 1000 * frame.channels * 2
    result = []
    for offset in range(0, len(frame.pcm), width):
        chunk = AudioFrame(
            frame.pcm[offset : offset + width], frame.sample_rate, frame.channels
        )
        result.extend(
            converter.process(
                chunk,
                1_000_000_000
                + offset * 1_000_000_000 // (frame.sample_rate * frame.channels * 2),
            )
        )
    converter.close()
    return result


@pytest.mark.parametrize("rate", [44100, 48000])
def test_resampling_preserves_passband_rejects_alias_and_timestamps(rate):
    normal = convert(pcm(rate))
    alias = convert(pcm(rate, 18000))

    def samples(chunks):
        return np.frombuffer(b"".join(c.audio.pcm for c in chunks), dtype="<i2").astype(
            float
        )[2000:-2000]

    def rms(a):
        return np.sqrt(np.mean(a * a))

    assert 11000 < rms(samples(normal)) < 11600
    assert rms(samples(alias)) < rms(samples(normal)) * 0.005
    assert all(
        c.audio.sample_rate == 24000
        and c.audio.channels == 1
        and 0 < len(c.audio.pcm) <= 960
        for c in normal
    )
    count = 0
    for c in normal:
        assert (
            abs(c.captured_ns - (1_000_000_000 + count * 1_000_000_000 // 24000))
            < 50000
        )
        count += len(c.audio.pcm) // 2
    assert 1.8 * 24000 < count <= 2 * 24000


@pytest.mark.parametrize("rate", [44100, 48000])
def test_streaming_chunk_sizes_match_filtered_reference(rate):
    frame = pcm(rate)
    source = np.frombuffer(frame.pcm, dtype="<i2").astype(np.float32) / 32768
    reference = np.rint(soxr.resample(source, rate, 24000, quality="HQ") * 32768).clip(
        -32768, 32767
    )
    for block_ms in (10, 20, 50):
        actual = np.frombuffer(
            b"".join(c.audio.pcm for c in convert(frame, block_ms)), dtype="<i2"
        )
        assert np.max(np.abs(actual.astype(float) - reference[: len(actual)])) <= 1


def test_downmix_has_headroom_and_stop_discards_native_tail():
    converter = module().Pcm24kStream(48000, 2)
    stereo = np.tile(np.array([32767, -32767], dtype="<i2"), 4800)
    result = converter.process(AudioFrame(stereo.tobytes(), 48000, 2), 1)
    assert result and all(not any(c.audio.pcm) for c in result)
    converter.close()
    with pytest.raises(ValueError, match="closed"):
        converter.process(AudioFrame(b"\0\0" * 960, 48000), 2)
    # A new session has no native filter state from the old stream.
    fresh = convert(AudioFrame(b"\0\0" * 48000, 48000))
    assert all(not any(c.audio.pcm) for c in fresh)


@pytest.mark.parametrize(
    "frame",
    [
        AudioFrame(b"\0\0" * 960, 48000),
        AudioFrame(b"\0\0" * 24, 24000),
        AudioFrame(b"\0\0" * 4800, 24000),
    ],
)
def test_format_change_tiny_and_oversized_chunks_rejected(frame):
    converter = module().Pcm24kStream(24000, 1)
    with pytest.raises(ValueError):
        converter.process(frame, 1)


def test_native_pending_is_bounded(monkeypatch):
    class Stalled:
        count = 0

        def resample_chunk(self, x):
            self.count += len(x)
            return np.array([], dtype=np.float32)

        def delay(self):
            return self.count / 2

        def clear(self):
            pass

    monkeypatch.setattr(soxr, "ResampleStream", lambda *a, **k: Stalled())
    converter = module().Pcm24kStream(48000, 1)
    frame = AudioFrame(b"\0\0" * 4800, 48000)
    converter.process(frame, 1)
    converter.process(frame, 100_000_001)
    with pytest.raises(ValueError, match="resampler_backlog"):
        converter.process(frame, 200_000_001)


@pytest.mark.parametrize("age_ns", [-1, 251_000_000])
def test_ingress_rejects_future_and_stale_input(age_ns):
    now = 10_000_000_000
    q = module().RealtimeIngress(48000, 1, clock_ns=lambda: now)
    assert not q.push(AudioFrame(b"\0\0" * 960, 48000), now - age_ns)
    assert q.error == "invalid_capture"


def test_queue_limits_discard_and_reject_new_audio():
    now = 10_000_000_000
    q = module().RealtimeIngress(48000, 1, clock_ns=lambda: now)
    for i in range(10):
        assert q.push(
            AudioFrame(b"\0\0" * 960, 48000), now - 200_000_000 + i * 20_000_000
        )
    assert not q.push(AudioFrame(b"\0\0" * 960, 48000), now)
    assert q.error == "input_overflow"
    assert not q.push(AudioFrame(b"\0\0" * 960, 48000), now)


def test_stop_during_send_discards_rest_and_closes_client():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        class Client:
            sent = []
            stopped = False

            async def feed(self, a, t):
                self.sent.append((a, t))
                started.set()
                await release.wait()

            async def stop(self):
                self.stopped = True

        q = module().RealtimeIngress(48000, 1)
        client = Client()
        stamp = time.monotonic_ns() - 100_000_000
        assert q.push(pcm(48000, seconds=0.1), stamp)
        task = asyncio.create_task(q.pump(client))
        await asyncio.wait_for(started.wait(), 1)
        q.close()
        release.set()
        await asyncio.wait_for(task, 1)
        assert client.stopped and len(client.sent) == 1
        assert client.sent[0][1] == stamp
        assert not q.push(pcm(48000, seconds=0.02), time.monotonic_ns())

    asyncio.run(run())


def test_cancel_and_multiple_consumer_are_bounded():
    async def run():
        class Client:
            stopped = False

            async def stop(self):
                self.stopped = True

        client = Client()
        q = module().RealtimeIngress(48000, 1)
        task = asyncio.create_task(q.pump(client))
        await asyncio.sleep(0.01)
        with pytest.raises(RuntimeError, match="consumer"):
            await q.pump(client)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.stopped
        assert not q.push(pcm(48000, seconds=0.02), time.monotonic_ns())

    asyncio.run(run())


def test_item_count_limit_and_nonmonotonic_capture():
    now = 10_000_000_000
    frame = AudioFrame(b"\0\0" * 240, 48000)
    q = module().RealtimeIngress(48000, 1, clock_ns=lambda: now)
    for i in range(20):
        assert q.push(frame, now - 100_000_000 + i * 5_000_000)
    assert not q.push(frame, now)
    assert q.error == "input_overflow"
    q = module().RealtimeIngress(48000, 1, clock_ns=lambda: now)
    assert q.push(frame, now)
    assert not q.push(frame, now)
    assert q.error == "invalid_capture"


def test_audio_that_ages_while_queued_never_reaches_client():
    async def run():
        now = [10_000_000_000]

        class Client:
            stopped = False

            async def feed(self, *args):
                pytest.fail("stale audio was sent")

            async def stop(self):
                self.stopped = True

        client = Client()
        q = module().RealtimeIngress(48000, 1, clock_ns=lambda: now[0])
        assert q.push(pcm(48000, seconds=0.1), now[0])
        now[0] += 251_000_000
        with pytest.raises(ValueError, match="stale_capture"):
            await q.pump(client)
        assert client.stopped and q.error == "input_failed"

    asyncio.run(run())


def test_send_failure_closes_ingress_and_client():
    async def run():
        class Client:
            stopped = False

            async def feed(self, *args):
                raise RuntimeError("test_send_failure")

            async def stop(self):
                self.stopped = True

        q = module().RealtimeIngress(48000, 1)
        client = Client()
        assert q.push(pcm(48000, seconds=0.1), time.monotonic_ns() - 100_000_000)
        with pytest.raises(RuntimeError, match="test_send_failure"):
            await q.pump(client)
        assert client.stopped and q.error == "input_failed"

    asyncio.run(run())
