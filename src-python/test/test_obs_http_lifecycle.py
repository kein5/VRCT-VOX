"""Real OBS handlers over memory sockets; no listener or network access."""

from io import BytesIO
from threading import Event
from time import monotonic
from unittest.mock import Mock

import pytest

import models.obs.obs_browser_source_server as obs_module


class StalledRequest:
    def __init__(self, prefix=b"", releasable=True):
        self.prefix = prefix
        self.entered, self.released = Event(), Event()
        self.timeout = None
        self.closed = False
        self.releasable = releasable

    def settimeout(self, timeout):
        self.timeout = timeout

    def makefile(self, *args):
        return self

    def readline(self, *args):
        if self.prefix:
            line, self.prefix = self.prefix, b""
            return line
        self.entered.set()
        assert self.released.wait(4), "test must retire the fake request"
        return b""

    def sendall(self, data):
        pass

    def shutdown(self, how):
        if self.releasable:
            self.released.set()

    def close(self):
        self.closed = True


@pytest.fixture
def server(monkeypatch):
    def fake_init(self, address, handler):
        self.server_address = address
        self.RequestHandlerClass = handler
        self.socket = Mock()

    # Keep production admission, handler, timeout and shutdown code. Only the
    # listener's socket allocation and wait for incoming clients are replaced.
    monkeypatch.setattr(obs_module.ThreadingHTTPServer, "__init__", fake_init)
    owner = obs_module.ObsBrowserSourceServer("127.0.0.1", 2232, ws_token="test-token")
    monkeypatch.setattr(obs_module.ThreadingHTTPServer, "handle_request", lambda self: self._stopping.wait(.01))
    owner.start()
    yield owner
    http = owner._server
    if http:
        for request in list(http._handlers):
            request.released.set()
    owner.stop()


@pytest.mark.parametrize("prefix", [b"", b"GET /obs HTTP/1.1\r\n"])
def test_stop_retires_incomplete_request_lines_and_headers(server, prefix):
    http = server._server
    request = StalledRequest(prefix)
    http.process_request(request, ("127.0.0.1", 1234))
    try:
        assert request.entered.wait(1)
        assert request.timeout is not None and 0 < request.timeout <= 5
        server.stop()
        assert request.released.is_set()
        assert request.closed
        assert server.is_stopped
        assert not http.has_handlers
    finally:
        request.released.set()


def test_handler_admission_is_bounded_and_stop_rejects_new_clients(server):
    http = server._server
    requests = [StalledRequest() for _ in range(17)]
    try:
        for request in requests:
            http.process_request(request, ("127.0.0.1", 1234))
        assert all(request.entered.wait(1) for request in requests[:16])
        assert requests[16].closed
        assert not requests[16].entered.is_set()
        server.stop()
        late = StalledRequest()
        http.process_request(late, ("127.0.0.1", 1234))
        assert late.closed and not late.entered.is_set()
        assert not http.has_handlers
    finally:
        for request in requests:
            request.released.set()


def test_total_request_deadline_closes_clients_even_without_read_timeout(server, monkeypatch):
    http = server._server
    request = StalledRequest()
    http.process_request(request, ("127.0.0.1", 1234))
    try:
        assert request.entered.wait(1)
        future = monotonic() + 6
        monkeypatch.setattr(obs_module, "monotonic", lambda: future)
        http.service_actions()
        assert request.released.is_set()
    finally:
        request.released.set()


def test_stop_retains_owner_if_handler_cannot_exit_within_budget(server, monkeypatch):
    http = server._server
    request = StalledRequest(releasable=False)
    http.process_request(request, ("127.0.0.1", 1234))
    try:
        assert request.entered.wait(1)
        monkeypatch.setattr(obs_module, "_STOP_TIMEOUT", .05)
        started = monotonic()
        server.stop()
        assert monotonic() - started < .5
        assert not server.is_stopped and not server.is_running
        assert server._server is http
        server.start()
        assert server._server is http, "a retiring owner must not be replaced"
    finally:
        request.released.set()
        server.stop()
    assert server.is_stopped


@pytest.mark.parametrize("stage", ["construct", "start"])
def test_thread_start_failure_closes_partial_http_listener(monkeypatch, stage):
    http = Mock(has_handlers=False)
    monkeypatch.setattr(obs_module, "_ObsHTTPServer", Mock(return_value=http))
    thread = Mock(ident=None)
    thread.start.side_effect = RuntimeError("no thread available")
    thread.is_alive.return_value = False
    thread_factory = Mock(return_value=thread)
    if stage == "construct":
        thread_factory.side_effect = RuntimeError("no thread available")
    monkeypatch.setattr(obs_module.threading, "Thread", thread_factory)
    owner = obs_module.ObsBrowserSourceServer("127.0.0.1", 2232)
    with pytest.raises(RuntimeError):
        owner.start()
    http.server_close.assert_called_once()
    assert owner.is_stopped and owner._server is None


def test_completed_http_request_releases_admission_slot(server):
    http = server._server
    request = StalledRequest()
    request.makefile = lambda *args: BytesIO(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
    http.process_request(request, ("127.0.0.1", 1234))
    server.stop()
    assert request.closed
    assert not http.has_handlers
