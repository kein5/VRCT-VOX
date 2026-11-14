"""SEC-06: what clients send is dropped, and a client that floods the server is closed.

These run the real server on a loopback port with websockets' asyncio client.
"""
import asyncio
import socket

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from models.websocket import websocket_server
from models.websocket.websocket_server import WebSocketServer

TOKEN = "tok-receive-limits-0123456789"


def _free_port():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    except PermissionError:
        pytest.skip("sandbox denies localhost TCP sockets")


@pytest.fixture
def server():
    running = WebSocketServer(host="127.0.0.1", port=_free_port(), token=TOKEN)
    running.start(timeout=5.0)
    yield running
    running.stop()


async def _connected(server, count):
    for _ in range(500):
        if len(server.clients) == count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected {count} clients, have {len(server.clients)}")


def test_a_flooding_client_is_closed_and_the_others_keep_receiving(server):
    async def run():
        uri = f"ws://127.0.0.1:{server.port}/?token={TOKEN}"
        async with connect(uri, open_timeout=5) as listener, connect(uri, open_timeout=5) as flooder:
            await _connected(server, 2)
            sent = 0
            try:
                for _ in range(500):
                    await flooder.send("spam " * 100)
                    sent += 1
            except ConnectionClosed:
                pass
            with pytest.raises(ConnectionClosed) as closed:
                await asyncio.wait_for(flooder.recv(), 5)
            assert closed.value.rcvd is not None and closed.value.rcvd.code == 1008
            assert sent > websocket_server._INCOMING_MESSAGE_BURST
            await _connected(server, 1)
            await asyncio.to_thread(server.send, "still here")
            assert await asyncio.wait_for(listener.recv(), 5) == "still here"
    asyncio.run(run())


def test_a_client_that_sends_a_little_stays_connected(server):
    async def run():
        uri = f"ws://127.0.0.1:{server.port}/?token={TOKEN}"
        async with connect(uri, open_timeout=5) as client:
            await _connected(server, 1)
            for index in range(5):
                await client.send(f"hello {index}")
            await asyncio.sleep(0.2)
            await asyncio.to_thread(server.send, "reply")
            assert await asyncio.wait_for(client.recv(), 5) == "reply"
            assert len(server.clients) == 1
    asyncio.run(run())
