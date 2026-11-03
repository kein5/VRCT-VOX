"""stdout専用書き込みスレッド (フェーズ3項目18) のテスト。

対象の欠陥: 以前は printLog/printResponse を呼んだスレッドが直接
sys.stdout.write() を (ロック付きで) 実行していたため、パイプが壊れる/
埋まると書き込みに関わる全スレッドが芋づる式に停止していた
(freeze_trace.log 2026-08-27、35秒フリーズで実際に確認済み)。

書き込みを専用スレッド1本に閉じ込め、呼び出し元はキューに積むだけに
することでこの連鎖を断つ。printResponse (実応答) は取りこぼさず、
printLog (診断ログ) は有界キューであふれたら古いものから捨てる。
連続して書き込みに失敗した場合は「フロントエンド消失」とみなして
コールバックを呼ぶ (既定は os._exit、テストでは差し替える)。
"""

import time
import inspect
import statistics
import sys
import threading
import unittest
from queue import Queue
from types import SimpleNamespace
from unittest.mock import patch

import utils


def _wait_until(predicate, timeout=2.0, interval=0.01) -> bool:
    """`predicate()` が真になるまで短い間隔でポーリングする
    (書き込みスレッドは別スレッドで非同期に動くため)。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _StdoutWriterTestCase(unittest.TestCase):
    """各テストの前後で書き込みスレッド・キュー・コールバックを
    まっさらな状態に戻す。グローバルなシングルトン状態を扱うため。"""

    def setUp(self) -> None:
        utils.stopStdoutWriter()
        # 直前のテストが残したスレッドが完全に停止するのを待つ。
        _wait_until(lambda: utils._stdout_writer_thread is None or not utils._stdout_writer_thread.is_alive())
        if utils._stdout_monitor_thread is not None:
            utils._stdout_monitor_thread.join(timeout=1.0)
            self.assertFalse(utils._stdout_monitor_thread.is_alive())
        utils._stdout_response_queue = utils._StdoutResponseQueue()
        utils._stdout_log_queue = Queue(maxsize=utils._STDOUT_LOG_QUEUE_MAXSIZE)
        utils._stdout_writer_thread = None
        utils._stdout_monitor_thread = None
        utils._stdout_monitor_deadline = None
        utils._stdout_stalled_at = None
        utils._stdout_pending_since = None
        utils._stdout_in_flight = False
        utils._stdout_completed_lines = 0
        utils._stdout_lost_lines = 0
        utils._stdout_needs_separator = False
        diagnostics = patch.object(utils, "_logStdoutTransport")
        self._diagnostics = diagnostics.start()
        self.addCleanup(diagnostics.stop)
        utils.setFrontendLostCallback(None)

    def tearDown(self) -> None:
        utils.stopStdoutWriter()
        if utils._stdout_writer_thread is not None:
            utils._stdout_writer_thread.join(timeout=1.0)
            self.assertFalse(utils._stdout_writer_thread.is_alive())
        if utils._stdout_monitor_thread is not None:
            utils._stdout_monitor_thread.join(timeout=1.0)
            self.assertFalse(utils._stdout_monitor_thread.is_alive())
        utils.setFrontendLostCallback(None)


class TestEnqueuedLinesAreWrittenAsynchronously(_StdoutWriterTestCase):
    def test_log_line_is_eventually_written(self) -> None:
        written = []
        with patch.object(utils, "_writeStdoutLine", side_effect=lambda line: written.append(line) or True):
            utils._enqueueLogLine("hello-log")
            self.assertTrue(_wait_until(lambda: written == ["hello-log"]))

    def test_response_line_is_eventually_written(self) -> None:
        written = []
        with patch.object(utils, "_writeStdoutLine", side_effect=lambda line: written.append(line) or True):
            utils._enqueueResponseLine("hello-response")
            self.assertTrue(_wait_until(lambda: written == ["hello-response"]))

    def test_response_lines_take_priority_over_log_lines(self) -> None:
        written = []
        with patch.object(utils, "_writeStdoutLine", side_effect=lambda line: written.append(line) or True), \
             patch.object(utils, "_ensureStdoutWriterStarted"):
            # 書き込みスレッドをまだ起動させない状態で両方を積んでおき
            # (でないと先に積んだログを書き込みスレッドが即座に処理して
            # しまい、優先度の検証にならない)、その後まとめて起動する。
            utils._enqueueLogLine("log-1")
            utils._enqueueResponseLine("response-1")

        # ログを先に積んでも、後から積んだ応答が先に書き込まれる
        # (応答キューが優先されるため)。
        with patch.object(utils, "_writeStdoutLine", side_effect=lambda line: written.append(line) or True):
            utils._ensureStdoutWriterStarted()
            self.assertTrue(_wait_until(lambda: len(written) == 2))
        self.assertEqual(written[0], "response-1")
        self.assertEqual(written[1], "log-1")


class _TimedStdout:
    def __init__(self):
        self.writes = Queue()
        self.flushes = 0

    def write(self, text):
        self.writes.put((text, time.perf_counter()))

    def flush(self):
        self.flushes += 1


def _idle_condition(module):
    # 同じプローブを変更前の log_queue 待機にも適用できるようにする。
    return getattr(module, "_stdout_writer_condition", module._stdout_log_queue.not_empty)


def measure_idle_response_latency(module, iterations=200):
    """実際の待機に入るたびに1件投入し、fake stdout の write までを測る。"""
    idle = threading.Event()
    condition = _idle_condition(module)
    original_wait = condition.wait
    stdout = _TimedStdout()
    latencies = []

    def wait(timeout=None):
        if threading.current_thread().name == "StdoutWriter":
            idle.set()
        return original_wait(timeout)

    with patch.object(condition, "wait", wait), \
            patch.object(module, "sys", SimpleNamespace(stdout=stdout)):
        module._ensureStdoutWriterStarted()
        try:
            for index in range(iterations):
                assert idle.wait(1.0), "writer did not become idle"
                idle.clear()
                started = time.perf_counter()
                module._enqueueResponseLine(f"response-{index}")
                text, written_at = stdout.writes.get(timeout=1.0)
                assert text == f"response-{index}\n"
                latencies.append((written_at - started) * 1000)
        finally:
            module.stopStdoutWriter()
            module._stdout_writer_thread.join(timeout=1.0)
            assert not module._stdout_writer_thread.is_alive()
    assert stdout.flushes == iterations
    return {"iterations": iterations, "median_ms": statistics.median(latencies),
            "max_ms": max(latencies)}


def measure_idle_writer(module, seconds=1.0):
    """writer だけを trace し、空のまま再実行したループ回数と停止時間を測る。"""
    loop = module._stdoutWriterLoop
    source, first_line = inspect.getsourcelines(loop)
    loop_line = first_line + next(i for i, line in enumerate(source) if line.lstrip().startswith("while "))
    iterations = []
    idle = threading.Event()
    condition = _idle_condition(module)
    original_wait = condition.wait

    def trace(frame, event, arg):
        if frame.f_code is loop.__code__:
            if event == "line" and frame.f_lineno == loop_line:
                iterations.append(time.perf_counter())
            return trace
        return None

    def traced_loop():
        sys.settrace(trace)
        try:
            loop()
        finally:
            sys.settrace(None)

    def wait(timeout=None):
        if threading.current_thread().name == "StdoutWriter":
            idle.set()
        return original_wait(timeout)

    stdout = _TimedStdout()
    with patch.object(module, "_stdoutWriterLoop", traced_loop), \
            patch.object(condition, "wait", wait), \
            patch.object(module, "sys", SimpleNamespace(stdout=stdout)):
        module._ensureStdoutWriterStarted()
        try:
            assert idle.wait(1.0), "writer did not become idle"
            before = len(iterations)
            started = time.perf_counter()
            threading.Event().wait(seconds)
            elapsed = time.perf_counter() - started
            wakeups = len(iterations) - before
        finally:
            stopped_at = time.perf_counter()
            module.stopStdoutWriter()
            module._stdout_writer_thread.join(timeout=0.5)
            stop_ms = (time.perf_counter() - stopped_at) * 1000
            assert not module._stdout_writer_thread.is_alive()
    assert stdout.writes.empty()
    return {"idle_seconds": elapsed, "idle_loop_iterations": wakeups, "stop_ms": stop_ms}


class TestWriterNotifications(_StdoutWriterTestCase):
    def test_idle_responses_wake_writer_promptly(self) -> None:
        result = measure_idle_response_latency(utils)
        self.assertLess(result["median_ms"], 10.0, result)

    def test_idle_writer_does_not_poll_and_stop_wakes_it(self) -> None:
        result = measure_idle_writer(utils)
        self.assertEqual(result["idle_loop_iterations"], 0, result)
        self.assertLess(result["stop_ms"], 500.0, result)

    def test_response_priority_and_fifo_after_idle_wakeup(self) -> None:
        stdout = _TimedStdout()
        idle = threading.Event()
        condition = utils._stdout_writer_condition
        original_wait = condition.wait

        def wait(timeout=None):
            idle.set()
            return original_wait(timeout)

        with patch.object(condition, "wait", wait), \
                patch.object(utils, "sys", SimpleNamespace(stdout=stdout)):
            utils._ensureStdoutWriterStarted()
            try:
                self.assertTrue(idle.wait(1.0))
                with condition:
                    for index in range(3):
                        utils._enqueueLogLine(f"log-{index}")
                        utils._enqueueResponseLine(f"response-{index}")
                written = [stdout.writes.get(timeout=1.0)[0] for _ in range(6)]
            finally:
                utils.stopStdoutWriter()
                utils._stdout_writer_thread.join(timeout=1.0)
        self.assertEqual(written, [f"response-{i}\n" for i in range(3)] + [f"log-{i}\n" for i in range(3)])
        self.assertEqual(stdout.flushes, 6)

    def test_many_producers_keep_all_lines_and_each_producers_order(self) -> None:
        stdout = _TimedStdout()
        barrier = threading.Barrier(8)

        def produce(producer):
            barrier.wait(timeout=2.0)
            for index in range(20):
                utils._enqueueLogLine(f"log-{producer}-{index}")
                utils._enqueueResponseLine(f"response-{producer}-{index}")

        with patch.object(utils, "sys", SimpleNamespace(stdout=stdout)):
            producers = [threading.Thread(target=produce, args=(p,)) for p in range(8)]
            try:
                for producer in producers:
                    producer.start()
                for producer in producers:
                    producer.join(timeout=2.0)
                    self.assertFalse(producer.is_alive())
                written = [stdout.writes.get(timeout=1.0)[0] for _ in range(320)]
            finally:
                utils.stopStdoutWriter()
                if utils._stdout_writer_thread is not None:
                    utils._stdout_writer_thread.join(timeout=1.0)
        for kind in ("log", "response"):
            for producer in range(8):
                prefix = f"{kind}-{producer}-"
                self.assertEqual([line for line in written if line.startswith(prefix)],
                                 [f"{prefix}{i}\n" for i in range(20)])
        self.assertEqual(stdout.flushes, 320)

    def test_stop_before_start_and_repeated_stop_allow_restart(self) -> None:
        stdout = _TimedStdout()
        with patch.object(utils, "sys", SimpleNamespace(stdout=stdout)):
            for index in range(10):
                utils.stopStdoutWriter()
                utils.stopStdoutWriter()
                utils._enqueueResponseLine(f"response-{index}")
                self.assertEqual(stdout.writes.get(timeout=1.0)[0], f"response-{index}\n")
                utils.stopStdoutWriter()
                utils._stdout_writer_thread.join(timeout=0.5)
                self.assertFalse(utils._stdout_writer_thread.is_alive())


class TestLogQueueDropsOldestWhenFull(_StdoutWriterTestCase):
    def test_repeated_overflow_keeps_exactly_latest_200_in_order(self) -> None:
        self.assertEqual(utils._STDOUT_LOG_QUEUE_MAXSIZE, 200)
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for index in range(700):
                utils._enqueueLogLine(f"log-{index}")
        self.assertEqual(list(utils._stdout_log_queue.queue), [f"log-{i}" for i in range(500, 700)])

    def test_overflow_drops_the_oldest_entry(self) -> None:
        # 書き込みスレッド自体は起動させず (＝キューが誰にも drain されない
        # 状態で)、キューの詰め込み動作だけを検証する。
        maxsize = utils._STDOUT_LOG_QUEUE_MAXSIZE
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for i in range(maxsize):
                utils._enqueueLogLine(f"log-{i}")
            self.assertEqual(utils._stdout_log_queue.qsize(), maxsize)

            utils._enqueueLogLine("log-overflow")

            self.assertEqual(utils._stdout_log_queue.qsize(), maxsize)
            remaining = list(utils._stdout_log_queue.queue)
            self.assertNotIn("log-0", remaining, "the oldest entry should have been dropped")
            self.assertIn("log-overflow", remaining, "the newest entry should have been kept")


class TestResponseQueueNeverDropsUnderLoad(_StdoutWriterTestCase):
    def test_many_response_lines_are_all_queued(self) -> None:
        with patch.object(utils, "_ensureStdoutWriterStarted"):
            for i in range(1000):
                utils._enqueueResponseLine(f"response-{i}")
            self.assertEqual(utils._stdout_response_queue.qsize(), 1000)


class TestConsecutiveFailuresTriggerFrontendLostCallback(_StdoutWriterTestCase):
    def test_broken_pipe_and_closed_stdout_keep_failure_threshold(self) -> None:
        self.assertEqual(utils._MAX_CONSECUTIVE_STDOUT_FAILURES, 50)
        for failure in (BrokenPipeError("pipe closed"), ValueError("I/O operation on closed file")):
            for operation in ("write", "flush"):
                with self.subTest(failure=type(failure).__name__, operation=operation):
                    stdout = _TimedStdout()
                    lost = threading.Event()
                    utils.setFrontendLostCallback(lost.set)
                    with patch.object(utils, "_ensureStdoutWriterStarted"):
                        for index in range(50):
                            utils._enqueueResponseLine(f"response-{index}")
                    with patch.object(utils, "sys", SimpleNamespace(stdout=stdout)), \
                            patch.object(stdout, operation, side_effect=failure) as failing, \
                            patch.object(utils, "_logStdoutTransport") as error:
                        utils._ensureStdoutWriterStarted()
                        self.assertTrue(lost.wait(1.0))
                        utils._stdout_writer_thread.join(timeout=0.5)
                        self.assertFalse(utils._stdout_writer_thread.is_alive())
                        self.assertEqual(failing.call_count, 50)
                        messages = [call.args[0] for call in error.call_args_list]
                        self.assertEqual(sum(message.startswith("stdout write failed:") for message in messages), 50)
                        self.assertEqual(sum(message.startswith("stdout line lost:") for message in messages), 50)

    def test_callback_fires_after_the_configured_number_of_failures(self) -> None:
        callback_calls = []
        utils.setFrontendLostCallback(lambda: callback_calls.append(True))

        with patch.object(utils, "_writeStdoutLine", return_value=False):
            for _ in range(utils._MAX_CONSECUTIVE_STDOUT_FAILURES):
                utils._enqueueLogLine("doomed-line")
            self.assertTrue(_wait_until(lambda: len(callback_calls) == 1))

    def test_default_callback_is_os_exit(self) -> None:
        # 既定 (コールバック未登録) では os._exit(1) を呼ぶことを、実際には
        # プロセスを終了させずに確認する。
        with patch.object(utils, "_writeStdoutLine", return_value=False), \
             patch.object(utils.os, "_exit") as mock_exit:
            for _ in range(utils._MAX_CONSECUTIVE_STDOUT_FAILURES):
                utils._enqueueLogLine("doomed-line")
            self.assertTrue(_wait_until(lambda: mock_exit.called))
            mock_exit.assert_called_once_with(1)

    def test_a_successful_write_resets_the_failure_counter(self) -> None:
        callback_calls = []
        utils.setFrontendLostCallback(lambda: callback_calls.append(True))

        results = [False] * (utils._MAX_CONSECUTIVE_STDOUT_FAILURES - 1) + [True] + [False] * (
            utils._MAX_CONSECUTIVE_STDOUT_FAILURES - 1
        )
        with patch.object(utils, "_writeStdoutLine", side_effect=results):
            for _ in range(len(results)):
                utils._enqueueLogLine("line")
            # 全件が書き込みスレッドに処理されるまで待ってから判定する
            # (with ブロックを抜けてパッチが外れる前にキューを空にしておかないと、
            # 残った項目が実際の _writeStdoutLine に渡り、後続テストの
            # stdout をリアルに汚してしまう)。
            self.assertTrue(_wait_until(lambda: utils._stdout_log_queue.empty()))
            # 途中で成功が1回挟まるため、カウンタがリセットされ、
            # まだ閾値には到達しないはず。
            self.assertEqual(callback_calls, [])


class TestWriterStartupIsRaceFree(_StdoutWriterTestCase):
    def test_concurrent_start_calls_result_in_a_single_thread(self) -> None:
        import threading

        barrier = threading.Barrier(8)

        def start_it():
            barrier.wait()
            utils._ensureStdoutWriterStarted()

        threads = [threading.Thread(target=start_it) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 起動した書き込みスレッドは常にただ1本 (StdoutWriter という
        # 名前を持つ living thread が1本だけ) であることを確認する。
        stdout_writer_threads = [
            t for t in threading.enumerate() if t.name == "StdoutWriter" and t.is_alive()
        ]
        self.assertEqual(len(stdout_writer_threads), 1)


class PutDroppingOldestOnFullTests(unittest.TestCase):
    """_enqueueLogLine (項目18) から切り出した共通ヘルパー。項目20で
    audio_queue/energy_queue にも展開したため、両者から独立して
    直接検証する (レビュー指摘: 以前は同じロジックが2箇所に手書きで
    重複していた)。"""

    def test_puts_normally_when_not_full(self) -> None:
        q = Queue(maxsize=2)
        evicted = utils.putDroppingOldestOnFull(q, "a")
        self.assertFalse(evicted)
        self.assertEqual(list(q.queue), ["a"])

    def test_evicts_the_oldest_item_when_full(self) -> None:
        q = Queue(maxsize=2)
        q.put("a")
        q.put("b")
        evicted = utils.putDroppingOldestOnFull(q, "c")
        self.assertTrue(evicted)
        self.assertEqual(list(q.queue), ["b", "c"])

    def test_works_on_an_already_empty_queue_racing_another_consumer(self) -> None:
        # get_nowait() が Empty を送出するタイミング (満杯判定直後に
        # 別スレッドが先に空にした場合) でも例外を出さずに積めること。
        q = Queue(maxsize=1)
        q.put("stale")
        # 満杯にした直後、内部でget_nowaitする前に誰か(このテストの
        # シミュレーションとしてここで先に)空にしてしまうケース。
        q.get_nowait()
        evicted = utils.putDroppingOldestOnFull(q, "fresh")
        self.assertFalse(evicted)
        self.assertEqual(list(q.queue), ["fresh"])


if __name__ == "__main__":
    unittest.main()
