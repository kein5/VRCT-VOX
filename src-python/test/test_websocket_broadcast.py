"""A slow WebSocket client must not hold back messages to the other clients.

The server used to await send() for every client before taking the next
message, so one client that stopped reading stalled everyone until it timed
out (the websockets docs describe this as blocking "until the slowest client
times out"). It now uses websockets' broadcast(), which does not wait.
"""

import base64
import os
import socket
import time

import pytest
from websockets.sync.client import connect

from models.websocket.websocket_server import WebSocketServer, _MAX_INCOMING_MESSAGE_SIZE


def _free_port() -> int:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("sandbox denies localhost TCP sockets (127.0.0.1:0)")
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def server():
    instance = WebSocketServer(host="127.0.0.1", port=_free_port())
    instance.start(timeout=5.0)
    yield instance
    instance.stop()


def _wait_for_clients(server: WebSocketServer, count: int) -> None:
    end = time.monotonic() + 5
    while len(server.clients) < count and time.monotonic() < end:
        time.sleep(0.01)
    assert len(server.clients) == count


def _client_that_never_reads(port: int) -> socket.socket:
    """Complete the WebSocket handshake by hand, then never read again."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    sock.connect(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(1)
    assert response.startswith(b"HTTP/1.1 101"), response
    return sock


def test_a_client_that_stops_reading_does_not_stall_the_others(server):
    slow = _client_that_never_reads(server.port)
    try:
        with connect(f"ws://127.0.0.1:{server.port}/") as fast:
            _wait_for_clients(server, 2)
            payload = "x" * 60_000
            total = 600  # about 36 MB: far more than the slow client's socket buffers hold
            for index in range(total):
                server.send(f"{index}:{payload}")
            received = []
            deadline = time.monotonic() + 10
            while len(received) < total and time.monotonic() < deadline:
                received.append(fast.recv(timeout=deadline - time.monotonic()).split(":", 1)[0])
            assert received == [str(index) for index in range(total)]
    finally:
        slow.close()


def test_incoming_messages_over_the_limit_close_the_connection(server):
    with connect(f"ws://127.0.0.1:{server.port}/") as client:
        _wait_for_clients(server, 1)
        client.send("y" * (_MAX_INCOMING_MESSAGE_SIZE + 1))
        with pytest.raises(Exception):
            client.recv(timeout=5)
    assert _MAX_INCOMING_MESSAGE_SIZE == 64 * 1024
