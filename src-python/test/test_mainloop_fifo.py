"""IPC の同一ロック FIFO、待機中の並行性、停止の優先経路を検証する。"""

import json
import threading
import unittest
from queue import Queue
from unittest.mock import MagicMock, patch

import mainloop as mainloop_module
from mainloop import Main


class _ObservedLock:
    """競合したことをイベントで通知する実ロック。ソケットは使わない。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.contended = threading.Event()
        self.attempts = 0

    def acquire(self, blocking=True):
        self.attempts += 1
        acquired = self.lock.acquire(blocking=blocking)
        if not acquired:
            self.contended.set()
        return acquired

    def release(self):
        self.lock.release()


class EndpointFifoTests(unittest.TestCase):
    def setUp(self):
        self.responses = Queue()
        self.releases = []
        self.mains = []
        for name in ("printLog", "errorLogging"):
            patcher = patch.object(mainloop_module, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(
            mainloop_module, "printResponse",
            side_effect=lambda status, endpoint, result: self.responses.put((status, endpoint, result)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._stop_workers)

    def _stop_workers(self):
        for main in self.mains:
            main._stop_event.set()
        for release in self.releases:
            release.set()
        for main in self.mains:
            for thread in main._threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

    def _main(self, mapping):
        main = Main(MagicMock(), mapping)
        self.mains.append(main)
        return main

    def _release_event(self):
        release = threading.Event()
        self.releases.append(release)
        return release

    def _assert_fifo(self, endpoints):
        entered = threading.Event()
        release = self._release_event()
        later_completed = threading.Event()
        completed = []

        def handle(data):
            if data == "A":
                entered.set()
                self.assertTrue(release.wait(2))
            completed.append(data)
            if data == "C":
                later_completed.set()
            return {"status": 200, "result": data}

        main = self._main({ep: {"status": True, "variable": handle} for ep in endpoints})
        lock = _ObservedLock()
        main._endpoint_locks[main._canonical_lock_key(endpoints[0])] = lock
        # 旧実装の B の sleep/requeue を C の完了まで止める。
        # 新実装ではこの sleep は呼ばれず、B はキューの先頭に残る。
        with patch.object(mainloop_module.time, "sleep", side_effect=lambda _: later_completed.wait(2)):
            main.startHandler()
            self.assertEqual(len(main._threads), 3)
            main.queue.put((endpoints[0], "A", 0))
            self.assertTrue(entered.wait(2))
            main.queue.put((endpoints[1], "B", 0))
            self.assertTrue(lock.contended.wait(2))
            release.set()
            responses = [self.responses.get(timeout=2)]
            # A が終了し、B が待っている間に C を受信する。
            main.queue.put((endpoints[2], "C", 0))
            responses.extend(self.responses.get(timeout=2) for _ in range(2))
        self.assertEqual(completed, ["A", "B", "C"])
        self.assertEqual(responses, [(200, ep, value) for ep, value in zip(endpoints, "ABC")])
        self.assertTrue(main.queue.empty())

    def test_three_chat_requests_complete_in_arrival_order(self):
        self._assert_fifo(["/run/send_message_box"] * 3)

    def test_enable_disable_share_fifo(self):
        self._assert_fifo(["/set/enable/translation", "/set/disable/translation", "/set/enable/translation"])

    def test_obs_and_websocket_settings_share_fifo(self):
        self._assert_fifo([
            "/set/enable/obs_browser_source", "/set/data/websocket_host",
            "/set/disable/websocket_server",
        ])

    def test_backlog_does_not_occupy_workers_for_other_endpoints(self):
        entered = [threading.Event(), threading.Event()]
        release = self._release_event()

        def handle(data):
            entered[data].set()
            self.assertTrue(release.wait(2))
            return {"status": 200, "result": data}

        main = self._main({
            "/a": {"status": True, "variable": handle},
            "/b": {"status": True, "variable": handle},
            "/c": {"status": True, "variable": lambda data: {"status": 200, "result": "free"}},
        })
        main.startHandler()
        main.queue.put(("/a", 0, 0))
        self.assertTrue(entered[0].wait(2))
        for _ in range(20):
            main.queue.put(("/a", 0, 0))
        main.queue.put(("/b", 1, 0))
        self.assertTrue(entered[1].wait(2))
        main.queue.put(("/c", None, 0))
        self.assertEqual(self.responses.get(timeout=2), (200, "/c", "free"))
        self.assertFalse(release.is_set())

    def test_contended_lock_waits_without_sleep_or_requeue_polling(self):
        entered = threading.Event()
        release = self._release_event()

        def handle(data):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"status": 200}

        main = self._main({"/a": {"status": True, "variable": handle}})
        lock = _ObservedLock()
        main._endpoint_locks["/a"] = lock
        main.startHandler()
        main.queue.put(("/a", "A", 0))
        self.assertTrue(entered.wait(2))
        with patch.object(mainloop_module.time, "sleep") as sleep:
            main.queue.put(("/a", "B", 0))
            self.assertTrue(lock.contended.wait(2))
            attempts = lock.attempts
            # 停止確認の 0.5 秒待ちが重なってもワーカー数を超えて起きない。
            threading.Event().wait(0.2)
            self.assertLessEqual(lock.attempts - attempts, 3)
            sleep.assert_not_called()
        release.set()
        self.responses.get(timeout=2)
        self.responses.get(timeout=2)

    def test_initialization_retry_keeps_fifo_and_other_endpoint_available(self):
        called = threading.Event()
        completed = []

        def handle(data):
            completed.append(data)
            return {"status": 200, "result": data}

        main = self._main({
            "/a": {"status": False, "variable": handle},
            "/b": {"status": True, "variable": lambda data: {"status": 200, "result": "free"}},
        })
        original = main._call_handler

        def call(endpoint, data):
            result = original(endpoint, data)
            if endpoint == "/a" and result[1] == 423:
                called.set()
            return result

        with patch.object(main, "_call_handler", side_effect=call):
            main.startHandler()
            main.queue.put(("/a", "A", 0))
            self.assertTrue(called.wait(2))
            main.queue.put(("/a", "B", 0))
            main.queue.put(("/a", "C", 0))
            main.queue.put(("/b", None, 0))
            self.assertEqual(self.responses.get(timeout=2), (200, "/b", "free"))
            self.assertEqual(completed, [])
            main.mapping["/a"]["status"] = True
            self.assertEqual([self.responses.get(timeout=2)[2] for _ in range(3)], list("ABC"))
            self.assertEqual(completed, list("ABC"))

    def test_initialization_timeout_returns_423_without_calling_handler(self):
        handler = MagicMock()
        main = self._main({"/a": {"status": False, "variable": handler}})
        with patch.object(mainloop_module, "_ENDPOINT_LOCKED_MAX_RETRIES", 2), \
                patch.object(mainloop_module, "_ENDPOINT_LOCKED_RETRY_INTERVAL_SEC", 0.01):
            main.startHandler()
            main.queue.put(("/a", None, 0))
            self.assertEqual(self.responses.get(timeout=2)[:2], (423, "/a"))
        handler.assert_not_called()

    def test_busy_deadline_returns_423_while_owner_is_running(self):
        entered = threading.Event()
        release = self._release_event()

        def handle(data):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"status": 200, "result": data}

        main = self._main({"/a": {"status": True, "variable": handle}})
        with patch.object(mainloop_module, "_LOCK_BUSY_MAX_RETRIES", 1), \
                patch.object(mainloop_module, "_LOCK_BUSY_RETRY_INTERVAL_SEC", 0.03):
            main.startHandler()
            main.queue.put(("/a", "A", 0))
            self.assertTrue(entered.wait(2))
            main.queue.put(("/a", "B", 0))
            self.assertEqual(self.responses.get(timeout=2), (423, "/a", "Locked endpoint (busy)"))
            self.assertFalse(release.is_set())
        release.set()
        self.assertEqual(self.responses.get(timeout=2), (200, "/a", "A"))

    def test_handler_failure_releases_next_request(self):
        def handle(data):
            if data == "A":
                raise RuntimeError("expected failure")
            return {"status": 200, "result": data}

        main = self._main({"/a": {"status": True, "variable": handle}})
        main.queue.put(("/a", "A", 0))
        main.queue.put(("/a", "B", 0))
        main.startHandler()
        self.assertEqual(self.responses.get(timeout=2), (500, "/a", "Internal error"))
        self.assertEqual(self.responses.get(timeout=2), (200, "/a", "B"))

    def test_all_fast_stop_commands_bypass_three_busy_workers(self):
        stops = [
            "/run/stop_voice", "/run/disable_tts", "/run/mute_voice", "/run/resume_voice",
            "/run/stop_direct_voice", "/run/stop_realtime_asr", "/run/stop_speech_server",
        ]
        entered = [threading.Event() for _ in range(3)]
        release = self._release_event()

        def handle(data):
            entered[data].set()
            self.assertTrue(release.wait(2))
            return {"status": 200}

        mapping = {f"/busy/{i}": {"status": True, "variable": handle} for i in range(3)}
        mapping.update({ep: {"status": True, "variable": lambda data: {"status": 200}} for ep in stops})
        main = self._main(mapping)
        main.startHandler()
        for index in range(3):
            main.queue.put((f"/busy/{index}", index, 0))
        self.assertTrue(all(event.wait(2) for event in entered))
        lines = iter(json.dumps({"endpoint": endpoint}) + "\n" for endpoint in stops)

        def readline():
            line = next(lines, "")
            if not line:
                main._stop_event.set()
            return line

        with patch.object(mainloop_module.sys.stdin, "readline", side_effect=readline), \
                patch.object(mainloop_module.time, "sleep"):
            main.receiver()
        self.assertEqual([self.responses.get(timeout=2)[:2] for _ in stops], [(200, ep) for ep in stops])
        self.assertFalse(release.is_set())
        self.assertTrue(main.queue.empty())
