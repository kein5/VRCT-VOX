"""Production queue/lock grouping under a controlled, thread-free interleaving."""
import ast
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest


@pytest.fixture
def dispatcher():
    # Execute the actual queue and Main classes without importing the runtime's
    # Controller singleton, devices, sockets, watchdog or background workers.
    source = Path(__file__).resolve().parents[1] / "mainloop.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    constants = {
        "DEFAULT_WORKER_COUNT", "_LOCK_BUSY_RETRY_INTERVAL_SEC", "_LOCK_BUSY_MAX_RETRIES",
        "_ENDPOINT_LOCKED_RETRY_INTERVAL_SEC", "_ENDPOINT_LOCKED_MAX_RETRIES",
    }
    nodes = [node for node in tree.body if (
        isinstance(node, ast.ClassDef) and node.name in {"_PendingRequest", "_EndpointQueue", "Main"}
    ) or (
        isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constants for target in node.targets
        )
    )]
    clock = SimpleNamespace(now=1.0)
    namespace = {
        "dataclass": dataclass, "Queue": Queue, "Empty": Empty, "Event": Event, "Lock": Lock,
        "Any": Any, "Controller": object, "time": SimpleNamespace(monotonic=lambda: clock.now),
        "errorLogging": Mock(),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    calls = []
    state = SimpleNamespace(typing=False)

    def typing(value):
        def handle(_):
            state.typing = value
            calls.append(value)
            return {"status": 200, "result": True}
        return handle

    mapping = {
        "/run/typing_message_box": {"status": True, "variable": typing(True)},
        "/run/stop_typing_message_box": {"status": True, "variable": typing(False)},
        "/independent": {"status": True, "variable": lambda _: {"status": 200}},
    }
    main = namespace["Main"](object(), mapping)
    return SimpleNamespace(main=main, calls=calls, state=state, clock=clock)


def complete(main, reserved):
    request, lock, busy = reserved
    assert not busy
    try:
        result = main._call_handler(request.endpoint, request.data)
        assert result[1] == 200
    finally:
        main.queue.finish(request, lock)


def test_stop_cannot_overtake_a_dequeued_start_before_its_handler_runs(dispatcher):
    main = dispatcher.main
    main.queue.put(("/run/typing_message_box", None, 0))
    first = main.queue.get_ready(timeout=0)  # Worker A is preempted here.
    main.queue.put(("/run/stop_typing_message_box", None, 0))
    # Worker B must not run STOP while A has not entered the controller yet.
    with pytest.raises(Empty):
        main.queue.get_ready(timeout=0)
    main.queue.put(("/independent", None, 0))
    independent = main.queue.get_ready(timeout=0)
    assert independent[0].endpoint == "/independent"
    complete(main, independent)
    assert dispatcher.calls == []
    complete(main, first)
    assert dispatcher.state.typing is True
    complete(main, main.queue.get_ready(timeout=0))
    assert dispatcher.calls == [True, False]
    assert dispatcher.state.typing is False
    assert main.queue.unfinished_tasks == 0


def test_multiple_typing_intents_keep_fifo_during_initialization_retry(dispatcher):
    main = dispatcher.main
    main.mapping["/run/typing_message_box"]["status"] = False
    for endpoint in ["/run/typing_message_box", "/run/stop_typing_message_box"] * 2:
        main.queue.put((endpoint, None, 0))
    request, lock, busy = main.queue.get_ready(timeout=0)
    assert not busy
    assert main._call_handler(request.endpoint, request.data)[1] == 423
    main.queue.finish(request, lock, retry=True)
    with pytest.raises(Empty):
        main.queue.get_ready(timeout=0)
    main.mapping["/run/typing_message_box"]["status"] = True
    dispatcher.clock.now += 1
    for _ in range(4):
        complete(main, main.queue.get_ready(timeout=0))
    assert dispatcher.calls == [True, False, True, False]
    assert dispatcher.state.typing is False
    assert main.queue.unfinished_tasks == 0
