"""フリーズ時のスタックの書き出し (freeze_dump.FreezeDump)。

faulthandler.dump_traceback_later() は GIL を持たない C のスレッドが各スレッドのフレームを読むので、
ほかのスレッドが動いている最中だとプロセスごと落ちることがある (Windows の CI で約 10 回に 1 回)。
期限が来たときに書くのは GIL を持った Python のスレッドで、C のスレッドは GIL が返ってこないとき
だけの最後の手段にする。
"""
import threading
import time
from unittest.mock import patch

import pytest

import freeze_dump
from freeze_dump import FreezeDump


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def later():
    """faulthandler の C 側のタイマーを記録に置き換える (本物を掛けたまま残さない)。"""
    calls = []
    with patch.object(freeze_dump.faulthandler, "dump_traceback_later",
                      side_effect=lambda timeout, **kwargs: calls.append(("later", timeout, kwargs))), \
            patch.object(freeze_dump.faulthandler, "cancel_dump_traceback_later", side_effect=lambda: calls.append(("cancel",))):
        yield calls


def wait_for(predicate, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_a_late_feed_is_dumped_by_a_python_thread_that_holds_the_gil(tmp_path, later) -> None:
    path = tmp_path / "freeze_trace.log"
    with open(path, "a", encoding="utf-8") as file:
        dump = FreezeDump(file, stall_margin=30.0)
        dump.arm(0.05)
        assert wait_for(lambda: "test_freeze_dump.py" in path.read_text(encoding="utf-8", errors="replace"))
        text = path.read_text(encoding="utf-8", errors="replace")
    # The stacks of every thread, written from the dump's own Python thread (it shows itself as current).
    assert text.startswith("Timeout (0s without a feed)!\n")
    assert "Current thread" in text and "freeze_dump.py" in text
    assert "test_freeze_dump.py" in text  # this (main) thread's stack is there too
    # The last-resort timer was armed past the deadline and withdrawn once the Python thread could run.
    assert later[0] == ("later", 30.05, {"repeat": False, "file": file, "exit": False})
    assert later[-1] == ("cancel",)


def test_each_feed_moves_the_deadline_and_nothing_is_written_while_feeds_arrive(tmp_path, later) -> None:
    path = tmp_path / "freeze_trace.log"
    clock = Clock()
    with open(path, "a", encoding="utf-8") as file:
        dump = FreezeDump(file, clock=clock)
        with patch.object(dump, "_write") as write:
            dump.arm(35.0)
            for _ in range(3):
                clock.now += 20.0  # the next feed arrives in time
                dump.arm(35.0)
            time.sleep(0.05)
            write.assert_not_called()
            # No more feeds: once the last deadline passes, one dump is written, and only one.
            clock.now += 36.0
            with dump._changed:
                dump._changed.notify()
            assert wait_for(lambda: write.call_count == 1)
            time.sleep(0.05)
            assert write.call_count == 1
    assert [call[1] for call in later if call[0] == "later"] == [65.0] * 4


def test_cancel_withdraws_both_stages(tmp_path, later) -> None:
    path = tmp_path / "freeze_trace.log"
    clock = Clock()
    with open(path, "a", encoding="utf-8") as file:
        dump = FreezeDump(file, clock=clock)
        with patch.object(dump, "_write") as write:
            dump.arm(35.0)
            dump.cancel()
            clock.now += 1000.0
            with dump._changed:
                dump._changed.notify()
            time.sleep(0.05)
            write.assert_not_called()
    assert later == [("later", 65.0, {"repeat": False, "file": file, "exit": False}), ("cancel",)]
    assert path.read_text() == ""


def test_dumping_while_other_threads_run_does_not_crash(tmp_path) -> None:
    """The case that crashed with dump_traceback_later: stacks read while their threads keep changing them."""
    path = tmp_path / "freeze_trace.log"
    stop = threading.Event()

    def churn(depth: int = 0) -> int:
        # Frames are pushed and popped as fast as possible.
        return depth if depth > 40 or stop.is_set() else churn(depth + 1)

    def busy() -> None:
        while not stop.is_set():
            churn()

    workers = [threading.Thread(target=busy, daemon=True) for _ in range(4)]
    for worker in workers:
        worker.start()
    try:
        with open(path, "a", encoding="utf-8") as file, \
                patch.object(freeze_dump.faulthandler, "dump_traceback_later"), \
                patch.object(freeze_dump.faulthandler, "cancel_dump_traceback_later"):
            dump = FreezeDump(file)
            for _ in range(200):
                dump._write(35.0)
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=5)
    assert path.read_text(encoding="utf-8", errors="replace").count("Timeout (35s without a feed)!") == 200


def test_a_closed_file_never_raises(tmp_path, later) -> None:
    file = open(tmp_path / "freeze_trace.log", "a", encoding="utf-8")
    dump = FreezeDump(file)
    file.close()
    dump._write(35.0)
