"""stdout の詰まり・集約・行境界をメモリだけで検証する（socket 不使用）。"""

import ast
import io
import json
import threading
from contextlib import ExitStack
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock, patch

import utils
from utils import _logStdoutTransport as log_transport
from test_utils_stdout_writer import _StdoutWriterTestCase, _wait_until


CAPTION = "/run/realtime_caption"


def caption(revision=1, **changes):
    return {"source": "mic", "namespace": "session", "generation": 1,
            "item_id": "utterance", "revision": revision, "state": "partial",
            "text": f"caption {revision}", **changes}


class StdoutBacklogTests(_StdoutWriterTestCase):
    def setUp(self):
        super().setUp()
        logger = patch.object(utils, "process_logger", Mock())
        logger.start()
        self.addCleanup(logger.stop)

    def notify(self, endpoint, result, status=200):
        utils.printResponse(status, endpoint, result, notification=True)

    def drain(self):
        written = []
        with patch.object(utils, "_writeStdoutLine", side_effect=lambda line: written.append(json.loads(line)) or True):
            utils._ensureStdoutWriterStarted()
            self.assertTrue(_wait_until(lambda: utils._stdout_response_queue.empty() and not utils._stdout_in_flight))
            utils.stopStdoutWriter()
            utils._stdout_writer_thread.join(1)
        return written

    def test_audit_1000_caption_probe_leaves_two_pending_lines(self):
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for index in range(1000):
                self.notify(CAPTION, caption(index + 1))
            utils.printResponse(200, "/get/data/voice_status", {"active": False})
        self.assertEqual(utils._stdout_response_queue.qsize(), 2)
        self.assertEqual(len(utils._stdout_response_queue._replaceable), 1)
        written = self.drain()
        self.assertEqual([row["result"] for row in written], [caption(1000), {"active": False}])
        self.assertEqual(utils._stdout_response_queue.qsize(), 0)

    def test_blocked_writer_bounds_1000_updates_and_preserves_every_reply(self):
        entered, release = threading.Event(), threading.Event()
        written = []

        def write(line):
            if line == "held":
                entered.set()
                release.wait(2)
            else:
                written.append(json.loads(line))
            return True

        with patch.object(utils, "_writeStdoutLine", side_effect=write):
            utils._enqueueResponseLine("held")
            self.assertTrue(entered.wait(1))
            try:
                for index in range(1000):
                    self.notify(CAPTION, caption(index + 1))
                    if index % 100 == 0:
                        utils.printResponse(200, "/run/send_message_box", index)
                self.assertEqual(utils._stdout_response_queue.qsize(), 11)
                self.assertEqual(len(utils._stdout_response_queue._replaceable), 1)
            finally:
                release.set()
            self.assertTrue(_wait_until(lambda: len(written) == 11))
        self.assertEqual([row["result"] for row in written if row["endpoint"] != CAPTION], list(range(0, 1000, 100)))
        self.assertEqual([row["result"] for row in written if row["endpoint"] == CAPTION], [caption(1000)])

    def test_command_replies_errors_finals_and_unknown_notifications_stay_fifo(self):
        expected = []
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for index in range(25):
                # 許可された endpoint でも、UI要求への応答は集約しない。
                utils.printResponse(200, "/run/check_mic_volume", index)
                expected.append((200, "/run/check_mic_volume", index))
                for endpoint, value, status in (
                    (CAPTION, caption(index + 1, state="final"), 200),
                    (CAPTION, caption(index + 1, state="translated"), 200),
                    (CAPTION, caption(index + 1, state="discarded"), 200),
                    ("/run/transcription_send_mic_message", {"text": str(index)}, 200),
                    ("/run/downloaded_whisper_weight", "tiny", 200),
                    ("/run/initialization_complete", {}, 200),
                    ("/run/unknown", index, 200),
                    ("/run/check_mic_volume", index, 500),
                ):
                    self.notify(endpoint, value, status)
                    expected.append((status, endpoint, value))
        written = self.drain()
        self.assertEqual([(r["status"], r["endpoint"], r["result"]) for r in written], expected)

    def test_partial_cannot_follow_its_final_and_new_items_are_independent(self):
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            self.notify(CAPTION, caption())
            self.notify(CAPTION, caption(2, source="speaker"))
            self.notify(CAPTION, caption(3, item_id="another"))
            self.notify(CAPTION, caption(4, state="final"))
            self.notify(CAPTION, caption(3))  # 遅れて届いた旧 partial も復活させない。
            self.notify(CAPTION, caption(5, state="translated"))
            self.notify(CAPTION, caption(1, generation=2))
        written = self.drain()
        self.assertEqual([r["result"] for r in written], [caption(2, source="speaker"),
                         caption(3, item_id="another"), caption(4, state="final"),
                         caption(5, state="translated"), caption(1, generation=2)])

    def test_in_flight_partial_completes_before_final(self):
        entered, release = threading.Event(), threading.Event()
        written = []

        def write(line):
            if not written:
                entered.set()
                release.wait(2)
            written.append(json.loads(line)["result"])
            return True

        with patch.object(utils, "_writeStdoutLine", side_effect=write):
            self.notify(CAPTION, caption())
            self.assertTrue(entered.wait(1))
            try:
                self.notify(CAPTION, caption(2))
                self.notify(CAPTION, caption(3, state="final"))
            finally:
                release.set()
            self.assertTrue(_wait_until(lambda: len(written) == 2))
        self.assertEqual(written, [caption(), caption(3, state="final")])

    def test_queued_finals_are_protected_beyond_the_delivered_history_limit(self):
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for index in range(300):
                self.notify(CAPTION, caption(2, state="final", item_id=str(index)))
            self.notify(CAPTION, caption(1, item_id="0"))
        self.assertEqual(utils._stdout_response_queue.qsize(), 300)
        self.assertTrue(all(row["result"]["state"] == "final" for row in self.drain()))
        self.assertEqual(len(utils._stdout_response_queue._terminal), 256)
        self.assertEqual(utils._stdout_response_queue._pending_terminals, {})

    def test_start_stop_meter_and_download_completion_keep_survivor_order(self):
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            self.notify("/run/check_mic_volume", 1)
            utils.printResponse(200, "/set/enable/check_mic_threshold", True)
            self.notify("/run/check_mic_volume", 2)
            utils.printResponse(200, "/set/disable/check_mic_threshold", False)
            for value in (0.1, 0.2, 1):
                self.notify("/run/download_progress_whisper_weight", {"weight_type": "tiny", "progress": value})
            self.notify("/run/downloaded_whisper_weight", "tiny")
        rows = self.drain()
        self.assertEqual([row["result"] for row in rows], [True, 2, False, {"weight_type": "tiny", "progress": 1}, "tiny"])

    def test_allowlist_keys_keep_only_latest_independent_values(self):
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for index in range(1000):
                self.notify("/run/vr_panel_pointer", {"x": index, "y": index})
                self.notify("/run/check_mic_volume", index)
                self.notify("/run/check_speaker_volume", index)
                for model in ("whisper", "ctranslate2"):
                    for weight in ("tiny", "small"):
                        self.notify(f"/run/download_progress_{model}_weight", {"weight_type": weight, "progress": index / 1000})
            self.notify("/run/vr_panel_pointer", None)
        self.assertEqual(utils._stdout_response_queue.qsize(), 7)
        rows = self.drain()
        self.assertEqual(rows[-1]["result"], None)
        self.assertEqual([r["result"] for r in rows[:2]], [999, 999])
        self.assertTrue(all(r["result"]["progress"] == 0.999 for r in rows[2:6]))

    def test_ambiguous_shapes_empty_partial_and_key_overflow_are_lossless(self):
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for _ in range(2):
                self.notify(CAPTION, {"source": "mic", "state": "partial", "text": "no identity"})
                self.notify(CAPTION, caption(text=""))
                self.notify("/run/check_mic_volume", {"error": "ambiguous"})
                self.notify("/run/download_progress_whisper_weight", {"progress": 0.5})
            for index in range(utils._STDOUT_REPLACEABLE_MAX_KEYS + 10):
                self.notify(CAPTION, caption(item_id=str(index)))
        self.assertEqual(len(utils._stdout_response_queue._replaceable), 64)
        self.assertEqual(utils._stdout_response_queue.qsize(), 82)
        self.assertEqual(len(self.drain()), 82)

    def test_mainloop_run_marks_only_notifications(self):
        # アプリの import/起動なしで、実際の入口を検証する。
        tree = ast.parse((Path(utils.__file__).parent / "mainloop.py").read_text())
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
        response = Mock()
        namespace = {"printResponse": response, "Any": object}
        exec(compile(ast.Module(body=[run], type_ignores=[]), "mainloop.py", "exec"), namespace)
        namespace["run"](200, CAPTION, caption())
        response.assert_called_once_with(200, CAPTION, caption(), notification=True)


class _FaultyStdout:
    def __init__(self, failures):
        self.output = ""
        self.failures = failures

    def write(self, text):
        if text != "\n" and self.failures:
            self.failures -= 1
            self.output += text[:5]
            raise OSError(22, "simulated partial write")
        self.output += text
        return len(text)

    def flush(self):
        pass

    def parsed(self):
        rows = []
        for line in self.output.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass  # sidecarSession.js と同じ行単位の復旧。
        return rows


class StdoutWriteFailureTests(_StdoutWriterTestCase):
    def write_lines(self, stdout, lines):
        with patch.object(utils, "sys", SimpleNamespace(stdout=stdout)):
            with patch.object(utils, "_ensureStdoutWriterStarted"):
                for line in lines:
                    utils._enqueueResponseLine(json.dumps(line))
            utils._ensureStdoutWriterStarted()
            self.assertTrue(_wait_until(lambda: utils._stdout_response_queue.empty() and not utils._stdout_in_flight))
            utils.stopStdoutWriter()
            utils._stdout_writer_thread.join(1)

    def test_transient_partial_write_retries_same_line_before_following_reply(self):
        stdout = _FaultyStdout(1)
        rows = [{"reply": 1}, {"reply": 2}]
        self.write_lines(stdout, rows)
        self.assertEqual(stdout.parsed(), rows)
        self.assertEqual(utils._stdout_lost_lines, 0)
        self.assertEqual(utils._stdout_completed_lines, 2)
        self.assertIn('stdout write failed: attempt=1 type=OSError errno=22', str(self._diagnostics.call_args_list))

    def test_exhausted_line_is_counted_after_success_and_next_line_is_not_corrupted(self):
        stdout = _FaultyStdout(utils._STDOUT_WRITE_ATTEMPTS)
        self.write_lines(stdout, [{"reply": 1}, {"reply": 2}])
        self.assertEqual(stdout.parsed(), [{"reply": 2}])
        self.assertEqual(utils._stdout_lost_lines, 1)
        self.assertEqual(utils._stdout_completed_lines, 1)
        self.assertEqual(sum(call.args[0].startswith("stdout line lost:") for call in self._diagnostics.call_args_list), 1)

    def test_failed_separator_is_retried_before_any_new_json(self):
        stdout = _FaultyStdout(0)
        real_write = stdout.write
        writes = []

        def write(text):
            writes.append(text)
            if len(writes) <= 2:
                raise OSError(22, "line then separator failure")
            return real_write(text)

        stdout.write = write
        self.write_lines(stdout, [{"reply": 1}, {"reply": 2}])
        self.assertEqual(writes[:3], ['{"reply": 1}\n', "\n", "\n"])
        self.assertEqual(stdout.parsed(), [{"reply": 1}, {"reply": 2}])

    def test_flush_error_and_short_write_preserve_next_line_boundary(self):
        for mode in ("flush", "short"):
            with self.subTest(mode=mode):
                stdout = _FaultyStdout(0)
                calls = []
                real_write = stdout.write

                def write(text):
                    calls.append(text)
                    if len(calls) == 1 and mode == "short":
                        stdout.output += text[:5]
                        return 5
                    return real_write(text)

                stdout.write = write
                if mode == "flush":
                    stdout.flush = Mock(side_effect=[OSError(22, "flush"), None, None, None])
                self.write_lines(stdout, [{"reply": 1}, {"reply": 2}])
                # flush が実は配送済みの場合は重複し得るが、次の行は壊さない。
                self.assertEqual(stdout.parsed()[-1], {"reply": 2})
                self.assertEqual(stdout.parsed().count({"reply": 2}), 1)
                self.assertEqual(calls[1], "\n")

    def test_transport_diagnostics_never_fall_back_to_stdout(self):
        output = io.StringIO()
        logger = Mock()
        logger.error.side_effect = OSError("disk failure")
        with patch.object(utils, "sys", SimpleNamespace(stdout=output)), patch.object(utils, "error_logger", logger):
            log_transport("stdout stalled")
        self.assertEqual(output.getvalue(), "")


class StdoutStallTests(_StdoutWriterTestCase):
    def test_1000_healthy_meter_samples_do_not_wake_monitor_per_line(self):
        writer_idle, monitor_idle = threading.Event(), threading.Event()
        monitor_waits = []
        conditions = {utils._stdout_writer_condition,
                      getattr(utils, "_stdout_monitor_condition", utils._stdout_writer_condition)}

        def observe_wait(condition):
            original_wait = condition.wait

            def wait(timeout=None):
                if threading.current_thread().name == "StdoutWriter":
                    writer_idle.set()
                else:
                    monitor_waits.append(timeout)
                    monitor_idle.set()
                return original_wait(timeout)

            return wait

        with ExitStack() as stack:
            for condition in conditions:
                stack.enter_context(patch.object(condition, "wait", observe_wait(condition)))
            stack.enter_context(patch.object(utils, "time", SimpleNamespace(monotonic=lambda: 100.0)))
            stack.enter_context(patch.object(utils, "process_logger", Mock()))
            written = stack.enter_context(patch.object(utils, "_writeStdoutLine", return_value=True))
            utils._ensureStdoutWriterStarted()
            try:
                self.assertTrue(writer_idle.wait(1))
                self.assertTrue(monitor_idle.wait(1))
                for index in range(1000):
                    writer_idle.clear()
                    endpoint = "/run/check_mic_volume" if index % 2 else "/run/check_speaker_volume"
                    utils.printResponse(200, endpoint, index, notification=True)
                    # 毎回空になる健康な writer でも監視の期限は一度だけセットする。
                    self.assertTrue(writer_idle.wait(1))
                with utils._stdout_writer_condition:
                    self.monitor_measurement = {"samples_written": written.call_count,
                                                "monitor_wait_calls": len(monitor_waits),
                                                "pending": utils._stdout_response_queue.qsize()}
                    self.assertEqual(written.call_count, 1000)
                    self.assertIsNone(utils._stdout_pending_since)
                    self.assertLessEqual(len(monitor_waits), 2, self.monitor_measurement)
            finally:
                utils.stopStdoutWriter()
                utils._stdout_writer_thread.join(1)
                utils._stdout_monitor_thread.join(1)

    def test_monitor_rechecks_progress_at_deadline_and_rearms_after_idle(self):
        waits = Queue()
        writer_idle, entered, release = (threading.Event() for _ in range(3))
        now = [100.0]
        monitor_wait = utils._stdout_monitor_condition.wait
        writer_wait = utils._stdout_writer_condition.wait

        def wait_monitor(timeout=None):
            waits.put(timeout)
            return monitor_wait(timeout)

        def wait_writer(timeout=None):
            writer_idle.set()
            return writer_wait(timeout)

        def write(line):
            if line == "held":
                entered.set()
                release.wait(2)
            return True

        with patch.object(utils, "time", SimpleNamespace(monotonic=lambda: now[0])), \
                patch.object(utils._stdout_monitor_condition, "wait", side_effect=wait_monitor), \
                patch.object(utils._stdout_writer_condition, "wait", side_effect=wait_writer), \
                patch.object(utils, "_writeStdoutLine", side_effect=write):
            utils._ensureStdoutWriterStarted()
            try:
                self.assertIsNone(waits.get(timeout=1))
                self.assertTrue(writer_idle.wait(1))
                writer_idle.clear()
                utils._enqueueResponseLine("healthy")
                self.assertEqual(waits.get(timeout=1), 20.0)
                self.assertTrue(writer_idle.wait(1))
                with utils._stdout_writer_condition:
                    now[0] = 110.0
                    writer_idle.clear()
                    utils._enqueueResponseLine("held")
                self.assertTrue(entered.wait(1))
                self.assertTrue(waits.empty())
                # 最初の期限120では、時刻110に始めた行を早まって詰まりにしない。
                with utils._stdout_monitor_condition:
                    now[0] = 120.0
                    utils._stdout_monitor_condition.notify()
                self.assertEqual(waits.get(timeout=1), 10.0)
                release.set()
                self.assertTrue(writer_idle.wait(1))
                with utils._stdout_monitor_condition:
                    now[0] = 130.0
                    utils._stdout_monitor_condition.notify()
                self.assertIsNone(waits.get(timeout=1))
                # 空のままなら期限なしで眠り、新しい仕事は新しい期限をセットする。
                with utils._stdout_writer_condition:
                    now[0] = 140.0
                    utils._enqueueResponseLine("new burst")
                self.assertEqual(waits.get(timeout=1), 20.0)
                self._diagnostics.assert_not_called()
            finally:
                release.set()
                utils.stopStdoutWriter()
                utils._stdout_writer_thread.join(1)
                utils._stdout_monitor_thread.join(1)

    def test_stall_is_recorded_once_then_recovery_once_without_stopping_writer(self):
        entered, release, stalled, recovered = (threading.Event() for _ in range(4))
        below_threshold = threading.Event()
        messages = []
        now = [100.0]
        original_wait = utils._stdout_monitor_condition.wait

        def wait(timeout=None):
            if threading.current_thread().name == "StdoutMonitor" and now[0] == 119.9:
                below_threshold.set()
            return original_wait(timeout)

        def record(message):
            messages.append(message)
            if message.startswith("stdout stalled:"):
                stalled.set()
            if message.startswith("stdout recovered:"):
                recovered.set()

        def write(line):
            entered.set()
            release.wait(2)
            return True

        with patch.object(utils, "time", SimpleNamespace(monotonic=lambda: now[0])), \
                patch.object(utils._stdout_monitor_condition, "wait", side_effect=wait), \
                patch.object(utils, "_writeStdoutLine", side_effect=write), \
                patch.object(utils, "_logStdoutTransport", side_effect=record):
            utils._enqueueResponseLine("held")
            self.assertTrue(entered.wait(1))
            try:
                utils._enqueueResponseLine("reply")
                # 偽時計の進行を期限待ちに伝える。通常の投入は監視を起こさない。
                with utils._stdout_monitor_condition:
                    now[0] += 19.9
                    utils._stdout_monitor_condition.notify()
                self.assertTrue(below_threshold.wait(1))
                self.assertFalse(stalled.is_set())
                with utils._stdout_monitor_condition:
                    now[0] += 0.2
                    utils._stdout_monitor_condition.notify()
                self.assertTrue(stalled.wait(1))
                now[0] += 100
                for _ in range(100):
                    utils._enqueueLogLine("still stalled")
                self.assertEqual(len(messages), 1)
                self.assertIn("reliable=1 replaceable=0", messages[0])
                self.assertIn("in_flight=1 lost_lines=0", messages[0])
            finally:
                release.set()
            self.assertTrue(recovered.wait(1))
            self.assertTrue(_wait_until(lambda: utils._stdout_log_queue.empty() and not utils._stdout_in_flight))
            self.assertEqual(len(messages), 2)
            self.assertTrue(utils._stdout_writer_thread.is_alive())

    def test_monitor_detects_block_without_any_further_enqueue(self):
        entered, release, stalled = (threading.Event() for _ in range(3))

        def write(line):
            entered.set()
            release.wait(2)
            return True

        def record(message):
            if message.startswith("stdout stalled:"):
                stalled.set()

        with patch.object(utils, "_STDOUT_STALL_SECONDS", 0.02), \
                patch.object(utils, "_writeStdoutLine", side_effect=write), \
                patch.object(utils, "_logStdoutTransport", side_effect=record):
            utils._enqueueResponseLine("held")
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(stalled.wait(1))
                self.assertTrue(utils._stdout_in_flight)
            finally:
                release.set()
            self.assertTrue(_wait_until(lambda: not utils._stdout_in_flight))

    def test_idle_monitor_and_writer_use_untimed_waits(self):
        waiting = {name: threading.Event() for name in ("StdoutWriter", "StdoutMonitor")}
        timeouts = []

        def observe_wait(condition):
            original_wait = condition.wait

            def wait(timeout=None):
                name = threading.current_thread().name
                timeouts.append((name, timeout))
                waiting[name].set()
                return original_wait(timeout)

            return wait

        with ExitStack() as stack:
            for condition in (utils._stdout_writer_condition, utils._stdout_monitor_condition):
                stack.enter_context(patch.object(condition, "wait", observe_wait(condition)))
            utils._ensureStdoutWriterStarted()
            self.assertTrue(all(event.wait(1) for event in waiting.values()))
            self.assertEqual(sorted(timeouts), [("StdoutMonitor", None), ("StdoutWriter", None)])
            utils.stopStdoutWriter()
            utils._stdout_writer_thread.join(1)
            utils._stdout_monitor_thread.join(1)
