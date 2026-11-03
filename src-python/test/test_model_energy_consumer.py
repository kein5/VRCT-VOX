"""音量メーターの通知待ちと停止。実デバイスは開かず recorder を差し替える。"""

import threading
import time
import unittest
from queue import Queue
from unittest.mock import Mock, patch

import model as model_module
from model import MicSession, SpeakerSession, _EnergyQueue
from utils import putDroppingOldestOnFull


class TestEnergyConsumer(unittest.TestCase):
    def _start_session(self, callback, session_cls=MicSession, before_start=None):
        session = session_cls()
        recorder = Mock()
        session.features = {"energy"}
        session.energy_fnc = callback
        if before_start is not None:
            recorder.recordIntoQueue.side_effect = before_start
        with patch.object(session, "_create_recorder", return_value=recorder):
            session._start(device={"name": "fake", "index": 0})
        self.addCleanup(session._stop)
        return session, recorder.recordIntoQueue.call_args.args[1]

    def test_only_latest_unread_value_is_delivered(self) -> None:
        for session_cls in (MicSession, SpeakerSession):
            with self.subTest(session=session_cls.__name__):
                received = Queue()

                def preload(audio_queue, energy_queue):
                    for value in range(100):
                        putDroppingOldestOnFull(energy_queue, float(value))

                session, queue = self._start_session(received.put, session_cls, preload)
                self.assertEqual(queue.maxsize, 1)
                self.assertEqual(received.get(timeout=1.0), 99.0)
                self.assertTrue(received.empty())
                self.assertFalse(session._stop())

    def test_slow_callback_keeps_only_latest_pending_sample(self) -> None:
        entered, release = threading.Event(), threading.Event()
        received = Queue()

        def callback(value):
            if value == 1.0:
                entered.set()
                release.wait(timeout=2.0)
            received.put(value)

        session, queue = self._start_session(callback)
        try:
            putDroppingOldestOnFull(queue, 1.0)
            self.assertTrue(entered.wait(1.0))
            for value in range(2, 102):
                putDroppingOldestOnFull(queue, float(value))
            self.assertEqual(queue.qsize(), 1)
            release.set()
            self.assertEqual(received.get(timeout=1.0), 1.0)
            self.assertEqual(received.get(timeout=1.0), 101.0)
            self.assertTrue(received.empty())
        finally:
            release.set()
            session._stop()

    def test_idle_consumer_blocks_until_sample_and_stops_promptly(self) -> None:
        waiting = threading.Event()
        get_calls = []
        received = Queue()
        original_get = _EnergyQueue.getUntilStopped

        def get(queue):
            get_calls.append(True)
            waiting.set()
            return original_get(queue)

        with patch.object(_EnergyQueue, "getUntilStopped", get):
            session, queue = self._start_session(received.put)
            worker = session._energy_progressbar
            try:
                self.assertTrue(waiting.wait(1.0))
                threading.Event().wait(1.0)
                self.assertEqual(len(get_calls), 1)
                waiting.clear()
                putDroppingOldestOnFull(queue, 0.0)
                self.assertEqual(received.get(timeout=1.0), 0.0)
                self.assertTrue(waiting.wait(1.0))
                stopped_at = time.perf_counter()
                self.assertFalse(session._stop())
                self.assertLess(time.perf_counter() - stopped_at, 0.5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(received.empty())
            finally:
                session._stop()

    def test_stop_with_full_queue_is_not_overwritten_by_producer(self) -> None:
        entered, release = threading.Event(), threading.Event()
        stopped = threading.Event()
        received = Queue()

        def callback(value):
            received.put(value)
            entered.set()
            release.wait(timeout=2.0)

        session, queue = self._start_session(callback)
        worker = session._energy_progressbar
        original_stop = queue.stop

        def stop_queue():
            original_stop()
            stopped.set()

        stopper = threading.Thread(target=session._stop)
        with patch.object(queue, "stop", stop_queue):
            try:
                putDroppingOldestOnFull(queue, 1.0)
                self.assertTrue(entered.wait(1.0))
                putDroppingOldestOnFull(queue, 2.0)
                stopper.start()
                self.assertTrue(stopped.wait(1.0))
                for value in range(3, 103):
                    putDroppingOldestOnFull(queue, float(value))
                released_at = time.perf_counter()
                release.set()
                stopper.join(timeout=0.5)
                self.assertFalse(stopper.is_alive())
                self.assertFalse(worker.is_alive())
                self.assertLess(time.perf_counter() - released_at, 0.5)
                self.assertEqual(received.get_nowait(), 1.0)
                self.assertTrue(received.empty())
                self.assertIsNone(queue.getUntilStopped())
            finally:
                release.set()
                if stopper.ident is not None:
                    stopper.join(timeout=1.0)

    def test_stop_before_first_read_does_not_wait(self) -> None:
        queue = _EnergyQueue()
        queue.stop()
        queue.stop()
        putDroppingOldestOnFull(queue, 42.0)
        self.assertIsNone(queue.getUntilStopped())

    def test_callback_error_does_not_lose_next_sample(self) -> None:
        failed = threading.Event()
        received = Queue()

        def callback(value):
            if value == 1.0:
                raise ValueError("callback failed")
            received.put(value)

        with patch.object(model_module, "errorLogging", side_effect=failed.set):
            session, queue = self._start_session(callback)
            try:
                putDroppingOldestOnFull(queue, 1.0)
                self.assertTrue(failed.wait(1.0))
                putDroppingOldestOnFull(queue, 2.0)
                self.assertEqual(received.get(timeout=1.0), 2.0)
            finally:
                session._stop()

    def test_restart_gets_fresh_queue_and_worker(self) -> None:
        received = Queue()
        session, old_queue = self._start_session(received.put)
        old_worker = session._energy_progressbar
        self.assertFalse(session._stop())
        session.features = {"energy"}
        with patch.object(session, "_create_recorder", return_value=Mock()):
            session._start(device={"name": "fake", "index": 0})
        self.assertIsNot(session._energy_queue, old_queue)
        self.assertFalse(old_worker.is_alive())
        putDroppingOldestOnFull(old_queue, 1.0)
        putDroppingOldestOnFull(session._energy_queue, 2.0)
        self.assertEqual(received.get(timeout=1.0), 2.0)
        self.assertFalse(session._stop())
        self.assertTrue(received.empty())


if __name__ == "__main__":
    unittest.main()
