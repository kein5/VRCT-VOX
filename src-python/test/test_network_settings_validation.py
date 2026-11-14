"""Saved values and IPC transactions, with no real listeners or devices."""

import ipaddress
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import quote

import pytest

import config as config_module
import controller as controller_module
import model as model_module
from config import Config
from controller import Controller
from models.obs.obs_browser_source_server import _build_overlay_html
from models.websocket.websocket_server import WebSocketServer
from utils import isValidPort, isValidWebSocketHost, isAvailableWebSocketServer


PORTS = [0, 1, 65535, 65536, -1, True, 1.0, "80", "8x", None]
OBS_NUMERIC = [
    ("MAX_MESSAGES", "MaxMessages", "maxMessages", 1, 50),
    ("DISPLAY_DURATION", "DisplayDuration", "displayDuration", 1, 120),
    ("FADEOUT_DURATION", "FadeoutDuration", "fadeoutDuration", 0, 120),
    ("FONT_SIZE", "FontSize", "fontSize", 10, 200),
    ("FONT_OUTLINE_THICKNESS", "FontOutlineThickness", "outlineThickness", 0, 20),
]
SETTINGS = [
    ("OSC_PORT", "setOscPort", 9000, "VALIDATION_OSC_PORT_INVALID"),
    ("WEBSOCKET_PORT", "setWebSocketPort", 2231, "WEBSOCKET_PORT_INVALID"),
    ("OBS_BROWSER_SOURCE_PORT", "setObsBrowserSourcePort", 2232, "OBS_BROWSER_SOURCE_PORT_INVALID"),
]


def finish(coro):
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("unexpected asynchronous wait")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "getComputeDeviceList", lambda: [{"device": "cpu", "compute_types": ["auto"]}])
    monkeypatch.setattr(config_module, "device_manager", None)
    monkeypatch.setattr(config_module, "errorLogging", Mock())
    instance = object.__new__(Config)
    instance.init_config()
    instance._PATH_CONFIG = str(tmp_path / "config.json")
    # load_config still performs its real final atomic save; descriptors don't
    # need background debounce threads in this deterministic fixture.
    monkeypatch.setattr(instance, "saveConfig", Mock())
    monkeypatch.setattr(controller_module, "config", instance)
    monkeypatch.setattr(controller_module, "model", Mock())
    monkeypatch.setattr(controller_module, "isAvailableWebSocketServer", Mock(return_value=True))
    return instance


def call_setter(setter, value):
    target = Controller
    if setter == "setOscPort":
        # The OSC setter publishes OSCQuery readiness through the instance;
        # that path has its own tests.
        target = object.__new__(Controller)
        target._publishOscQueryReadiness = lambda: None
    return getattr(target, setter)(value)


def load(settings, values):
    with open(settings.PATH_CONFIG, "w", encoding="utf-8") as stream:
        json.dump(values, stream)
    settings.load_config()
    with open(settings.PATH_CONFIG, encoding="utf-8") as stream:
        return json.load(stream)


@pytest.mark.parametrize("suffix,method,wire,minimum,maximum", OBS_NUMERIC)
def test_obs_numeric_rejects_invalid_values_without_saving_or_publishing(settings, suffix, method, wire, minimum, maximum):
    key = f"OBS_BROWSER_SOURCE_{suffix}"
    previous = getattr(settings, key)
    target = object.__new__(Controller)
    target._pushObsBrowserSourceSettings = Mock()
    for value in [minimum - 1, maximum + 1, str(maximum + 1), True, 1.5, "1.5", "", None]:
        response = getattr(target, f"setObsBrowserSource{method}")(value)
        assert response["status"] == 400, value
        assert response["result"]["data"] == previous
        assert response["result"]["error_code"] == f"{key}_INVALID"
        assert getattr(settings, key) == previous
    settings.saveConfig.assert_not_called()
    target._pushObsBrowserSourceSettings.assert_not_called()


@pytest.mark.parametrize("suffix,method,wire,minimum,maximum", OBS_NUMERIC)
def test_obs_numeric_saved_live_and_reloaded_values_agree(settings, monkeypatch, suffix, method, wire, minimum, maximum):
    from models.obs import obs_browser_source_server as obs_module

    monkeypatch.setattr(obs_module, "config", settings)
    key = f"OBS_BROWSER_SOURCE_{suffix}"
    settings.OBS_BROWSER_SOURCE = True
    controller_module.model.checkWebSocketServerAlive.return_value = True
    target = object.__new__(Controller)
    for value in [minimum, str(maximum)]:
        response = getattr(target, f"setObsBrowserSource{method}")(value)
        assert response == {"status": 200, "result": int(value)}
        pushed = controller_module.model.websocketSendMessage.call_args.args[0]["settings"]
        assert pushed[wire] == int(value)
        saved = load(settings, {key: int(value)})
        assert saved[key] == getattr(settings, key) == int(value)
        html = obs_module._build_overlay_html()
        fragments = {
            "maxMessages": f"maxMessages: {value}",
            "displayDuration": f"--display-duration: {value}s",
            "fadeoutDuration": f"--fadeout-duration: {value}s",
            "fontSize": f"--font-size: {value}px",
            "outlineThickness": f"--outline-size: {value}px",
        }
        assert fragments[wire] in html


@pytest.mark.parametrize("suffix,method,wire,minimum,maximum", OBS_NUMERIC)
def test_obs_numeric_invalid_saved_values_fall_back_on_load(settings, suffix, method, wire, minimum, maximum):
    key = f"OBS_BROWSER_SOURCE_{suffix}"
    previous = getattr(settings, key)
    for value in [minimum - 1, maximum + 1, True, None, 1.5]:
        saved = load(settings, {key: value})
        assert saved[key] == getattr(settings, key) == previous


def test_obs_numeric_live_page_enforces_the_initialization_ranges(settings, monkeypatch):
    import shutil
    import subprocess
    from pathlib import Path
    from models.obs import obs_browser_source_server as obs_module

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the generated OBS page")
    monkeypatch.setattr(obs_module, "config", settings)
    result = subprocess.run(
        [node, str(Path(__file__).with_name("obs_numeric_settings.mjs"))],
        input=obs_module._build_overlay_html(), text=True, capture_output=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("value", PORTS)
@pytest.mark.parametrize("key,setter,default,error", SETTINGS)
def test_ports_validate_on_load_and_persist_safe_default(settings, value, key, setter, default, error):
    accepted = type(value) is int and 1 <= value <= 65535
    assert isValidPort(value) is accepted
    saved = load(settings, {key: value})
    assert getattr(settings, key) == (value if accepted else default)
    assert saved[key] == (value if accepted else default)


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("value", PORTS)
@pytest.mark.parametrize("key,setter,default,error", SETTINGS)
def test_port_setters_validate_before_any_service_or_save(settings, value, running, key, setter, default, error):
    services = controller_module.model
    services.checkWebSocketServerAlive.return_value = running
    services.checkObsBrowserSourceServerAlive.return_value = running
    services.startWebSocketServer.return_value = True
    services.startObsBrowserSourceServer.return_value = True
    response = call_setter(setter, value)
    accepted = isValidPort(value)
    assert response["status"] == (200 if accepted else 400)
    assert getattr(settings, key) == (value if accepted else default)
    if not accepted:
        assert response["result"]["error_code"] == error
        assert response["result"]["data"] == default
        assert services.mock_calls == []
        settings.saveConfig.assert_not_called()
        controller_module.isAvailableWebSocketServer.assert_not_called()


@pytest.mark.parametrize("obs", [False, True])
def test_failed_port_restart_restores_old_service_without_saving(settings, obs):
    services = controller_module.model
    settings._WEBSOCKET_SERVER = True
    settings._OBS_BROWSER_SOURCE = obs
    start = services.startObsBrowserSourceServer if obs else services.startWebSocketServer
    start.side_effect = [False, True]
    services.checkWebSocketServerAlive.return_value = True
    services.checkObsBrowserSourceServerAlive.return_value = True
    key, setter, default, _ = SETTINGS[2 if obs else 1]
    response = getattr(Controller, setter)(3333)
    assert response["status"] == 400
    assert getattr(settings, key) == default
    assert start.call_args_list[-1].args == (settings.WEBSOCKET_HOST, default)
    settings.saveConfig.assert_not_called()
    assert settings.WEBSOCKET_SERVER
    assert settings.OBS_BROWSER_SOURCE is obs


@pytest.mark.parametrize("token", [None, "", "   ", 123, False, [], {}])
def test_invalid_saved_token_regenerates_persists_and_rejects_tokenless(settings, token):
    default = settings.WEBSOCKET_AUTH_TOKEN
    saved = load(settings, {"WEBSOCKET_AUTH_TOKEN": token})
    assert saved["WEBSOCKET_AUTH_TOKEN"] == default
    assert isinstance(default, str) and len(default) >= 32
    assert Controller.getWebSocketAuthToken()["result"] == default
    server = WebSocketServer(token=default)
    client = SimpleNamespace(respond=lambda status, text: status)
    assert finish(server._process_request(client, SimpleNamespace(path="/"))) == 403
    assert finish(server._process_request(client, SimpleNamespace(path="/?token=" + quote(default)))) is None
    assert f'wsToken: "{default}"' in _build_overlay_html(ws_token=default)
    # A repaired config keeps the same secret across subsequent launches.
    settings._WEBSOCKET_AUTH_TOKEN = "another-generated-default"
    settings.load_config()
    assert settings.WEBSOCKET_AUTH_TOKEN == default


@pytest.mark.parametrize("token", [None, "", "   ", 123, False, [], {}])
def test_production_start_refuses_missing_secret_before_creating_thread(token, monkeypatch):
    thread = Mock()
    monkeypatch.setattr("models.websocket.websocket_server.threading.Thread", thread)
    server = WebSocketServer(token=token)
    with pytest.raises(ValueError, match="token is required"):
        server.begin_start()
    thread.assert_not_called()
    client = SimpleNamespace(respond=lambda status, text: status)
    assert finish(server._process_request(client, SimpleNamespace(path="/"))) == 403


@pytest.mark.parametrize("host,valid", [
    ("127.0.0.1", True), ("192.168.1.5", True), ("::1", False),
    ("2001:db8::1", False), ("::ffff:127.0.0.1", False),
    ("0.0.0.0", False), ("::", False), ("localhost", False),
    ("nonsense", False), (None, False), (2130706433, False),
])
def test_host_load_and_setter_use_the_same_ipv4_contract(settings, host, valid):
    assert isValidWebSocketHost(host) is valid
    saved = load(settings, {"WEBSOCKET_HOST": host})
    expected = host if valid else "127.0.0.1"
    assert settings.WEBSOCKET_HOST == saved["WEBSOCKET_HOST"] == expected
    settings.saveConfig.reset_mock()
    services = controller_module.model
    services.checkWebSocketServerAlive.return_value = False
    response = Controller.setWebSocketHost(host)
    # Load and setter share the address format. A LAN address also needs a certificate
    # (SEC-01); without one the setter refuses it and keeps the services as they are.
    needs_tls = valid and not ipaddress.IPv4Address(host).is_loopback
    assert response["status"] == (200 if valid and not needs_tls else 400)
    assert settings.WEBSOCKET_HOST == expected
    if needs_tls:
        assert response["result"]["error_code"] == "WEBSOCKET_HOST_NEEDS_TLS"
        assert services.mock_calls == []
    if not valid:
        assert response["result"]["error_code"] == "VALIDATION_INVALID_IP"
        assert services.mock_calls == []
        settings.saveConfig.assert_not_called()


def test_invalid_preflight_never_opens_socket(monkeypatch):
    socket = Mock(side_effect=AssertionError("must reject before socket creation"))
    monkeypatch.setattr("utils.socket.socket", socket)
    assert not isAvailableWebSocketServer("::1", 2231)
    assert not isAvailableWebSocketServer("127.0.0.1", 0)
    socket.assert_not_called()


def test_model_passes_admission_failure_to_existing_output_error_path(monkeypatch):
    from model import Model
    owner = object.__new__(Model)
    owner.ensure_initialized = Mock()
    owner.checkWebSocketServerAlive = Mock(return_value=True)
    owner.websocket_server = SimpleNamespace(send=Mock(side_effect=BufferError("queue full")))
    with pytest.raises(BufferError):
        owner.websocketSendMessage({"message": "hello"})


def test_model_server_and_token_getter_share_repaired_secret(settings, monkeypatch):
    from threading import Lock
    from model import Model
    load(settings, {"WEBSOCKET_AUTH_TOKEN": None})
    owner = object.__new__(Model)
    owner.ensure_initialized = Mock()
    owner._websocket_lifecycle_lock = Lock()
    owner.websocket_server = None
    factory = Mock(return_value=Mock(is_running=True))
    monkeypatch.setattr(model_module, "config", settings)
    monkeypatch.setattr(model_module, "WebSocketServer", factory)
    assert owner.startWebSocketServer(settings.WEBSOCKET_HOST, settings.WEBSOCKET_PORT)
    assert factory.call_args.kwargs["token"] == Controller.getWebSocketAuthToken()["result"]
