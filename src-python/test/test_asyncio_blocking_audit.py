"""Loop progress and thread ownership without sockets, devices or model loading."""

import asyncio
import sys
import threading
from contextlib import suppress
from types import SimpleNamespace

import pytest

from models.telemetry import Telemetry
from models.telemetry.core import TelemetryCore
from models.telemetry.state import TelemetryState
from models.websocket import websocket_server


def run_loop(coroutine):
    # The sandbox can reject socketpair.send(), including asyncio's internal
    # cross-thread wakeup. Timers keep this real debug loop polling during both
    # the test and Runner's executor shutdown; no network permission is needed.
    def factory():
        loop = asyncio.new_event_loop()

        def poll():
            loop.call_later(0.005, poll)

        poll()
        return loop

    with asyncio.Runner(debug=True, loop_factory=factory) as runner:
        runner.run(coroutine)


class BlockingCall:
    """Only the event loop can release this fake slow synchronous operation."""

    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.expired = False
        self.thread = None

    def __call__(self):
        self.thread = threading.get_ident()
        self.loop.call_soon_threadsafe(self.entered.set)
        self.expired = not self.release.wait(2)

    async def check_progress(self):
        await asyncio.wait_for(self.entered.wait(), 1)
        await asyncio.sleep(0.01)
        assert not self.expired, "synchronous work prevented the loop from releasing it"
        assert self.thread != threading.get_ident()


async def cancel(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


class FakeTransport:
    def get_write_buffer_size(self):
        return 0

    def abort(self):
        raise AssertionError("a healthy client must not be aborted")


class FakeClient:
    def __init__(self):
        self.transport = FakeTransport()


def fake_client():
    return FakeClient()


class Messages:
    def __aiter__(self):
        self.messages = iter(("first", "second"))
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise StopAsyncIteration from None


def test_websocket_handler_keeps_loop_live_and_preserves_order():
    async def run():
        server = websocket_server.WebSocketServer()
        socket = Messages()
        gate = BlockingCall()
        received = []

        def handler(owner, connection, message):
            assert owner is server and connection is socket
            received.append(message)
            if message == "first":
                gate()

        server.set_message_handler(handler)
        task = asyncio.create_task(server._handler(socket))
        try:
            await gate.check_progress()
            assert received == ["first"]
            gate.release.set()
            await asyncio.wait_for(task, 1)
            assert received == ["first", "second"]
            assert not server.clients
        finally:
            gate.release.set()
            await cancel(task)

    run_loop(run())


def test_websocket_error_logging_keeps_traceback_off_loop(monkeypatch):
    async def run():
        gate = BlockingCall()
        exceptions = []
        server = websocket_server.WebSocketServer()

        def handler(*args):
            raise ValueError("callback failure")

        def log():
            exceptions.append(sys.exc_info()[1])
            gate()

        monkeypatch.setattr(websocket_server, "errorLogging", log)
        server.set_message_handler(handler)
        task = asyncio.create_task(server._handler(Messages()))
        try:
            await gate.check_progress()
            gate.release.set()
            await asyncio.wait_for(task, 1)
            assert len(exceptions) == 2
            assert all(str(exc) == "callback failure" for exc in exceptions)
        finally:
            gate.release.set()
            await cancel(task)

    run_loop(run())


def test_websocket_backlog_yields_before_draining_every_message(monkeypatch):
    async def run():
        delivered, tick = [], []
        server = websocket_server.WebSocketServer(token="test-token")
        attempt = websocket_server._ServerRun(deadline=0)
        attempt.send_queue = asyncio.Queue()
        for index in range(100):
            message = str(index)
            attempt.send_queue.put_nowait((message, len(message)))
            attempt.pending_messages += 1
            attempt.pending_bytes += len(message)
        async def broadcast(message):
            delivered.append(message)

        async def drained():
            while len(delivered) < 100:
                await asyncio.sleep(0)

        monkeypatch.setattr(server, "_broadcast_async", broadcast)
        task = asyncio.create_task(server._send_loop(attempt))
        asyncio.get_running_loop().call_soon(lambda: tick.append(len(delivered)))
        try:
            await asyncio.wait_for(drained(), 1)
            assert 0 < tick[0] < 100
            assert delivered == [str(index) for index in range(100)]
            assert (attempt.pending_messages, attempt.pending_bytes) == (0, 0)
        finally:
            await cancel(task)

    run_loop(run())


@pytest.mark.parametrize("operation", ["should_send_app_started_today", "mark_app_started_sent_today"])
def test_telemetry_state_lock_and_persistence_do_not_block_loop(monkeypatch, operation):
    async def run():
        telemetry = object.__new__(Telemetry)
        telemetry.state = TelemetryState()
        telemetry.core = TelemetryCore(telemetry.state)
        gate = BlockingCall()
        events = []
        original = getattr(telemetry.state, operation)

        def slow():
            gate()
            return original()

        async def track(event):
            events.append(event)

        monkeypatch.setattr(telemetry.state, operation, slow)
        monkeypatch.setattr(telemetry.core, "send_event", track)
        task = asyncio.create_task(telemetry._init_async("test"))
        try:
            await gate.check_progress()
            # Shutdown work can run even while the state operation waits.
            await asyncio.wait_for(telemetry._shutdown_async(), 0.1)
            gate.release.set()
            await asyncio.wait_for(task, 1)
            assert events == ["app_started"]
            assert not await asyncio.to_thread(telemetry.state.should_send_app_started_today)
        finally:
            gate.release.set()
            await cancel(task)

    run_loop(run())


def test_websocket_cross_thread_send_broadcast_and_stop(monkeypatch):
    async def run():
        server = websocket_server.WebSocketServer(token="test-token")
        loop = asyncio.get_running_loop()
        attempt = websocket_server._ServerRun(deadline=0)
        attempt.loop, attempt.send_queue, attempt.running = loop, asyncio.Queue(), True
        server._run = attempt
        server.clients.add(fake_client())
        delivered = asyncio.Event()
        owner = threading.get_ident()

        def broadcast(clients, message):
            assert threading.get_ident() == owner and message == "broadcast"
            delivered.set()

        monkeypatch.setattr(websocket_server, "broadcast", broadcast)
        await asyncio.to_thread(server.send, "send")
        assert await asyncio.wait_for(attempt.send_queue.get(), 1) == ("send", 4)
        server._release_message(attempt, 4)
        # broadcast() shares send()'s bounded queue; the owner loop fans it out.
        sender = asyncio.create_task(server._send_loop(attempt))
        await asyncio.to_thread(server.broadcast, "broadcast")
        await asyncio.wait_for(delivered.wait(), 1)
        await cancel(sender)
        attempt.task = asyncio.create_task(asyncio.sleep(60))
        await asyncio.to_thread(server._stop_run, attempt)
        with suppress(asyncio.CancelledError):
            await attempt.task
        assert attempt.task.cancelled()

    run_loop(run())


def test_websocket_large_fanout_yields_between_client_batches(monkeypatch):
    async def run():
        server = websocket_server.WebSocketServer(token="test-token")
        server.clients.update(fake_client() for _ in range(100))
        expected = set(server.clients)
        sent, tick = [], []

        def broadcast(clients, message):
            assert message == "payload" and len(clients) <= 32
            sent.extend(clients)

        monkeypatch.setattr(websocket_server, "broadcast", broadcast)
        task = asyncio.create_task(server._broadcast_async("payload"))
        asyncio.get_running_loop().call_soon(lambda: tick.append(len(sent)))
        await task
        assert 0 < tick[0] < 100
        assert len(sent) == 100 and set(sent) == expected

    run_loop(run())


def test_without_a_handler_incoming_messages_are_dropped_on_the_loop(monkeypatch):
    """The app sets no handler (SEC-06): messages never reach a worker thread or the log."""
    async def run():
        server = websocket_server.WebSocketServer()
        errors, sent, threads = [], [], []
        monkeypatch.setattr(websocket_server, "errorLogging", lambda: errors.append(sys.exc_info()[1]))
        monkeypatch.setattr(websocket_server.asyncio, "to_thread",
                            lambda *args, **kwargs: threads.append(args) or asyncio.sleep(0))
        monkeypatch.setattr(server, "send", sent.append)
        await asyncio.wait_for(server._handler(Messages()), 1)
        assert (errors, sent, threads) == ([], [], [])
        assert not server.clients

    run_loop(run())


class Flood:
    """A client that sends `count` messages of `size` characters as fast as it can."""

    def __init__(self, count, size=1):
        self.remaining, self.message = count, "x" * size
        self.received, self.closed_with, self.transport = 0, None, SimpleNamespace(aborted=False)
        self.transport.abort = lambda: setattr(self.transport, "aborted", True)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.remaining == 0 or self.closed_with is not None:
            raise StopAsyncIteration
        self.remaining -= 1
        self.received += 1
        return self.message

    async def close(self, code, reason):
        self.closed_with = (code, reason)


@pytest.mark.parametrize("count,size,closed_after", [
    (websocket_server._INCOMING_MESSAGE_BURST, 1, None),  # a burst within the budget stays open
    (200, 1, websocket_server._INCOMING_MESSAGE_BURST + 1),  # message count
    (10, 60 * 1024, 5),  # 4 x 60 KiB fit in 256 KiB, the fifth does not
])
def test_a_client_over_the_incoming_budget_is_closed_with_1008(monkeypatch, count, size, closed_after):
    async def run():
        server = websocket_server.WebSocketServer()
        monkeypatch.setattr(websocket_server, "printLog", lambda *args: None)
        # A frozen clock: nothing refills while the client floods.
        monkeypatch.setattr(websocket_server, "monotonic", lambda: 100.0)
        client = Flood(count, size)
        await asyncio.wait_for(server._handler(client), 1)
        if closed_after is None:
            assert client.closed_with is None and not client.transport.aborted
            assert client.received == count
        else:
            assert client.closed_with == (1008, "incoming message limit")
            assert client.transport.aborted
            assert client.received == closed_after
        assert not server.clients

    run_loop(run())


def test_the_incoming_budget_refills_with_time():
    now = [0.0]
    budget = websocket_server._IncomingBudget(clock=lambda: now[0])
    for _ in range(websocket_server._INCOMING_MESSAGE_BURST):
        assert budget.admit(10)
    assert not budget.admit(10)
    now[0] += 1.0  # ten messages a second
    assert all(budget.admit(10) for _ in range(10))
    assert not budget.admit(10)
    # A steady 10 messages a second is never cut off.
    for _ in range(100):
        now[0] += 0.1
        assert budget.admit(1000)
