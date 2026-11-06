"""Realtime ingress waits using fake PCM conversion and a socket-free loop."""

import asyncio
from queue import Queue
from statistics import median
from threading import Lock, Thread
from time import monotonic_ns, perf_counter
import unittest
from unittest.mock import Mock, patch

from models.transcription import realtime_audio as audio
from models.voice_events import AudioFrame
from asr_wait_fakes import run_async


FRAME = AudioFrame(b"\0\0" * 480, 24000)


class FakeConverter:
    def __init__(self, *args):
        pass

    def process(self, frame, stamp):
        return (audio.CapturedAudio(frame, stamp),)

    def close(self):
        pass


class CountingLock:
    def __init__(self):
        self.lock = Lock()
        self.entries = 0

    def __enter__(self):
        self.lock.acquire()
        self.entries += 1

    def __exit__(self, *args):
        self.lock.release()


class Client:
    def __init__(self):
        self.received = asyncio.Queue()
        self.stopped = False

    async def feed(self, frame, stamp):
        self.received.put_nowait((frame, stamp))

    async def stop(self):
        self.stopped = True


async def start_pump(ingress, client):
    task = asyncio.create_task(ingress.pump(client))
    # Let both pump and its consumer start and enter their waits.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return task


class TestRealtimeIngressWait(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(audio, "Pcm24kStream", FakeConverter))

    def test_idle_has_no_rechecks_for_one_second_and_close_wakes(self):
        async def run():
            ingress, client = audio.RealtimeIngress(24000, 1), Client()
            ingress._lock = CountingLock()
            task = await start_pump(ingress, client)
            entries = ingress._lock.entries
            await asyncio.sleep(1)
            self.assertEqual(ingress._lock.entries, entries)
            started = perf_counter()
            thread = Thread(target=ingress.close)
            thread.start()
            await asyncio.wait_for(task, 0.5)
            thread.join(1)
            self.assertLess(perf_counter() - started, 0.5)
            self.assertTrue(client.stopped)
            self.assertIsNone(ingress._loop)
            self.assertFalse(ingress.push(FRAME, monotonic_ns()))

        run_async(run())

    def test_thread_push_wakes_promptly_repeatedly_without_lost_input(self):
        async def run():
            ingress, client = audio.RealtimeIngress(24000, 1), Client()
            task = await start_pump(ingress, client)
            acknowledgements = Queue()
            latencies, failures = [], []
            started = [0.0]

            async def feed(frame, stamp):
                latencies.append(perf_counter() - started[0])
                acknowledgements.put(True)

            client.feed = feed

            def producer():
                try:
                    for _ in range(50):
                        started[0] = perf_counter()
                        self.assertTrue(ingress.push(FRAME, monotonic_ns()))
                        acknowledgements.get(timeout=1)
                except Exception as error:
                    failures.append(error)
                finally:
                    ingress.close()

            thread = Thread(target=producer)
            thread.start()
            await asyncio.wait_for(task, 3)
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(len(latencies), 50)
            self.assertLess(median(latencies), 0.25)
            print(f"RealtimeIngress: push-to-feed median_ms={median(latencies) * 1000:.3f}, n=50")

        run_async(run())

    def test_push_before_pump_and_between_clear_and_wait_is_not_lost(self):
        async def run():
            for preloaded in (True, False):
                ingress, client = audio.RealtimeIngress(24000, 1), Client()
                stamp = monotonic_ns()
                if preloaded:
                    self.assertTrue(ingress.push(FRAME, stamp))
                    task = await start_pump(ingress, client)
                else:
                    # Install the hook after pump creates its Event but before
                    # the consumer starts. Push from another thread on entry
                    # to wait(): clear and the locked empty check already ran.
                    task = asyncio.create_task(ingress.pump(client))
                    await asyncio.sleep(0)
                    event = ingress._available
                    original_wait = event.wait
                    pushed = False

                    async def wait():
                        nonlocal pushed
                        if not pushed:
                            pushed = True
                            thread = Thread(target=lambda: ingress.push(FRAME, stamp))
                            thread.start()
                            thread.join(1)
                            self.assertFalse(thread.is_alive())
                        await original_wait()

                    event.wait = wait
                self.assertEqual(await asyncio.wait_for(client.received.get(), 0.5), (FRAME, stamp))
                ingress.close()
                await asyncio.wait_for(task, 0.5)

        run_async(run())

    def test_close_interrupts_busy_feed_and_drops_tail(self):
        async def run():
            ingress, client = audio.RealtimeIngress(24000, 1), Client()
            feeding = asyncio.Event()

            async def feed(*args):
                feeding.set()
                await asyncio.Event().wait()

            client.feed = feed
            task = await start_pump(ingress, client)
            self.assertTrue(ingress.push(FRAME, monotonic_ns()))
            await asyncio.wait_for(feeding.wait(), 0.5)
            self.assertTrue(ingress.push(FRAME, monotonic_ns()))
            thread = Thread(target=ingress.close)
            thread.start()
            await asyncio.wait_for(task, 0.5)
            thread.join(1)
            self.assertTrue(client.stopped)
            self.assertFalse(ingress._queue)
            self.assertEqual(ingress._samples_queued, 0)

        run_async(run())

    def test_closing_loop_does_not_raise_on_producer_thread(self):
        for action in ("push", "close", "invalid"):
            with self.subTest(action=action):
                ingress = audio.RealtimeIngress(24000, 1)
                ingress._loop = Mock()
                ingress._loop.call_soon_threadsafe.side_effect = RuntimeError("Event loop is closed")
                ingress._available = Mock()
                ingress._closing = Mock()
                failures = []

                def producer():
                    try:
                        if action == "close":
                            ingress.close()
                        else:
                            ingress.push(FRAME, 0 if action == "invalid" else monotonic_ns())
                        ingress.close()
                    except Exception as error:
                        failures.append(error)

                thread = Thread(target=producer)
                thread.start()
                thread.join(0.5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
                self.assertIsNotNone(ingress.error)

    def test_cancel_and_single_consumer_rule_while_waiting(self):
        async def run():
            ingress, client = audio.RealtimeIngress(24000, 1), Client()
            task = await start_pump(ingress, client)
            with self.assertRaisesRegex(RuntimeError, "single_consumer_required"):
                await ingress.pump(client)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            self.assertTrue(client.stopped)
            self.assertIsNone(ingress._loop)
            self.assertFalse(ingress.push(FRAME, monotonic_ns()))

        run_async(run())

    def test_overflow_and_invalid_input_wake_waiting_pump(self):
        async def run():
            for reason in ("input_overflow", "invalid_capture"):
                ingress, client = audio.RealtimeIngress(24000, 1), Client()
                task = await start_pump(ingress, client)

                def producer():
                    if reason == "invalid_capture":
                        ingress.push(FRAME, 0)
                    else:
                        now = monotonic_ns()
                        for i in range(11):
                            ingress.push(FRAME, now - 20 + i)

                thread = Thread(target=producer)
                thread.start()
                # Keep the loop here until the producer fills the bounded queue.
                thread.join(1)
                with self.assertRaisesRegex(ValueError, reason):
                    await asyncio.wait_for(task, 0.5)
                self.assertEqual(ingress.error, reason)
                self.assertTrue(client.stopped)
                self.assertEqual(ingress._samples_queued, 0)

        run_async(run())

    def test_freshness_and_item_count_limits_unchanged(self):
        now = 1_000_000_000
        for stamp in (now + 1, now - audio.MAX_AGE_NS - 1):
            ingress = audio.RealtimeIngress(24000, 1, clock_ns=lambda: now)
            self.assertFalse(ingress.push(FRAME, stamp))
            self.assertEqual(ingress.error, "invalid_capture")
        ingress = audio.RealtimeIngress(24000, 1, clock_ns=lambda: now)
        tiny = AudioFrame(b"\0\0" * 120, 24000)
        for i in range(20):
            self.assertTrue(ingress.push(tiny, now - 20 + i))
        self.assertFalse(ingress.push(tiny, now))
        self.assertEqual(ingress.error, "input_overflow")

        async def run():
            clock = [now]
            ingress = audio.RealtimeIngress(24000, 1, clock_ns=lambda: clock[0])
            client = Client()
            self.assertTrue(ingress.push(FRAME, now))
            clock[0] += audio.MAX_AGE_NS + 1
            with self.assertRaisesRegex(ValueError, "stale_capture"):
                await ingress.pump(client)
            self.assertTrue(client.received.empty())
            self.assertTrue(client.stopped)

        run_async(run())
