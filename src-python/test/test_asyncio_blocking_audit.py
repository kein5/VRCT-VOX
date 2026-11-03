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
        server = websocket_server.WebSocketServer()
        queue = asyncio.Queue()
        for index in range(100):
            queue.put_nowait(str(index))
        async def broadcast(message):
            delivered.append(message)

        monkeypatch.setattr(server, "_broadcast_async", broadcast)
        task = asyncio.create_task(server._send_loop(SimpleNamespace(send_queue=queue)))
        asyncio.get_running_loop().call_soon(lambda: tick.append(len(delivered)))
        try:
            while len(delivered) < 100:
                await asyncio.sleep(0)
            assert 0 < tick[0] < 100
            assert delivered == [str(index) for index in range(100)]
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
        server = websocket_server.WebSocketServer()
        loop = asyncio.get_running_loop()
        attempt = websocket_server._ServerRun(deadline=0)
        attempt.loop, attempt.send_queue, attempt.running = loop, asyncio.Queue(), True
        server._run = attempt
        server.clients.add(object())
        delivered = asyncio.Event()
        owner = threading.get_ident()

        def broadcast(clients, message):
            assert threading.get_ident() == owner and message == "broadcast"
            delivered.set()

        monkeypatch.setattr(websocket_server, "broadcast", broadcast)
        await asyncio.to_thread(server.send, "send")
        assert await asyncio.wait_for(attempt.send_queue.get(), 1) == "send"
        await asyncio.to_thread(server.broadcast, "broadcast")
        await asyncio.wait_for(delivered.wait(), 1)
        attempt.task = asyncio.create_task(asyncio.sleep(60))
        await asyncio.to_thread(server._stop_run, attempt)
        with suppress(asyncio.CancelledError):
            await attempt.task
        assert attempt.task.cancelled()

    run_loop(run())


def test_websocket_large_fanout_yields_between_client_batches(monkeypatch):
    async def run():
        server = websocket_server.WebSocketServer()
        server.clients.update(object() for _ in range(100))
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


def test_model_ignores_incoming_websocket_messages_without_logging(monkeypatch):
    from model import Model

    async def run():
        # Bind the production callback without initializing the app singleton.
        model = object.__new__(Model)
        server = websocket_server.WebSocketServer()
        errors, sent = [], []
        monkeypatch.setattr(websocket_server, "errorLogging", lambda: errors.append(sys.exc_info()[1]))
        monkeypatch.setattr(server, "send", sent.append)
        server.set_message_handler(model.message_handler)
        await asyncio.wait_for(server._handler(Messages()), 1)
        assert errors == []
        assert sent == []
        assert not server.clients

    run_loop(run())
