"""会話ログの切り替えとメッセージ書き込みの競合を検証する。"""

import logging
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import model as model_module
import utils


class ConversationLoggerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.loggers = {name: logging.Logger(name) for name in ("log", "process", "error")}
        get_logger = logging.getLogger
        patcher = patch.object(
            utils.logging, "getLogger",
            side_effect=lambda name=None: self.loggers[name] if name in self.loggers else get_logger(name),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logger = utils.ConversationLogger()
        self.addCleanup(self.logger.stop)
        self.model = object.__new__(model_module.Model)
        self.model._inited = True
        self.model.logger = self.logger
        patcher = patch.object(model_module, "config", SimpleNamespace(PATH_LOGS=str(self.directory)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _start(self, second):
        timestamp = datetime(2026, 11, 3, 12, 0, second)
        with patch.object(model_module, "datetime") as clock:
            clock.now.return_value = timestamp
            self.model.startLogger()
        return self.directory / f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}.log"

    def test_enable_disable_enable_writes_only_to_current_file(self):
        first = self._start(0)
        self.model.logger.info("first message")
        old_handler = self.loggers["log"].handlers[0]
        self.model.stopLogger()
        self.assertEqual(self.loggers["log"].handlers, [])
        self.assertIsNone(old_handler.stream)
        second = self._start(1)
        self.model.logger.info("second message")
        self.model.stopLogger()
        self.assertEqual(first.read_text(encoding="utf-8").count("first message"), 1)
        self.assertNotIn("second message", first.read_text(encoding="utf-8"))
        self.assertEqual(second.read_text(encoding="utf-8").count("second message"), 1)
        self.assertNotIn("first message", second.read_text(encoding="utf-8"))

    def test_start_replaces_existing_handler_without_stop(self):
        first = self._start(0)
        self.model.logger.info("old message")
        old_handler = self.loggers["log"].handlers[0]
        second = self._start(1)
        self.model.logger.info("new message")
        self.assertEqual(len(self.loggers["log"].handlers), 1)
        self.assertIsNone(old_handler.stream)
        self.assertNotIn(old_handler, self.loggers["log"].handlers)
        self.assertNotIn("new message", first.read_text(encoding="utf-8"))
        self.assertEqual(second.read_text(encoding="utf-8").count("new message"), 1)

    def test_stop_after_feature_check_keeps_info_safe_and_does_not_reopen_file(self):
        path = self._start(0)
        self.model.logger.info("before stop")
        self.model.stopLogger()
        # controller が LOGGER_FEATURE を確認した後で停止が完了した状況。
        self.model.logger.info("after stop")
        self.model.stopLogger()
        self.assertNotIn("after stop", path.read_text(encoding="utf-8"))
        self.assertEqual(self.loggers["log"].handlers, [])

    def _assert_write_race(self, replace):
        first = self._start(0)
        handler = self.loggers["log"].handlers[0]
        entered = threading.Event()
        release = threading.Event()
        changing = threading.Event()
        changed = threading.Event()
        errors = []
        emit = handler.emit

        def blocked_emit(record):
            entered.set()
            if not release.wait(2):
                raise AssertionError("write was not released")
            emit(record)

        def write():
            try:
                self.model.logger.info("in flight")
            except Exception as exc:
                errors.append(exc)

        def change():
            changing.set()
            try:
                if replace:
                    self._start(1)
                else:
                    self.model.stopLogger()
            except Exception as exc:
                errors.append(exc)
            finally:
                changed.set()

        writer = threading.Thread(target=write)
        changer = threading.Thread(target=change)
        with patch.object(handler, "emit", side_effect=blocked_emit):
            writer.start()
            try:
                self.assertTrue(entered.wait(2))
                changer.start()
                self.assertTrue(changing.wait(2))
                self.assertFalse(changed.wait(0.05), "書き込みが終わる前にハンドラーを閉じてはいけない")
            finally:
                release.set()
                writer.join(timeout=2)
                if changer.ident is not None:
                    changer.join(timeout=2)
        self.assertFalse(writer.is_alive())
        self.assertFalse(changer.is_alive())
        self.assertEqual(errors, [])
        self.assertIsNone(handler.stream)
        self.assertEqual(first.read_text(encoding="utf-8").count("in flight"), 1)
        self.model.logger.info("after change")
        self.assertNotIn("after change", first.read_text(encoding="utf-8"))
        if replace:
            second = self.directory / "2026-11-03_12-00-01.log"
            self.assertEqual(second.read_text(encoding="utf-8").count("after change"), 1)
        else:
            self.assertEqual(self.loggers["log"].handlers, [])

    def test_stop_during_write_waits_then_closes_without_error(self):
        self._assert_write_race(replace=False)

    def test_start_during_write_waits_then_replaces_without_error(self):
        self._assert_write_race(replace=True)

    def test_handlers_do_not_accumulate_including_same_second_restarts(self):
        handlers = []
        for cycle in range(40):
            path = self._start(cycle // 2)
            self.model.logger.info("cycle %s", cycle)
            self.assertEqual(len(self.loggers["log"].handlers), 1)
            handlers.extend(self.loggers["log"].handlers)
            self.model.stopLogger()
            self.assertEqual(self.loggers["log"].handlers, [])
            self.assertTrue(all(handler.stream is None for handler in handlers))
            self.assertEqual(path.read_text(encoding="utf-8").count(f"cycle {cycle}\n"), 1)

    def test_conversation_lifecycle_does_not_change_diagnostic_handlers(self):
        diagnostics = []
        for name in ("process", "error"):
            logger = utils.setupLogger(name, str(self.directory / f"{name}.log"))
            logger.info("before")
            handler = logger.handlers[0]
            self.addCleanup(handler.close)
            diagnostics.append((logger, handler, handler.stream))
        self._start(0)
        self.model.logger.info("conversation")
        self.model.stopLogger()
        self._start(1)
        for logger, handler, stream in diagnostics:
            self.assertEqual(logger.handlers, [handler])
            self.assertIs(handler.stream, stream)
            self.assertFalse(logger.disabled)
            logger.info("after")
            self.assertIn("after", Path(handler.baseFilename).read_text(encoding="utf-8"))
