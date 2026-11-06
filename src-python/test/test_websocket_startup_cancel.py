"""OI-20: real asyncio threads, fake serve/bind; no TCP sockets are opened."""

import asyncio
import selectors
import threading
import time

import pytest

from models.websocket.websocket_server import WebSocketServer


@pytest.fixture(autouse=True)
def timer_woken_loops(monkeypatch):
    """No socket I/O, even for asyncio's cross-thread wakeup in this sandbox."""
    class NoSocketSelector(selectors.SelectSelector):
        # Without the self-pipe nothing is registered, and Windows select() rejects
        # three empty sets (WinError 10022). The loop's 1 ms tick bounds the wait.
        def select(self, timeout=None):
            if self._readers or self._writers:
                return super().select(timeout)
            time.sleep(0.001 if timeout is None else max(0.0, min(timeout, 0.001)))
            return []

    class TimerLoop(asyncio.SelectorEventLoop):
        def __init__(self):
            super().__init__(NoSocketSelector())

        def _make_self_pipe(self):
            pass

        def _close_self_pipe(self):
            pass

        def _write_to_self(self):
            pass

    def new_loop():
        loop = TimerLoop()

        def tick():
            loop.call_later(0.001, tick)

        tick()
        return loop

    monkeypatch.setattr(asyncio, "new_event_loop", new_loop)


class Listener:
    def __init__(self):
        self.listening = False
        self.closed = False
        self.ever_listened = False

    async def start_serving(self):
        self.listening = self.ever_listened = True

    def close(self):
        self.listening = False
        self.closed = True

    async def wait_closed(self):
        assert self.closed


def test_timeout_cancels_slow_serve_before_it_can_listen(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    listener = Listener()

    async def slow_serve(*args, **kwargs):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.001)
        # Match websockets: default serve starts listening before it returns.
        if kwargs.get("start_serving", True):
            await listener.start_serving()
        returned.set()
        return listener

    monkeypatch.setattr("models.websocket.websocket_server.websockets.serve", slow_serve)
    server = WebSocketServer("127.0.0.1", 0, token="test-token")
    try:
        with pytest.raises(TimeoutError):
            server.start(timeout=0.05)
        assert entered.is_set()
        release.set()
        # A cancelled setup must never return a listening server later.
        returned.wait(0.1)
        assert not listener.ever_listened
        assert not server.is_running
    finally:
        release.set()
        server.stop()


class ServeGate:
    """A fake asynchronous bind, optionally returning a resource on cancellation."""
    def __init__(self, mode="immediate"):
        self.mode = mode
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.listener = Listener()
        self.returned = False

    async def serve(self, *args, **kwargs):
        self.entered.set()
        try:
            if self.mode == "blocked_thread":
                # Simulate a synchronous OS/library call that cannot be cancelled.
                assert self.release.wait(3.0), "test did not release bind"
            elif self.mode != "immediate":
                while not self.release.is_set():
                    await asyncio.sleep(0.001)
        except asyncio.CancelledError:
            self.cancelled.set()
            if self.mode != "finish_on_cancel":
                raise
        self.returned = True
        if kwargs.get("start_serving", True):
            await self.listener.start_serving()
        return self.listener


@pytest.fixture
def harness(monkeypatch):
    from types import SimpleNamespace
    import controller as controller_module
    import model as model_module
    from model import Model

    # Do not initialize the app or mutate the shared Model/config singletons.
    model = object.__new__(Model)
    model._inited = True
    model._websocket_lifecycle_lock = threading.Lock()
    model.websocket_server = None
    settings = SimpleNamespace(
        WEBSOCKET_HOST="127.0.0.1", WEBSOCKET_PORT=2231,
        WEBSOCKET_AUTH_TOKEN="test-token", WEBSOCKET_SERVER=False,
        OBS_BROWSER_SOURCE=False, OBS_BROWSER_SOURCE_PORT=2232,
    )
    gates, servers, workers = [], [], []

    def server_factory(*args, **kwargs):
        server = WebSocketServer(*args, **kwargs)
        servers.append(server)
        return server

    async def serve(*args, **kwargs):
        assert gates, "unexpected extra bind"
        gate = gates.pop(0)
        return await gate.serve(*args, **kwargs)

    def background(callback):
        result = []
        worker = threading.Thread(target=lambda: result.append(callback()), daemon=True)
        workers.append(worker)
        worker.start()
        return worker, result

    def finish(worker):
        worker.join(2.0)
        assert not worker.is_alive()

    def add_gate(mode="immediate"):
        gate = ServeGate(mode)
        all_gates.append(gate)
        gates.append(gate)
        return gate

    all_gates = []
    monkeypatch.setattr(model_module, "config", settings)
    monkeypatch.setattr(controller_module, "config", settings)
    monkeypatch.setattr(controller_module, "model", model)
    monkeypatch.setattr(controller_module, "isAvailableWebSocketServer", lambda *a: True)
    monkeypatch.setattr(model_module, "WebSocketServer", server_factory)
    monkeypatch.setattr(model_module, "_WEBSOCKET_START_TIMEOUT", 0.1)
    monkeypatch.setattr("models.websocket.websocket_server.websockets.serve", serve)
    yield SimpleNamespace(
        model=model, config=settings, controller=controller_module.Controller,
        servers=servers, add_gate=add_gate, background=background, finish=finish,
    )
    for gate in all_gates:
        gate.release.set()
    for server in servers:
        server.stop()
    for worker in workers:
        finish(worker)
    for server in servers:
        assert server.is_stopped
        if server._run and server._run.loop:
            assert server._run.loop.is_closed()


def assert_reaped(server):
    assert server.is_stopped
    assert not server.is_running
    assert not server._run.thread.is_alive()
    assert server._run.loop.is_closed()
    assert not asyncio.all_tasks(server._run.loop)


@pytest.mark.parametrize("obs", [False, True])
def test_controller_timeout_reports_failure_and_reaps_attempt(harness, obs):
    from errors import ErrorCode
    h = harness
    gate = h.add_gate("wait")
    enable = h.controller.setEnableObsBrowserSource if obs else h.controller.setEnableWebSocketServer
    response = enable()
    expected = ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE
    assert response["status"] == 400
    assert response["result"]["error_code"] == expected.value
    assert response["result"]["data"] is False
    assert not h.config.WEBSOCKET_SERVER
    assert not h.config.OBS_BROWSER_SOURCE
    assert not h.model.checkWebSocketServerAlive()
    assert gate.entered.is_set() and gate.cancelled.is_set()
    assert not gate.listener.ever_listened
    assert_reaped(h.servers[0])


def test_start_finishing_on_timeout_is_closed_without_listening(harness):
    h = harness
    gate = h.add_gate("finish_on_cancel")
    assert not h.model.startWebSocketServer("127.0.0.1", 0)
    assert gate.cancelled.is_set() and gate.returned
    assert gate.listener.closed
    assert not gate.listener.ever_listened
    assert_reaped(h.servers[0])


def test_enable_immediately_after_timeout_succeeds(harness):
    h = harness
    h.add_gate("finish_on_cancel")
    assert h.controller.setEnableWebSocketServer()["status"] == 400
    first = h.servers[0]
    gate = h.add_gate()
    assert h.controller.setEnableWebSocketServer() == {"status": 200, "result": True}
    assert h.config.WEBSOCKET_SERVER and h.model.checkWebSocketServerAlive()
    assert h.servers[1] is not first
    first.stop()  # A stale cleanup cannot close the replacement.
    assert gate.listener.listening
    assert h.controller.setDisableWebSocketServer() == {"status": 200, "result": False}
    assert gate.listener.closed
    assert_reaped(first)
    assert_reaped(h.servers[1])


@pytest.mark.parametrize("obs", [False, True])
def test_disable_cancels_pending_enable_even_while_config_is_false(harness, obs):
    h = harness
    gate = h.add_gate("wait")
    enable = h.controller.setEnableObsBrowserSource if obs else h.controller.setEnableWebSocketServer
    worker, responses = h.background(enable)
    assert gate.entered.wait(1.0)
    assert not h.config.WEBSOCKET_SERVER
    assert h.controller.setDisableWebSocketServer() == {"status": 200, "result": False}
    h.finish(worker)
    assert responses[0]["status"] == 400
    assert not h.config.WEBSOCKET_SERVER
    assert not h.config.OBS_BROWSER_SOURCE
    assert not gate.listener.ever_listened
    assert_reaped(h.servers[0])


@pytest.mark.parametrize("setting,value", [("Host", "127.0.0.1"), ("Port", 2233)])
def test_address_change_cancels_pending_old_bind(harness, setting, value):
    h = harness
    gate = h.add_gate("wait")
    worker, responses = h.background(h.controller.setEnableWebSocketServer)
    assert gate.entered.wait(1.0)
    response = getattr(h.controller, "setWebSocket" + setting)(value)
    h.finish(worker)
    assert response == {"status": 200, "result": value}
    assert responses[0]["status"] == 400
    assert not h.config.WEBSOCKET_SERVER
    assert not gate.listener.ever_listened
    h.add_gate()
    assert h.controller.setEnableWebSocketServer()["status"] == 200
    assert getattr(h.model.websocket_server, setting.lower()) == value


@pytest.mark.parametrize("setting,value,error", [
    ("Port", 2233, "WEBSOCKET_PORT_UNAVAILABLE"),
    ("Host", "127.0.0.2", "WEBSOCKET_HOST_INVALID"),  # fake bind only
])
def test_address_change_timeout_restores_previous_listener(harness, setting, value, error):
    h = harness
    first = h.add_gate()
    assert h.controller.setEnableWebSocketServer()["status"] == 200
    late = h.add_gate("finish_on_cancel")
    restored = h.add_gate()
    response = getattr(h.controller, "setWebSocket" + setting)(value)
    assert response["status"] == 400
    assert response["result"]["error_code"] == error
    assert getattr(h.config, "WEBSOCKET_" + setting.upper()) != value
    assert first.listener.closed and late.listener.closed
    assert not late.listener.ever_listened
    assert restored.listener.listening
    assert h.config.WEBSOCKET_SERVER and h.model.checkWebSocketServerAlive()
    assert_reaped(h.servers[0])
    assert_reaped(h.servers[1])


def test_concurrent_starts_share_one_attempt(harness):
    h = harness
    gate = h.add_gate("wait")
    worker1, result1 = h.background(lambda: h.model.startWebSocketServer("127.0.0.1", 0))
    assert gate.entered.wait(1.0)
    worker2, result2 = h.background(lambda: h.model.startWebSocketServer("127.0.0.1", 0))
    gate.release.set()
    h.finish(worker1)
    h.finish(worker2)
    assert result1 == result2 == [True]
    assert len(h.servers) == 1
    assert h.model.checkWebSocketServerAlive()


def test_stuck_bind_stays_owned_until_cleanup_and_never_listens_late(harness, monkeypatch):
    h = harness
    monkeypatch.setattr("models.websocket.websocket_server._STOP_JOIN_TIMEOUT", 0.02)
    gate = h.add_gate("blocked_thread")
    assert h.controller.setEnableWebSocketServer()["status"] == 400
    first = h.servers[0]
    h.model.logger = None
    logs = []
    monkeypatch.setattr("model.printLog", logs.append)
    h.model.stopWebSocketServer()
    assert logs == ["WebSocket server thread did not terminate properly"]
    assert not first.is_stopped
    assert h.model.websocket_server is first
    assert not h.model.checkWebSocketServerAlive()
    # A bounded join cannot kill a synchronous call. Retain its reference and
    # refuse a competing bind until the old thread has closed its resources.
    assert h.controller.setEnableWebSocketServer()["status"] == 400
    assert len(h.servers) == 1
    gate.release.set()
    first._run.thread.join(1.0)
    assert gate.listener.closed and not gate.listener.ever_listened
    assert_reaped(first)
    h.add_gate()
    assert h.controller.setEnableWebSocketServer()["status"] == 200


def test_stop_before_loop_creation_closes_late_loop(harness, monkeypatch):
    h = harness
    entered, release = threading.Event(), threading.Event()
    original = asyncio.new_event_loop

    def delayed_loop():
        entered.set()
        assert release.wait(3.0)
        return original()

    monkeypatch.setattr(asyncio, "new_event_loop", delayed_loop)
    monkeypatch.setattr("models.websocket.websocket_server._STOP_JOIN_TIMEOUT", 0.02)
    worker, responses = h.background(h.controller.setEnableWebSocketServer)
    try:
        assert entered.wait(1.0)
        h.controller.setDisableWebSocketServer()
    finally:
        release.set()
    h.finish(worker)
    h.servers[0]._run.thread.join(1.0)
    assert responses[0]["status"] == 400
    assert_reaped(h.servers[0])


def test_loop_creation_failure_reports_failure_and_can_retry(harness, monkeypatch):
    h = harness
    with monkeypatch.context() as m:
        m.setattr(asyncio, "new_event_loop", lambda: (_ for _ in ()).throw(OSError("no loop")))
        assert h.controller.setEnableWebSocketServer()["status"] == 400
    assert h.servers[0].is_stopped
    h.add_gate()
    assert h.controller.setEnableWebSocketServer()["status"] == 200


def test_production_six_second_budget_cancels_start(harness, monkeypatch):
    h = harness
    monkeypatch.setattr("model._WEBSOCKET_START_TIMEOUT", 6.0)
    gate = h.add_gate("wait")
    assert h.controller.setEnableWebSocketServer()["status"] == 400
    assert gate.cancelled.is_set()
    assert not gate.listener.ever_listened
    assert_reaped(h.servers[0])


def test_listen_failure_closes_partially_created_server(harness, monkeypatch):
    h = harness
    gate = h.add_gate()

    async def fail_listen():
        raise OSError("listen failed")

    monkeypatch.setattr(gate.listener, "start_serving", fail_listen)
    assert h.controller.setEnableWebSocketServer()["status"] == 400
    assert gate.listener.closed
    assert_reaped(h.servers[0])


def test_thread_start_failure_can_retry(harness, monkeypatch):
    h = harness

    def fail_start(self):
        raise RuntimeError("cannot start thread")

    with monkeypatch.context() as m:
        m.setattr(threading.Thread, "start", fail_start)
        assert h.controller.setEnableWebSocketServer()["status"] == 400
        h.model.stopWebSocketServer()
    h.add_gate()
    assert h.controller.setEnableWebSocketServer()["status"] == 200


def test_old_waiter_cannot_clear_replacement_after_timeout(harness, monkeypatch):
    h = harness
    failed, release = threading.Event(), threading.Event()
    original = WebSocketServer.wait_started

    def delayed_failure(server, run):
        try:
            original(server, run)
        except TimeoutError:
            failed.set()
            assert release.wait(2.0)
            raise

    monkeypatch.setattr(WebSocketServer, "wait_started", delayed_failure)
    h.add_gate("wait")
    worker, results = h.background(lambda: h.model.startWebSocketServer("127.0.0.1", 0))
    try:
        assert failed.wait(1.0)
        assert_reaped(h.servers[0])
        gate = h.add_gate()
        assert h.model.startWebSocketServer("127.0.0.1", 0)
        replacement = h.model.websocket_server
    finally:
        release.set()
    h.finish(worker)
    assert results == [False]
    assert h.model.websocket_server is replacement
    assert h.model.checkWebSocketServerAlive() and gate.listener.listening
