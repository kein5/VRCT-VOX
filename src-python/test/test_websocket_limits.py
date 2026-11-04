"""Output limits with real frame encoding, memory transports and a fake clock."""

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from websockets.protocol import OPEN
from websockets.server import ServerProtocol

from models.websocket import websocket_server as ws


class MemoryLoop(asyncio.SelectorEventLoop):
    """No self-pipe, sockets, server, or elapsed wall-clock waits."""
    def _make_self_pipe(self):
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        pass


@pytest.fixture
def clock_loop():
    loop = MemoryLoop()
    clock = SimpleNamespace(now=0.0)
    loop.time = lambda: clock.now

    def select(timeout):
        assert timeout is not None, "test would wait forever"
        clock.now += max(0, timeout)
        return []

    loop._selector.select = select
    yield loop
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()


class MemoryTransport:
    def __init__(self, *, reading=True):
        self.reading = reading
        self.size = self.peak = 0
        self.frames = []
        self.aborted = False

    def write(self, frame):
        assert not self.aborted
        self.frames.append(frame)
        if not self.reading:
            self.size += len(frame)
            self.peak = max(self.peak, self.size)

    def get_write_buffer_size(self):
        return self.size

    def is_closing(self):
        return self.aborted

    def abort(self):
        self.aborted = True
        self.size = 0


def connection(*, reading=True):
    client = ws._BoundedConnection(ServerProtocol(state=OPEN), SimpleNamespace())
    client.transport = MemoryTransport(reading=reading)
    return client


def test_slow_client_evicted_without_losing_healthy_messages(clock_loop):
    async def scenario():
        server = ws.WebSocketServer(token="test-token")
        slow, fast = connection(reading=False), connection()
        server.clients.update((slow, fast))
        for index in range(100):
            await server._broadcast_async(f"{index}:" + "あ" * 20_000)
        assert slow.transport.aborted
        assert slow not in server.clients
        assert slow.transport.peak <= ws._MAX_CLIENT_BUFFER_BYTES
        assert not fast.transport.aborted
        # Frames contain the sequence and full UTF-8 text; compare against a
        # separately encoded protocol, rather than relying on byte counts only.
        expected = ServerProtocol(state=OPEN)
        frames = []
        for index in range(100):
            expected.send_text((f"{index}:" + "あ" * 20_000).encode())
            frames.extend(expected.data_to_send())
        assert fast.transport.frames == frames
    clock_loop.run_until_complete(scenario())


@pytest.mark.parametrize("stalled_drain", [True, False])
def test_keepalive_deadline_includes_ping_drain_and_pong(clock_loop, stalled_drain):
    async def scenario():
        client = connection(reading=False)
        client.paused = stalled_drain
        await client.keepalive()
        assert client.transport.aborted
        assert len(client.transport.frames) == 1  # ping was written
        assert len(client.pong_waiters) == 1
        assert not client.drain_waiters
        assert clock_loop.time() == ws._PING_INTERVAL + ws._PING_TIMEOUT
    clock_loop.run_until_complete(scenario())


def test_healthy_pongs_keep_connection_alive(clock_loop):
    async def scenario():
        client = connection()
        calls = []

        async def ping():
            calls.append(clock_loop.time())
            reply = clock_loop.create_future()
            reply.set_result(None)
            return reply

        client.ping = ping
        task = clock_loop.create_task(client.keepalive())
        await asyncio.sleep(ws._PING_INTERVAL * 3 + 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert len(calls) == 3
        assert not client.transport.aborted
    clock_loop.run_until_complete(scenario())


@pytest.fixture
def producer():
    callbacks = deque()
    loop = SimpleNamespace(call_soon_threadsafe=lambda callback, *args: callbacks.append((callback, args)))
    run = ws._ServerRun(deadline=1, loop=loop, running=True,
                        send_queue=asyncio.Queue(maxsize=ws._MAX_PENDING_MESSAGES))
    server = ws.WebSocketServer(token="test-token")
    server._run = run
    return server, run, callbacks


@pytest.mark.parametrize("method", ["send", "broadcast"])
def test_admission_bounds_callbacks_before_the_loop_can_drain(producer, method):
    server, run, callbacks = producer
    send = getattr(server, method)
    for _ in range(ws._MAX_PENDING_MESSAGES):
        send("")  # zero bytes still costs a callback/queue entry
    with pytest.raises(BufferError):
        send("overflow")
    assert len(callbacks) == run.pending_messages == ws._MAX_PENDING_MESSAGES
    while callbacks:
        callback, args = callbacks.popleft()
        callback(*args)
    assert run.send_queue.qsize() == ws._MAX_PENDING_MESSAGES


def test_admission_bounds_utf8_bytes_and_rejects_oversized_message(producer):
    server, run, callbacks = producer
    payload = "あ" * (ws._MAX_OUTGOING_MESSAGE_SIZE // 3)
    admitted = ws._MAX_PENDING_BYTES // len(payload.encode())
    for _ in range(admitted):
        server.send(payload)
    with pytest.raises(BufferError):
        server.broadcast(payload)
    assert len(callbacks) == admitted
    assert run.pending_bytes <= ws._MAX_PENDING_BYTES
    with pytest.raises(BufferError):
        server.send("あ" * ws._MAX_OUTGOING_MESSAGE_SIZE)
    assert len(callbacks) == admitted


def test_drain_releases_admission_and_preserves_order(producer, clock_loop):
    server, run, callbacks = producer
    delivered = []

    async def record(message):
        delivered.append(message)

    async def scenario():
        server._broadcast_async = record
        for value in ("one", "two", "three"):
            server.send(value)
        while callbacks:
            callback, args = callbacks.popleft()
            callback(*args)
        task = clock_loop.create_task(server._send_loop(run))
        await asyncio.sleep(1)
        assert delivered == ["one", "two", "three"]
        assert run.pending_messages == run.pending_bytes == 0
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    clock_loop.run_until_complete(scenario())


def test_stop_and_closed_loop_release_admission(producer):
    server, run, callbacks = producer
    server.send("queued")
    run.cancelled.set()
    callback, args = callbacks.popleft()
    callback(*args)
    assert run.send_queue.empty()
    assert run.pending_messages == run.pending_bytes == 0
    run.cancelled.clear()
    run.loop.call_soon_threadsafe = Mock(side_effect=RuntimeError("loop closed"))
    server.send("queued")
    assert run.pending_messages == run.pending_bytes == 0


def test_serve_installs_limits_without_opening_a_listener(clock_loop, monkeypatch):
    async def scenario():
        options = {}
        listener = SimpleNamespace(start_serving=Mock())

        async def start_serving():
            pass

        async def serve(*args, **kwargs):
            options.update(kwargs)
            return listener

        async def send_loop(run):
            assert run.send_queue.maxsize == ws._MAX_PENDING_MESSAGES

        listener.start_serving = start_serving
        monkeypatch.setattr(ws.websockets, "serve", serve)
        server = ws.WebSocketServer(token="test-token")
        server._send_loop = send_loop
        await server._serve(ws._ServerRun(deadline=float("inf")))
        assert options["create_connection"] is ws._BoundedConnection
        assert options["compression"] is None
        assert options["max_size"] == 64 * 1024
        assert options["start_serving"] is False
    clock_loop.run_until_complete(scenario())
