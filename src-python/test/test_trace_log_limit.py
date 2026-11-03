"""faulthandler のトレース (crash_trace.log、freeze_trace.log) も上限を超えて増え続けない。

logging のハンドラーは 10 MB で切り詰めるが、faulthandler は開いたファイルへ直接
書くので、この 2 つは起動のたびに追記され続けていた。
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import utils


class OpenTraceLogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.dict(os.environ, {"VRCT_CONFIG_DIR": directory.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = os.path.join(directory.name, "logs", "freeze_trace.log")

    def _open(self, **limits):
        path, handle = utils.openTraceLog("freeze_trace.log", **limits)
        self.addCleanup(handle.close)
        self.assertEqual(path, self.path)
        return handle

    def test_an_oversized_trace_keeps_its_newest_whole_lines(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        lines = [f"Timeout (0:00:35)! dump {index}\n" for index in range(2000)]
        with open(self.path, "w", encoding="utf-8") as target:
            target.writelines(lines)
        handle = self._open(limit=20_000, keep=5_000)
        handle.write("new dump\n")
        handle.flush()
        with open(self.path, encoding="utf-8") as source:
            kept = source.read()
        self.assertLessEqual(len(kept.encode()), 5_000 + len("new dump\n"))
        self.assertTrue(kept.startswith("Timeout"), kept[:40])  # 行の途中から始めない
        self.assertTrue(kept.endswith(lines[-1] + "new dump\n"))

    def test_a_trace_under_the_limit_is_left_alone(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as target:
            target.write("Timeout (0:00:35)!\n")
        self._open(limit=20_000, keep=5_000).close()
        with open(self.path, encoding="utf-8") as source:
            self.assertEqual(source.read(), "Timeout (0:00:35)!\n")

    def test_a_missing_trace_is_created_for_appending(self):
        handle = self._open()
        handle.write("x")
        handle.close()
        with open(self.path, encoding="utf-8") as source:
            self.assertEqual(source.read(), "x")


if __name__ == "__main__":
    unittest.main()
