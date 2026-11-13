"""config.json を書き込めなかったら、捨てずに知らせて、あとで書き直す。

以前は書き込みの例外を setter が捨て、変更はメモリーにだけ残って成功を返していた。
再起動すると変更が消え、利用者はそれを知る手段がなかった。
"""

import errno
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import config as config_module
from config import Config


class ConfigSaveFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "config.json"
        self.config = object.__new__(Config)
        self.config.init_config()
        self.config._PATH_CONFIG = str(self.path)
        self.config._file_lock = threading.Lock()
        with patch.object(self.config, "saveConfigToFile"):
            self.config.load_config()
        self.config._save_retry_sec = 3600  # the test triggers the retry itself
        self.failed, self.recovered = [], []
        self.done = threading.Event()

        def on_failed(reason, path):
            self.failed.append((reason, path))
            self.done.set()

        self.config.setSaveCallbacks(on_failed, lambda: self.recovered.append(True))
        self.addCleanup(lambda: self.config._save_retry_timer and self.config._save_retry_timer.cancel())

    def _fail_with(self, code: int):
        real_open = config_module.os.open

        def failing_open(path, *args, **kwargs):
            if str(path).endswith(".tmp"):
                raise OSError(code, "simulated")
            return real_open(path, *args, **kwargs)

        return patch.object(config_module.os, "open", failing_open)

    def test_a_full_disk_is_reported_once_and_retried(self) -> None:
        with self._fail_with(errno.ENOSPC), patch.object(config_module, "errorLogging"):
            self.config.saveConfigToFile()
            self.config.saveConfigToFile()  # still failing: no second notice

        self.assertTrue(self.done.wait(2))
        self.assertEqual(self.failed, [("disk_full", str(self.path))])
        self.assertTrue(self.config._save_retry_timer.is_alive())
        self.assertFalse(self.path.exists())

        self.config.saveConfigToFile()  # space freed

        self.assertEqual(self.recovered, [True])
        self.assertIsInstance(json.loads(self.path.read_text(encoding="utf-8")), dict)
        self.assertIsNone(self.config._save_retry_timer)

    def test_permission_and_read_only_get_their_own_reasons(self) -> None:
        for code, reason in ((errno.EACCES, "permission_denied"), (errno.EROFS, "read_only"), (errno.EIO, "write_failed")):
            with self.subTest(reason=reason):
                self.config._save_failed = False
                self.failed.clear()
                self.done.clear()
                with self._fail_with(code), patch.object(config_module, "errorLogging"):
                    self.config.saveConfigToFile()
                self.assertTrue(self.done.wait(2))
                self.assertEqual(self.failed[0][0], reason)

    def test_a_failure_before_the_callbacks_are_set_is_reported_when_they_are(self) -> None:
        self.config.on_save_failed = None
        self.config._save_failed = False
        with self._fail_with(errno.ENOSPC), patch.object(config_module, "errorLogging"):
            self.config.saveConfigToFile()
        late = []

        self.config.setSaveCallbacks(lambda reason, path: late.append(reason), lambda: None)

        self.assertEqual(late, ["disk_full"])


if __name__ == "__main__":
    unittest.main()
