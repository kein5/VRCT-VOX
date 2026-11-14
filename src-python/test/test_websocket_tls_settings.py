"""SEC-01 settings: a LAN host needs a usable certificate, the pair is checked before it is
saved, an old LAN host goes back to this PC at startup, and the token can be replaced.

The servers are mocked here; test_websocket_tls.py runs them for real.
"""
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

import controller as controller_module
import model as model_module
import utils
from config import config
from controller import Controller
from errors import ErrorCode
from tls_certs import make_certificate

LAN = "192.168.1.5"


@pytest.fixture(autouse=True)
def saved_network_settings():
    keys = ("WEBSOCKET_HOST", "WEBSOCKET_SERVER", "OBS_BROWSER_SOURCE", "WEBSOCKET_AUTH_TOKEN",
            "WEBSOCKET_TLS_CERT_FILE", "WEBSOCKET_TLS_KEY_FILE")
    saved = {key: getattr(config, key) for key in keys}
    config.WEBSOCKET_HOST = "127.0.0.1"
    config.WEBSOCKET_SERVER = False
    config.OBS_BROWSER_SOURCE = False
    config.WEBSOCKET_TLS_CERT_FILE = ""
    config.WEBSOCKET_TLS_KEY_FILE = ""
    yield
    for key, value in saved.items():
        setattr(config, key, value)


@pytest.fixture
def backend(monkeypatch):
    fake = Mock()
    fake.checkWebSocketServerAlive.return_value = False
    fake.startWebSocketServer.return_value = True
    fake.startObsBrowserSourceServer.return_value = True
    monkeypatch.setattr(controller_module, "model", fake)
    monkeypatch.setattr(controller_module, "isAvailableWebSocketServer", Mock(return_value=True))
    return fake


@pytest.fixture
def certificate(tmp_path):
    return make_certificate(tmp_path, ip=LAN)


def _error(response):
    assert response["status"] == 400, response
    return response["result"]["error_code"], response["result"]["data"]


def _use_certificate(files):
    config.WEBSOCKET_TLS_CERT_FILE, config.WEBSOCKET_TLS_KEY_FILE = files


# --- The host ------------------------------------------------------------------------

def test_a_lan_host_without_a_certificate_is_refused_before_anything_stops(backend):
    config.WEBSOCKET_SERVER = True
    backend.checkWebSocketServerAlive.return_value = True
    assert _error(Controller.setWebSocketHost(LAN)) == (ErrorCode.WEBSOCKET_HOST_NEEDS_TLS.value, "127.0.0.1")
    assert config.WEBSOCKET_HOST == "127.0.0.1"
    backend.stopWebSocketServer.assert_not_called()
    backend.startWebSocketServer.assert_not_called()


def test_a_lan_host_with_a_broken_certificate_is_refused(backend, tmp_path):
    broken = tmp_path / "broken.pem"
    broken.write_text("not a certificate")
    _use_certificate((str(broken), str(broken)))
    assert _error(Controller.setWebSocketHost(LAN))[0] == ErrorCode.WEBSOCKET_HOST_NEEDS_TLS.value
    assert config.WEBSOCKET_HOST == "127.0.0.1"


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2"])
def test_loopback_hosts_need_no_certificate(backend, host):
    assert Controller.setWebSocketHost(host) == {"status": 200, "result": host}


def test_a_lan_host_with_a_certificate_moves_both_running_servers(backend, certificate):
    _use_certificate(certificate)
    config.WEBSOCKET_SERVER = config.OBS_BROWSER_SOURCE = True
    backend.checkWebSocketServerAlive.return_value = True
    assert Controller.setWebSocketHost(LAN) == {"status": 200, "result": LAN}
    backend.startWebSocketServer.assert_called_with(LAN, config.WEBSOCKET_PORT)
    backend.startObsBrowserSourceServer.assert_called_with(LAN, int(config.OBS_BROWSER_SOURCE_PORT))
    assert config.WEBSOCKET_HOST == LAN


# --- The certificate and key ---------------------------------------------------------

@pytest.mark.parametrize("data", [
    None, "a.pem", ["a.pem", "b.pem"], {}, {"cert_file": "a.pem"},
    {"cert_file": "a.pem", "key_file": None}, {"cert_file": 1, "key_file": 2},
    {"cert_file": "", "key_file": "", "extra": ""},
])
def test_malformed_requests_are_refused(backend, data):
    assert _error(Controller.setWebSocketTls(data)) == (
        ErrorCode.WEBSOCKET_TLS_INVALID.value, {"cert_file": "", "key_file": ""})


def test_only_one_of_the_pair_is_refused(backend, certificate):
    for data in ({"cert_file": certificate[0], "key_file": ""}, {"cert_file": "", "key_file": certificate[1]}):
        assert _error(Controller.setWebSocketTls(data))[0] == ErrorCode.WEBSOCKET_TLS_INVALID.value
    assert (config.WEBSOCKET_TLS_CERT_FILE, config.WEBSOCKET_TLS_KEY_FILE) == ("", "")


def test_a_pair_that_does_not_load_is_not_saved(backend, certificate, tmp_path, monkeypatch):
    other = make_certificate(tmp_path, name="other")
    logged = []
    monkeypatch.setattr(controller_module, "printLog", lambda *args: logged.append(args))
    response = Controller.setWebSocketTls({"cert_file": certificate[0], "key_file": other[1]})
    assert _error(response)[0] == ErrorCode.WEBSOCKET_TLS_INVALID.value
    assert (config.WEBSOCKET_TLS_CERT_FILE, config.WEBSOCKET_TLS_KEY_FILE) == ("", "")
    # The log says why without naming the files.
    assert logged and str(tmp_path) not in repr(logged)


def test_a_working_pair_is_saved_trimmed(backend, certificate):
    response = Controller.setWebSocketTls({"cert_file": f"  {certificate[0]} ", "key_file": certificate[1]})
    assert response == {"status": 200, "result": {"cert_file": certificate[0], "key_file": certificate[1]}}
    assert Controller.getWebSocketTls()["result"] == response["result"]
    # On loopback nothing restarts: the certificate is only for a LAN host.
    backend.stopWebSocketServer.assert_not_called()


def test_the_pair_can_be_cleared_on_loopback_but_not_while_listening_beyond_this_pc(backend, certificate):
    _use_certificate(certificate)
    config.WEBSOCKET_HOST = LAN
    empty = {"cert_file": "", "key_file": ""}
    assert _error(Controller.setWebSocketTls(empty)) == (
        ErrorCode.WEBSOCKET_HOST_NEEDS_TLS.value, {"cert_file": certificate[0], "key_file": certificate[1]})
    config.WEBSOCKET_HOST = "127.0.0.1"
    assert Controller.setWebSocketTls(empty) == {"status": 200, "result": empty}


def test_a_new_pair_restarts_servers_listening_beyond_this_pc(backend, certificate, tmp_path):
    _use_certificate(certificate)
    config.WEBSOCKET_HOST = LAN
    config.WEBSOCKET_SERVER = config.OBS_BROWSER_SOURCE = True
    backend.checkWebSocketServerAlive.return_value = True
    renewed = make_certificate(tmp_path, ip=LAN, name="renewed")
    response = Controller.setWebSocketTls({"cert_file": renewed[0], "key_file": renewed[1]})
    assert response["status"] == 200
    backend.startWebSocketServer.assert_called_once_with(LAN, config.WEBSOCKET_PORT, tls_files=renewed)
    backend.startObsBrowserSourceServer.assert_called_once_with(
        LAN, int(config.OBS_BROWSER_SOURCE_PORT), tls_files=renewed)
    assert (config.WEBSOCKET_TLS_CERT_FILE, config.WEBSOCKET_TLS_KEY_FILE) == renewed


def test_a_failed_restart_goes_back_to_the_old_pair(backend, certificate, tmp_path):
    _use_certificate(certificate)
    config.WEBSOCKET_HOST = LAN
    config.WEBSOCKET_SERVER = True
    backend.checkWebSocketServerAlive.return_value = True
    backend.startWebSocketServer.side_effect = [False, True]
    renewed = make_certificate(tmp_path, ip=LAN, name="renewed")
    response = Controller.setWebSocketTls({"cert_file": renewed[0], "key_file": renewed[1]})
    assert _error(response)[0] == ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE.value
    assert (config.WEBSOCKET_TLS_CERT_FILE, config.WEBSOCKET_TLS_KEY_FILE) == certificate
    # The second start is the restore, with the saved (old) pair.
    assert backend.startWebSocketServer.call_args_list[-1] == call(LAN, config.WEBSOCKET_PORT)


# --- Startup -------------------------------------------------------------------------

def test_a_lan_host_saved_without_a_certificate_goes_back_to_this_pc(backend):
    config.WEBSOCKET_HOST = LAN
    assert Controller._resetWebSocketHostWithoutTls() is True
    assert config.WEBSOCKET_HOST == "127.0.0.1"


def test_a_lan_host_with_a_working_certificate_stays(backend, certificate):
    _use_certificate(certificate)
    config.WEBSOCKET_HOST = LAN
    assert Controller._resetWebSocketHostWithoutTls() is False
    assert config.WEBSOCKET_HOST == LAN


def test_a_loopback_host_stays(backend):
    assert Controller._resetWebSocketHostWithoutTls() is False


# --- The model refuses plain listeners beyond this PC ----------------------------------

def _model(monkeypatch):
    owner = object.__new__(model_module.Model)
    owner.ensure_initialized = Mock()
    owner._websocket_lifecycle_lock = Lock()
    owner._obs_lifecycle_lock = Lock()
    owner.websocket_server = None
    owner.obs_browser_source_server = None
    monkeypatch.setattr(model_module, "WebSocketServer", Mock(side_effect=AssertionError("plain listener opened")))
    monkeypatch.setattr(model_module, "ObsBrowserSourceServer", Mock(side_effect=AssertionError("plain listener opened")))
    return owner


def test_the_model_never_opens_a_plain_listener_on_a_lan_address(monkeypatch):
    owner = _model(monkeypatch)
    assert owner.startWebSocketServer(LAN, 2231) is False
    assert owner.startObsBrowserSourceServer(LAN, 2232) is False
    assert owner.websocket_server is None and owner.obs_browser_source_server is None


def test_the_model_gives_lan_listeners_the_certificate(monkeypatch, certificate):
    owner = _model(monkeypatch)
    _use_certificate(certificate)
    websocket = Mock(is_running=True, is_stopped=False)
    factory = Mock(return_value=websocket)
    monkeypatch.setattr(model_module, "WebSocketServer", factory)
    assert owner.startWebSocketServer(LAN, 2231)
    assert factory.call_args.kwargs["ssl_context"] is not None
    factory.reset_mock()
    owner.websocket_server = None
    assert owner.startWebSocketServer("127.0.0.1", 2231)
    assert factory.call_args.kwargs["ssl_context"] is None


# --- Replacing the token -------------------------------------------------------------

def test_a_new_token_reaches_both_servers_and_stays_out_of_the_log(backend, monkeypatch):
    old = config.WEBSOCKET_AUTH_TOKEN
    response = Controller.regenerateWebSocketAuthToken()
    token = response["result"]
    assert response["status"] == 200 and token != old and len(token) >= 40
    assert config.WEBSOCKET_AUTH_TOKEN == token
    backend.setWebSocketAuthToken.assert_called_once_with(token)

    logger = Mock()
    monkeypatch.setattr(utils, "process_logger", logger)
    monkeypatch.setattr(utils, "_enqueueLogLine", Mock())
    utils.printResponse(200, "/run/regenerate_websocket_auth_token", token)
    assert token not in repr(logger.info.call_args_list)


def test_each_new_token_is_different(backend):
    tokens = {Controller.regenerateWebSocketAuthToken()["result"] for _ in range(5)}
    assert len(tokens) == 5


def test_the_model_hands_the_token_to_both_servers(monkeypatch):
    owner = _model(monkeypatch)
    owner.websocket_server = SimpleNamespace(set_token=Mock())
    owner.obs_browser_source_server = SimpleNamespace(set_token=Mock())
    owner.setWebSocketAuthToken("tok-new")
    owner.websocket_server.set_token.assert_called_once_with("tok-new")
    owner.obs_browser_source_server.set_token.assert_called_once_with("tok-new")
