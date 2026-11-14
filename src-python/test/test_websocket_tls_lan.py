"""SEC-01 on a real LAN-facing interface, through the production start path (Model).

The servers listen on this machine's non-loopback IPv4 address, as they do when a user
enters a LAN address. Without a certificate nothing listens there. With one, a client
gets WSS and HTTPS, a plain client is refused, and an observer on the path (a relay whose
leg to the server crosses that interface) sees neither the token nor the conversation.

Binding a LAN address raises the Windows Defender Firewall question for python.exe, so
on Windows this runs only with VRCT_TEST_LAN_BIND=1. Linux CI runs it.
"""
import ipaddress
import os
import socket
import time
from http.client import HTTPConnection, HTTPSConnection
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from websockets.sync.client import connect

import model as model_module
from tls_certs import Relay, client_context, make_certificate, wss_receive

pytestmark = pytest.mark.skipif(
    os.name == "nt" and os.environ.get("VRCT_TEST_LAN_BIND") != "1",
    reason="binding a LAN address raises the Windows firewall question (set VRCT_TEST_LAN_BIND=1)")

TOKEN = "tok-lan-0123456789abcdef_secret"
SPOKEN = "lan-kaigi-no-naiyou-0042"


def _lan_address():
    # A UDP "connect" picks the outgoing interface without sending anything.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))
        except OSError:
            pytest.skip("no route off this machine")
        address = probe.getsockname()[0]
    if ipaddress.IPv4Address(address).is_loopback or ipaddress.IPv4Address(address).is_unspecified:
        pytest.skip("no non-loopback IPv4 address")
    return address


def _free_port(host):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _listening(host, port):
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.fixture
def lan():
    return _lan_address()


@pytest.fixture
def owner(monkeypatch):
    settings = SimpleNamespace(WEBSOCKET_AUTH_TOKEN=TOKEN, WEBSOCKET_TLS_CERT_FILE="", WEBSOCKET_TLS_KEY_FILE="")
    monkeypatch.setattr(model_module, "config", settings)
    instance = object.__new__(model_module.Model)
    instance.ensure_initialized = Mock()
    instance._websocket_lifecycle_lock = Lock()
    instance._obs_lifecycle_lock = Lock()
    instance.websocket_server = None
    instance.obs_browser_source_server = None
    instance.settings = settings
    yield instance
    instance.stopObsBrowserSourceServer()
    instance.stopWebSocketServer()


def test_nothing_listens_on_the_lan_address_without_a_certificate(owner, lan):
    ws_port, obs_port = _free_port(lan), _free_port(lan)
    assert owner.startWebSocketServer(lan, ws_port) is False
    assert owner.startObsBrowserSourceServer(lan, obs_port) is False
    assert not _listening(lan, ws_port) and not _listening(lan, obs_port)


def test_on_the_lan_address_only_tls_carries_the_token_and_the_text(owner, lan, tmp_path):
    cert_file, key_file = make_certificate(tmp_path, ip=lan)
    owner.settings.WEBSOCKET_TLS_CERT_FILE, owner.settings.WEBSOCKET_TLS_KEY_FILE = cert_file, key_file
    ws_port, obs_port = _free_port(lan), _free_port(lan)
    assert owner.startWebSocketServer(lan, ws_port)
    assert owner.startObsBrowserSourceServer(lan, obs_port)

    # A plain client is refused on both.
    with pytest.raises(Exception):
        with connect(f"ws://{lan}:{ws_port}/?token={TOKEN}", open_timeout=3):
            pass
    plain = HTTPConnection(lan, obs_port, timeout=3)
    with pytest.raises((OSError, ConnectionError)):
        plain.request("GET", f"/obs?token={TOKEN}")
        plain.getresponse()
    plain.close()

    relays = [Relay(ws_port, lan), Relay(obs_port, lan)]
    try:
        # WebSocket through the observer: the client checks the certificate for the LAN address.
        context = client_context(cert_file)
        context.check_hostname = False  # The relay is reached as 127.0.0.1; the certificate names the LAN address.
        def deliver():
            end = time.monotonic() + 5
            while not owner.websocket_server.clients and time.monotonic() < end:
                time.sleep(0.01)
            owner.websocket_server.send(SPOKEN)
        assert wss_receive(f"wss://127.0.0.1:{relays[0].port}/?token={TOKEN}", context, deliver) == SPOKEN

        connection = HTTPSConnection("127.0.0.1", relays[1].port, timeout=5, context=context)
        connection.request("GET", f"/obs?token={TOKEN}", headers={"Host": f"{lan}:{obs_port}"})
        response = connection.getresponse()
        assert response.status == 200 and TOKEN.encode() in response.read()
        connection.close()

        for relay in relays:
            assert relay.captured, "the observer saw no traffic"
            assert TOKEN.encode() not in relay.captured
            assert SPOKEN.encode() not in relay.captured
    finally:
        for relay in relays:
            relay.close()
