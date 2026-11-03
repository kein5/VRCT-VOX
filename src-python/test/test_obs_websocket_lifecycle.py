"""Coupled IPC lifecycle transactions with fake listeners and fake bind results."""

from io import BytesIO
from queue import Queue
from threading import Event, Lock, RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as controller_module
import mainloop as mainloop_module
import model as model_module
from controller import Controller
from mainloop import Main
from model import Model


@pytest.fixture
def services(monkeypatch):
    settings = SimpleNamespace(
        WEBSOCKET_HOST="127.0.0.1", WEBSOCKET_PORT=2231,
        WEBSOCKET_AUTH_TOKEN="test-token", WEBSOCKET_SERVER=False,
        OBS_BROWSER_SOURCE=False, OBS_BROWSER_SOURCE_PORT=2232,
    )
    owner = object.__new__(Model)
    owner._inited = True
    owner._websocket_lifecycle_lock = Lock()
    owner._obs_lifecycle_lock = RLock()
    owner.websocket_server = owner.obs_browser_source_server = None
    state = SimpleNamespace(config=settings, model=owner, ws=[], obs=[],
                            ws_results=[], obs_results=[], before_obs_start=lambda: None)

    class FakeListener:
        def __init__(self, host, port, **kwargs):
            self.host, self.port = host, port
            self.token = kwargs.get("token", kwargs.get("ws_token"))
            self.is_running = False
            self.is_stopped = True
            self.stops = 0

        def stop(self):
            self.stops += 1
            self.is_running, self.is_stopped = False, True

    class FakeWebSocket(FakeListener):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            state.ws.append(self)

        def set_message_handler(self, handler):
            pass

        def begin_start(self, timeout):
            return self

        def wait_started(self, attempt):
            if state.ws_results and not state.ws_results.pop(0):
                raise OSError("fake WebSocket bind failure")
            self.is_running, self.is_stopped = True, False

    class FakeObs(FakeListener):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            state.obs.append(self)

        def start(self):
            state.before_obs_start()
            if state.obs_results and not state.obs_results.pop(0):
                raise OSError("fake OBS bind failure")
            self.is_running, self.is_stopped = True, False

    for module in (controller_module, model_module):
        monkeypatch.setattr(module, "config", settings)
        monkeypatch.setattr(module, "errorLogging", lambda: None)
        monkeypatch.setattr(module, "printLog", lambda *args: None)
    monkeypatch.setattr(controller_module, "model", owner)
    monkeypatch.setattr(controller_module, "isAvailableWebSocketServer", lambda *args: True)
    monkeypatch.setattr(model_module, "WebSocketServer", FakeWebSocket)
    monkeypatch.setattr(model_module, "ObsBrowserSourceServer", FakeObs)
    return state


def assert_consistent(s):
    assert s.config.WEBSOCKET_SERVER == s.model.checkWebSocketServerAlive()
    assert s.config.OBS_BROWSER_SOURCE == s.model.checkObsBrowserSourceServerAlive()
    assert not s.config.OBS_BROWSER_SOURCE or s.config.WEBSOCKET_SERVER


@pytest.mark.parametrize("already_running", [False, True])
@pytest.mark.parametrize("failure", ["preflight", "bind", "exception"])
def test_failed_obs_enable_releases_only_its_own_websocket(services, monkeypatch, already_running, failure):
    s = services
    if already_running:
        assert Controller.setEnableWebSocketServer()["status"] == 200

    def available(host, port):
        if port == s.config.OBS_BROWSER_SOURCE_PORT:
            if failure == "exception":
                raise OSError("fake preflight error")
            return failure != "preflight"
        return True

    monkeypatch.setattr(controller_module, "isAvailableWebSocketServer", available)
    s.obs_results = [False]
    response = Controller.setEnableObsBrowserSource()
    assert response["status"] == 400
    assert response["result"]["data"] is False  # enable's prior value, not the port
    assert response["result"]["error_code"] == (
        "OBS_BROWSER_SOURCE_PORT_UNAVAILABLE" if failure == "preflight"
        else "OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE"
    )
    assert s.config.WEBSOCKET_SERVER is already_running
    assert s.ws[0].stops == (0 if already_running else 1)
    assert_consistent(s)


@pytest.mark.parametrize("host,path,status,has_token", [
    ("127.0.0.1:2232", "/", 403, False),
    ("127.0.0.1:2232", "/obs?token=wrong", 403, False),
    ("127.0.0.1:2232", "/?token=test-token&token=test-token", 403, False),
    ("127.0.0.1:2232", "/?token=test-token", 200, True),
    ("127.0.0.1:2232", "/obs?token=test-token", 200, True),
    ("attacker.example", "/?token=test-token", 403, False),
    ("127.0.0.1:2232", "/health", 200, False),
])
def test_obs_http_token_protection_without_sockets(monkeypatch, host, path, status, has_token):
    """Exercise the real HTTP handler with an in-memory request/response."""
    import models.obs.obs_browser_source_server as obs_module

    http_factory = Mock()
    thread_factory = Mock()
    monkeypatch.setattr(obs_module, "ThreadingHTTPServer", http_factory)
    monkeypatch.setattr(obs_module.threading, "Thread", thread_factory)
    server = obs_module.ObsBrowserSourceServer("127.0.0.1", 2232, ws_token="test-token")
    server.start()  # Both the listener and worker are fakes.
    try:
        handler_class = http_factory.call_args.args[1]
        request = object.__new__(handler_class)
        request.path, request.headers = path, {"Host": host}
        request.wfile = BytesIO()
        request.send_response = Mock()
        headers = {}
        request.send_header = lambda key, value: headers.update({key: value})
        request.end_headers = Mock()
        request.do_GET()
        request.send_response.assert_called_once_with(status)
        body = request.wfile.getvalue()
        assert (b"test-token" in body) is has_token
        if has_token:
            assert body.startswith(b"<!doctype html>")
            assert headers["Referrer-Policy"] == "no-referrer"
            assert "no-store" in headers["Cache-Control"]
        elif status == 403:
            assert b"<html" not in body
        else:
            assert body == b"ok"
    finally:
        thread_factory.return_value.is_alive.return_value = False
        server.stop()


def test_websocket_failure_during_obs_enable_keeps_specific_cause(services):
    s = services
    s.ws_results = [False]
    response = Controller.setEnableObsBrowserSource()
    assert response["status"] == 400
    assert response["result"]["error_code"] == "WEBSOCKET_SERVER_UNAVAILABLE"
    assert response["result"]["data"] is False
    assert not s.obs
    assert_consistent(s)


def test_obs_enable_commits_only_after_both_listeners_are_ready(services):
    s = services
    def before_start():
        assert not s.config.WEBSOCKET_SERVER
        assert not s.config.OBS_BROWSER_SOURCE
    s.before_obs_start = before_start
    assert Controller.setEnableObsBrowserSource() == {"status": 200, "result": True}
    assert s.ws[0].token == s.obs[0].token == s.config.WEBSOCKET_AUTH_TOKEN
    assert_consistent(s)


@pytest.mark.parametrize("ws_restored,obs_restored", [(True, True), (True, False), (False, False)])
def test_host_change_obs_failure_rolls_back_pair_or_disables_failed_restore(services, ws_restored, obs_restored):
    s = services
    assert Controller.setEnableObsBrowserSource()["status"] == 200
    old_host = s.config.WEBSOCKET_HOST
    s.ws_results = [True, ws_restored]
    s.obs_results = [False, obs_restored]
    response = Controller.setWebSocketHost("127.0.0.2")
    assert response["status"] == 400
    assert response["result"]["error_code"] == "OBS_BROWSER_SOURCE_HOST_UNAVAILABLE"
    assert response["result"]["data"] == old_host == s.config.WEBSOCKET_HOST
    assert s.config.WEBSOCKET_SERVER is ws_restored
    assert s.config.OBS_BROWSER_SOURCE is obs_restored
    assert not s.ws[0].is_running and not s.ws[1].is_running
    assert not s.obs[0].is_running and not s.obs[1].is_running
    if ws_restored:
        assert s.model.websocket_server.host == old_host
    if obs_restored:
        assert s.model.obs_browser_source_server.host == old_host
    assert_consistent(s)


def test_host_change_success_moves_both_before_committing_host(services):
    s = services
    assert Controller.setEnableObsBrowserSource()["status"] == 200
    def before_start():
        assert s.config.WEBSOCKET_HOST == "127.0.0.1"
        assert s.model.websocket_server.host == "127.0.0.2"
    s.before_obs_start = before_start
    assert Controller.setWebSocketHost("127.0.0.2") == {"status": 200, "result": "127.0.0.2"}
    assert s.model.obs_browser_source_server.host == "127.0.0.2"
    assert_consistent(s)


@pytest.mark.parametrize("restored", [True, False])
def test_obs_port_rebind_failure_returns_previous_port(services, restored):
    s = services
    assert Controller.setEnableObsBrowserSource()["status"] == 200
    s.obs_results = [False, restored]
    response = Controller.setObsBrowserSourcePort(2233)
    assert response["status"] == 400
    assert response["result"]["error_code"] == "OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE"
    assert response["result"]["data"] == s.config.OBS_BROWSER_SOURCE_PORT == 2232
    assert s.config.OBS_BROWSER_SOURCE is restored
    assert s.config.WEBSOCKET_SERVER
    assert_consistent(s)


@pytest.mark.parametrize("port,code", [("bad", "OBS_BROWSER_SOURCE_PORT_INVALID"), (2233, "OBS_BROWSER_SOURCE_PORT_UNAVAILABLE")])
def test_obs_port_rejection_keeps_existing_listener(services, monkeypatch, port, code):
    s = services
    assert Controller.setEnableObsBrowserSource()["status"] == 200
    monkeypatch.setattr(controller_module, "isAvailableWebSocketServer", lambda *args: False)
    response = Controller.setObsBrowserSourcePort(port)
    assert response["status"] == 400
    assert response["result"]["error_code"] == code
    assert response["result"]["data"] == 2232
    assert s.obs[0].stops == 0
    assert_consistent(s)


LIFECYCLE_ENDPOINTS = {
    "/set/enable/obs_browser_source": Controller.setEnableObsBrowserSource,
    "/set/disable/obs_browser_source": Controller.setDisableObsBrowserSource,
    "/set/enable/websocket_server": Controller.setEnableWebSocketServer,
    "/set/disable/websocket_server": Controller.setDisableWebSocketServer,
    "/set/data/websocket_host": Controller.setWebSocketHost,
    "/set/data/websocket_port": Controller.setWebSocketPort,
    "/set/data/obs_browser_source_port": Controller.setObsBrowserSourcePort,
}


@pytest.mark.parametrize("next_endpoint,obs_succeeds", [
    ("/set/disable/websocket_server", True),
    ("/set/enable/websocket_server", False),
])
def test_ipc_interleaving_serializes_dependency_and_cleanup(services, monkeypatch, next_endpoint, obs_succeeds):
    s = services
    entered, release, waiting = Event(), Event(), Event()
    first_finished, next_entered = Event(), Event()
    responses = Queue()
    main = Main(None, {ep: {"status": True, "variable": fn} for ep, fn in LIFECYCLE_ENDPOINTS.items()}, worker_count=2)
    assert len({main._canonical_lock_key(ep) for ep in LIFECYCLE_ENDPOINTS}) == 1

    def blocked_start():
        entered.set()
        assert release.wait(3), "test did not release OBS startup"
    s.before_obs_start = blocked_start
    s.obs_results = [obs_succeeds]
    def first_handler(data):
        try:
            return Controller.setEnableObsBrowserSource(data)
        finally:
            first_finished.set()

    def next_handler(data):
        next_entered.set()
        assert first_finished.is_set(), "dependent request started before OBS cleanup finished"
        return LIFECYCLE_ENDPOINTS[next_endpoint](data)

    main.mapping["/set/enable/obs_browser_source"]["variable"] = first_handler
    main.mapping[next_endpoint]["variable"] = next_handler
    original_wait = main.queue.not_empty.wait

    def wait(timeout=None):
        # 条件変数のロック下で、後続をキューに残して待つ瞬間を観測する。
        if any(request.endpoint == next_endpoint for request in main.queue.queue):
            waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(main.queue.not_empty, "wait", wait)
    monkeypatch.setattr(mainloop_module, "printLog", lambda *args: None)
    monkeypatch.setattr(mainloop_module, "printResponse", lambda *args: responses.put(args))
    main.startHandler()
    try:
        main.queue.put(("/set/enable/obs_browser_source", None, 0))
        assert entered.wait(2)
        main.queue.put((next_endpoint, None, 0))
        assert waiting.wait(2), "dependent request did not wait in the lifecycle queue"
        assert main._endpoint_locks[main._canonical_lock_key(next_endpoint)].locked()
        assert not next_entered.is_set(), "dependent request bypassed the lifecycle lock"
        assert not first_finished.is_set()
        assert responses.empty()
        release.set()
        results = {ep: (status, result) for status, ep, result in (responses.get(timeout=2), responses.get(timeout=2))}
        assert results[next_endpoint][0] == 200
        assert results["/set/enable/obs_browser_source"][0] == (200 if obs_succeeds else 400)
        assert next_entered.is_set(), "dependent request did not run after the lock was released"
    finally:
        release.set()
        main._stop_event.set()
        for thread in main._threads:
            thread.join(2)
            assert not thread.is_alive()
    assert not s.config.OBS_BROWSER_SOURCE
    assert s.config.WEBSOCKET_SERVER is (not obs_succeeds)
    # A queued independent enable acquires a new listener after failed OBS
    # cleanup; it cannot be stopped later by that failed attempt.
    if not obs_succeeds:
        assert len(s.ws) == 2 and s.ws[0].stops == 1 and s.ws[1].stops == 0
    assert_consistent(s)
