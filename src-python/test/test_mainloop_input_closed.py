"""UI からの入力が閉じたときの終了と、ウォッチドッグへの生存の知らせの経路。

以前は stdin が閉じても 0.1 秒ごとに読み直し続け、ウォッチドッグの期限 (60〜90秒) まで
プロセスが残った。また /run/feed_watchdog がふつうの要求と同じ3本のワーカーに並んだため、
重い処理で埋まると知らせが届かず、健全なアプリがウォッチドッグに止められるおそれがあった。
"""

import json
import threading
import unittest
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mainloop as mainloop_module
from mainloop import Main


class InputClosedTests(unittest.TestCase):
    def setUp(self):
        for name in ("printLog", "errorLogging"):
            patcher = patch.object(mainloop_module, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.main = Main(MagicMock(), {})
        self.main.escalateShutdown = MagicMock()

    def receive(self, stdin):
        with patch.object(mainloop_module.sys, "stdin", stdin):
            thread = threading.Thread(target=self.main.receiver, daemon=True)
            thread.start()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive(), "receiver kept reading a closed input")

    def test_closed_input_shuts_down_once_instead_of_polling(self):
        self.receive(SimpleNamespace(readline=lambda: ""))
        self.main.escalateShutdown.assert_called_once_with()

    def test_missing_input_is_treated_as_closed(self):
        self.receive(None)
        self.main.escalateShutdown.assert_called_once_with()

    def test_input_ending_after_a_stop_request_does_not_shut_down_again(self):
        def readline():
            self.main._stop_event.set()
            return ""

        self.receive(SimpleNamespace(readline=readline))
        self.main.escalateShutdown.assert_not_called()


class WatchdogFeedTests(unittest.TestCase):
    def setUp(self):
        self.responses = Queue()
        for name in ("printLog", "errorLogging"):
            patcher = patch.object(mainloop_module, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(mainloop_module, "printResponse",
                               side_effect=lambda status, endpoint, result: self.responses.put((status, endpoint)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_feed_is_answered_while_every_worker_is_busy(self):
        release = threading.Event()
        entered = [threading.Event() for _ in range(3)]
        fed = MagicMock(return_value={"status": 200, "result": True})

        def busy(index):
            def handle(data):
                entered[index].set()
                release.wait(5)
                return {"status": 200}
            return handle

        mapping = {f"/busy/{i}": {"status": True, "variable": busy(i)} for i in range(3)}
        mapping["/run/feed_watchdog"] = {"status": True, "variable": fed}
        main = Main(MagicMock(), mapping)
        main.startHandler()
        main.startFeedHandler()
        for i in range(3):
            main.queue.put((f"/busy/{i}", None, 0))
        self.assertTrue(all(event.wait(2) for event in entered))

        lines = Queue()
        lines.put(json.dumps({"endpoint": "/run/feed_watchdog"}) + "\n")
        main.escalateShutdown = MagicMock()
        with patch.object(mainloop_module.sys, "stdin", SimpleNamespace(readline=lines.get)):
            receiver = threading.Thread(target=main.receiver, daemon=True)
            receiver.start()
            try:
                self.assertEqual(self.responses.get(timeout=2), (200, "/run/feed_watchdog"))
                fed.assert_called_once()
            finally:
                main._stop_event.set()
                release.set()
                lines.put("")
                receiver.join(timeout=2)
                for thread in main._threads:
                    thread.join(timeout=2)
        main.escalateShutdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
