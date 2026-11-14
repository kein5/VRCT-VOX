"""SEC-01: the WebSocket and OBS servers beyond this PC only over TLS, and a token that can be replaced.

A relay between the client and the server stands for someone who can watch the network
path: it forwards every byte both ways and keeps a copy. Over plain HTTP and WebSocket the
copy holds the token and the conversation (the attack the audit describes); over TLS it
holds neither. The servers listen on 127.0.0.1 here, so the test needs no firewall rule.
"""
import socket
import ssl
import time
from http.client import HTTPConnection, HTTPSConnection

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from models.obs.obs_browser_source_server import ObsBrowserSourceServer
from models.websocket import tls
from models.websocket.websocket_server import WebSocketServer
from tls_certs import Relay, client_context, make_certificate, wss_open, wss_receive

TOKEN = "tok-AbCdEf0123456789_secret"
SPOKEN = "kaigi-no-naiyou-0042"


def _free_port():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    except PermissionError:
        pytest.skip("sandbox denies localhost TCP sockets")


@pytest.fixture
def certificate(tmp_path):
    return make_certificate(tmp_path)


@pytest.fixture
def relays():
    made = []
    yield lambda port: made.append(Relay(port)) or made[-1]
    for relay in made:
        relay.close()


def _websocket(context=None, token=TOKEN):
    server = WebSocketServer(host="127.0.0.1", port=_free_port(), token=token, ssl_context=context)
    server.start(timeout=5.0)
    return server


def _wait_for_clients(server, count):
    end = time.monotonic() + 5
    while len(server.clients) != count and time.monotonic() < end:
        time.sleep(0.01)
    assert len(server.clients) == count


def _deliver(server):
    """Once the client is in, send it one line of conversation."""
    return lambda: (_wait_for_clients(server, 1), server.send(SPOKEN))


def _receive_one(uri, *, ssl_context=None, server):
    if ssl_context is not None:
        return wss_receive(uri, ssl_context, _deliver(server))
    with connect(uri, open_timeout=5) as client:
        _deliver(server)()
        return client.recv(timeout=5)


# --- Which addresses need TLS ---------------------------------------------------------

@pytest.mark.parametrize("host,needed", [
    ("127.0.0.1", False), ("127.0.0.2", False), ("127.255.255.254", False),
    ("192.168.1.5", True), ("10.0.0.2", True), ("172.16.0.9", True), ("100.64.1.1", True),
    ("8.8.8.8", True), ("not an address", True), (None, True),
])
def test_only_loopback_addresses_listen_without_tls(host, needed):
    assert tls.requires_tls(host) is needed


# --- Loading the certificate and key ----------------------------------------------------

def test_a_certificate_and_its_key_make_a_server_context(certificate):
    context = tls.server_context(*certificate)
    assert isinstance(context, ssl.SSLContext)
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_one_file_holding_both_the_certificate_and_the_key_works(certificate, tmp_path):
    combined = tmp_path / "combined.pem"
    combined.write_bytes(open(certificate[0], "rb").read() + open(certificate[1], "rb").read())
    assert isinstance(tls.server_context(str(combined), str(combined)), ssl.SSLContext)


def _refusals(tmp_path, certificate):
    cert_file, key_file = certificate
    other_cert, other_key = make_certificate(tmp_path, name="other")
    garbage = tmp_path / "garbage.pem"
    garbage.write_text("-----BEGIN CERTIFICATE-----\nSECRET-LOOKING-CONTENT\n-----END CERTIFICATE-----\n")
    empty = tmp_path / "empty.pem"
    empty.write_bytes(b"")
    huge = tmp_path / "huge.pem"
    huge.write_bytes(b"A" * (tls.MAX_PEM_BYTES + 1))
    encrypted_cert, encrypted_key = make_certificate(tmp_path, passphrase=b"pass phrase", name="encrypted")
    return {
        "missing certificate": (str(tmp_path / "nowhere.pem"), key_file),
        "missing key": (cert_file, str(tmp_path / "nowhere-key.pem")),
        "folder": (str(tmp_path), key_file),
        "empty file": (str(empty), key_file),
        "too large": (str(huge), key_file),
        "not a certificate": (str(garbage), key_file),
        "key of another certificate": (cert_file, other_key),
        "certificate of another key": (other_cert, key_file),
        "key with a passphrase": (encrypted_cert, encrypted_key),
        "empty path": ("", key_file),
        "blank key path": (cert_file, "   "),
        "not text": (None, key_file),
    }


def test_unusable_certificates_and_keys_are_refused_without_leaking_them(tmp_path, certificate):
    for case, (cert_file, key_file) in _refusals(tmp_path, certificate).items():
        with pytest.raises(tls.TlsSettingsError) as caught:
            tls.server_context(cert_file, key_file)
        message = str(caught.value)
        assert message in tls.TlsSettingsError.REASONS, case
        # The reason names the problem, never the path or what the file holds.
        assert "SECRET" not in message and str(tmp_path) not in message, case


def test_a_key_with_a_passphrase_never_waits_for_a_typed_answer(tmp_path, monkeypatch):
    cert_file, key_file = make_certificate(tmp_path, passphrase=b"pass phrase")
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("prompted for a passphrase"))
    started = time.monotonic()
    with pytest.raises(tls.TlsSettingsError):
        tls.server_context(cert_file, key_file)
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2"])
def test_loopback_listeners_get_no_context(host):
    assert tls.listener_context(host, "", "") is None


def test_listeners_beyond_this_pc_need_a_usable_certificate(certificate):
    with pytest.raises(tls.TlsSettingsError):
        tls.listener_context("192.168.1.5", "", "")
    assert isinstance(tls.listener_context("192.168.1.5", *certificate), ssl.SSLContext)


# --- WebSocket over TLS ----------------------------------------------------------------

def test_websocket_over_tls_carries_messages_to_a_client_that_trusts_the_certificate(certificate):
    server = _websocket(tls.server_context(*certificate))
    try:
        message = _receive_one(f"wss://127.0.0.1:{server.port}/?token={TOKEN}",
                               ssl_context=client_context(certificate[0]), server=server)
        assert message == SPOKEN
    finally:
        server.stop()


def test_websocket_over_tls_refuses_a_plain_client_and_a_wrong_token(certificate):
    server = _websocket(tls.server_context(*certificate))
    try:
        with pytest.raises(Exception):
            with connect(f"ws://127.0.0.1:{server.port}/?token={TOKEN}", open_timeout=3):
                pass
        with pytest.raises(InvalidStatus) as refused:
            wss_open(f"wss://127.0.0.1:{server.port}/?token=wrong", client_context(certificate[0]))
        assert refused.value.response.status_code == 403
        assert server.clients == set()
    finally:
        server.stop()


def test_websocket_refuses_a_client_that_does_not_trust_the_certificate(certificate):
    server = _websocket(tls.server_context(*certificate))
    try:
        with pytest.raises(ssl.SSLError):
            wss_open(f"wss://127.0.0.1:{server.port}/?token={TOKEN}", ssl.create_default_context())
    finally:
        server.stop()


def test_an_observer_reads_the_token_and_text_over_plain_websocket_but_not_over_tls(certificate, relays):
    # Without TLS the attack works: this is why only loopback may listen without it.
    plain = _websocket()
    try:
        relay = relays(plain.port)
        assert _receive_one(f"ws://127.0.0.1:{relay.port}/?token={TOKEN}", server=plain) == SPOKEN
        assert TOKEN.encode() in relay.captured and SPOKEN.encode() in relay.captured
    finally:
        plain.stop()

    secure = _websocket(tls.server_context(*certificate))
    try:
        relay = relays(secure.port)
        assert _receive_one(f"wss://127.0.0.1:{relay.port}/?token={TOKEN}",
                            ssl_context=client_context(certificate[0]), server=secure) == SPOKEN
        assert relay.captured, "the relay saw no traffic"
        assert TOKEN.encode() not in relay.captured and SPOKEN.encode() not in relay.captured
    finally:
        secure.stop()


# --- OBS over HTTPS --------------------------------------------------------------------

def _obs(context=None, token=TOKEN):
    server = ObsBrowserSourceServer("127.0.0.1", 0, ws_token=token, ssl_context=context)
    server.start()
    return server, server._server.server_address[1]


def _https_get(port, target, cert_file):
    connection = HTTPSConnection("127.0.0.1", port, timeout=5, context=client_context(cert_file))
    try:
        connection.request("GET", target)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_obs_over_https_serves_the_page_only_with_the_token(certificate):
    server, port = _obs(tls.server_context(*certificate))
    try:
        status, body = _https_get(port, f"/obs?token={TOKEN}", certificate[0])
        assert status == 200 and body.startswith(b"<!doctype html>")
        # The page connects back over WSS when it was served over HTTPS.
        assert b'location.protocol === "https:" ? "wss" : "ws"' in body
        assert _https_get(port, "/obs?token=wrong", certificate[0])[0] == 403
        assert _https_get(port, "/health", certificate[0]) == (200, b"ok")
    finally:
        server.stop()


def test_obs_over_https_refuses_plain_http(certificate):
    server, port = _obs(tls.server_context(*certificate))
    try:
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        with pytest.raises((OSError, ConnectionError)):
            connection.request("GET", f"/obs?token={TOKEN}")
            connection.getresponse()
        connection.close()
        # A failed handshake does not stop the server for the next client.
        assert _https_get(port, "/health", certificate[0]) == (200, b"ok")
    finally:
        server.stop()


def test_a_client_that_stalls_the_tls_handshake_does_not_hold_up_others(certificate):
    server, port = _obs(tls.server_context(*certificate))
    stalled = socket.create_connection(("127.0.0.1", port))
    try:
        stalled.sendall(b"\x16\x03\x01")  # The start of a ClientHello, then nothing.
        started = time.monotonic()
        assert _https_get(port, "/health", certificate[0]) == (200, b"ok")
        assert time.monotonic() - started < 3
    finally:
        stalled.close()
        server.stop()


def test_an_observer_reads_the_obs_token_over_http_but_not_over_https(certificate, relays):
    plain, plain_port = _obs()
    try:
        relay = relays(plain_port)
        connection = HTTPConnection("127.0.0.1", relay.port, timeout=5)
        connection.request("GET", f"/obs?token={TOKEN}")
        assert connection.getresponse().status == 200
        connection.close()
        assert TOKEN.encode() in relay.captured
    finally:
        plain.stop()

    secure, secure_port = _obs(tls.server_context(*certificate))
    try:
        relay = relays(secure_port)
        status, body = _https_get(relay.port, f"/obs?token={TOKEN}", certificate[0])
        assert status == 200 and TOKEN.encode() in body
        assert relay.captured and TOKEN.encode() not in relay.captured
    finally:
        secure.stop()


# --- Replacing the token ---------------------------------------------------------------

def test_a_new_token_shuts_out_the_old_one_and_its_open_connections():
    server = _websocket()
    try:
        old = connect(f"ws://127.0.0.1:{server.port}/?token={TOKEN}", open_timeout=5)
        _wait_for_clients(server, 1)
        server.set_token("tok-new-0123456789")
        # The connection made with the old token is closed at once.
        with pytest.raises(Exception):
            old.recv(timeout=5)
        old.close()
        _wait_for_clients(server, 0)
        with pytest.raises(InvalidStatus) as refused:
            with connect(f"ws://127.0.0.1:{server.port}/?token={TOKEN}", open_timeout=5):
                pass
        assert refused.value.response.status_code == 403
        with connect(f"ws://127.0.0.1:{server.port}/?token=tok-new-0123456789", open_timeout=5) as client:
            _wait_for_clients(server, 1)
            server.send(SPOKEN)
            assert client.recv(timeout=5) == SPOKEN
    finally:
        server.stop()


@pytest.mark.parametrize("token", ["", "   ", None, 42])
def test_an_empty_token_is_never_set(token):
    server = WebSocketServer(host="127.0.0.1", port=_free_port(), token=TOKEN)
    with pytest.raises(ValueError):
        server.set_token(token)
    assert server.token == TOKEN


def test_the_obs_page_follows_a_new_token_at_once():
    server, port = _obs()
    try:
        server.set_token("tok-new-0123456789")
        for target, status in ((f"/obs?token={TOKEN}", 403), ("/obs?token=tok-new-0123456789", 200)):
            connection = HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", target)
            response = connection.getresponse()
            body = response.read()
            connection.close()
            assert response.status == status
            assert (TOKEN.encode() in body) is False
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/obs/connection", headers={"Authorization": f"Bearer {TOKEN}"})
        assert connection.getresponse().status == 403
        connection.close()
    finally:
        server.stop()
