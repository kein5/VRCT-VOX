import asyncio
import base64
from contextlib import asynccontextmanager
import importlib
import json
from itertools import count
import socket
import time
from types import SimpleNamespace

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response
from websockets.datastructures import Headers

from models.voice_events import AudioFrame

PREFIX = "conversation.item.input_audio_transcription."


def module():
    return importlib.import_module("models.transcription.speechcpp_realtime")


@asynccontextmanager
async def mock_server(mode="normal"):
    state = SimpleNamespace(
        requests=[], connected=asyncio.Event(), configured=asyncio.Event()
    )
    ids = count()

    async def send(ws, kind, **kwargs):
        await ws.send(json.dumps({"event_id": f"e{next(ids)}", "type": kind, **kwargs}))

    async def handler(ws):
        state.connected.set()
        try:
            await send(
                ws,
                "session.created",
                session={"type": "transcription", "id": "mock-session"},
            )
            config = json.loads(await ws.recv())
            state.requests.append(config)
            state.configured.set()
            if mode == "no_config":
                await ws.wait_closed()
                return
            if mode == "config_error":
                await send(ws, "error", error={"message": "private server detail"})
                await ws.wait_closed()
                return
            if mode == "bad_config":
                config["session"]["audio"]["input"]["format"]["rate"] = 16000
            await send(
                ws,
                "session.updated",
                session={"id": "mock-session", **config["session"]},
            )
            item = 0
            async for raw in ws:
                message = json.loads(raw)
                state.requests.append(message)
                kind = message["type"]
                if mode == "clear" and kind == "input_audio_buffer.append":
                    await send(ws, "input_audio_buffer.speech_started", item_id="old")
                    await send(ws, PREFIX + "delta", item_id="old", delta="消す")
                if kind == "input_audio_buffer.clear":
                    await send(ws, "input_audio_buffer.cleared")
                    await send(
                        ws,
                        PREFIX + "completed",
                        item_id="old",
                        transcript="late",
                        stop="complete",
                    )
                if kind != "input_audio_buffer.commit":
                    continue
                if mode == "disconnect":
                    await ws.close()
                    return
                if mode == "large":
                    await ws.send("x" * (1024 * 1024 + 1))
                    continue
                item += 1
                item_id = str(item)
                await send(
                    ws,
                    "input_audio_buffer.committed",
                    item_id=item_id,
                    previous_item_id=None,
                )
                if mode == "pending":
                    continue
                for _ in range(40 if mode == "flood" else 1):
                    await send(ws, PREFIX + "delta", item_id=item_id, delta="途中")
                await send(
                    ws,
                    PREFIX + "completed",
                    item_id=item_id,
                    transcript="確定",
                    stop="complete",
                )
                await send(
                    ws,
                    PREFIX + "completed",
                    item_id=item_id,
                    transcript="duplicate",
                    stop="complete",
                )
        except ConnectionClosed:
            pass

    async with serve(handler, "127.0.0.1", 0, close_timeout=0.1) as ws_server:
        yield f"http://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}", state


async def until(predicate, timeout=1):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def test_protocol_config_audio_and_duplicate_final(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("WS_PROXY", "http://127.0.0.1:1")

    async def run():
        async with mock_server() as (url, server):
            client = module().SpeechCppRealtime(
                url, "asr", "ja", "mic", server_vad=False
            )
            await client.start()
            config = server.requests[0]["session"]
            assert config["type"] == "transcription"
            assert config["audio"]["input"] == {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": {"model": "asr", "language": "ja"},
                "turn_detection": None,
                "noise_reduction": None,
            }
            pcm = b"\1\0" * 480
            await client.feed(AudioFrame(pcm, 24000), time.monotonic_ns())
            await client.commit()
            one = await asyncio.wait_for(client.next_update(), 1)
            two = await asyncio.wait_for(client.next_update(), 1)
            assert not one.is_final and two.is_final and two.text == "確定"
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(client.next_update(), 0.05)
            append = next(
                r for r in server.requests if r["type"] == "input_audio_buffer.append"
            )
            assert base64.b64decode(append["audio"]) == pcm
            await client.stop()
            assert client.state == "closed"
            with pytest.raises(module().RealtimeError):
                await client.next_update()

    asyncio.run(run())


def test_sources_and_explicit_reconnect_use_separate_namespaces():
    async def run():
        async with mock_server() as (url, _):
            clients = [
                module().SpeechCppRealtime(url, "asr", "ja", s, server_vad=False)
                for s in ("mic", "speaker", "mic")
            ]
            identities = []
            for c in clients:
                await c.start()
                await c.commit()
                await c.next_update()
                u = await c.next_update()
                identities.append((u.source, u.namespace, u.item_id))
                await c.stop()
                with pytest.raises(module().RealtimeError):
                    await c.start()
            assert len(set(identities)) == 3

    asyncio.run(run())


def test_clear_barrier_discards_late_final_and_allows_new_utterance():
    async def run():
        async with mock_server("clear") as (url, _):
            c = module().SpeechCppRealtime(url, "asr", "ja", "mic", server_vad=False)
            await c.start()
            await c.feed(AudioFrame(b"\1\0" * 480, 24000), time.monotonic_ns())
            assert (await c.next_update()).text == "消す"
            await c.clear()
            assert (await c.next_update()).state == "discarded"
            await c.commit()
            assert not (await c.next_update()).is_final
            assert (await c.next_update()).text == "確定"
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(c.next_update(), 0.05)
            await c.stop()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["bad_config", "config_error", "no_config"])
def test_configuration_must_be_acknowledged_before_audio(mode):
    async def run():
        async with mock_server(mode) as (url, server):
            c = module().SpeechCppRealtime(url, "asr", "ja", "mic")
            with pytest.raises(module().RealtimeError) as caught:
                await c.start()
            assert "private" not in str(caught.value)
            assert c.state == "failed"
            assert all(r["type"] == "session.update" for r in server.requests)

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["disconnect", "large", "flood", "pending"])
def test_transport_fault_or_unconsumed_results_closes_and_discards(mode, monkeypatch):
    async def run():
        async with mock_server(mode) as (url, _):
            monkeypatch.setattr(module(), "PENDING_TIMEOUT", 0.1)
            c = module().SpeechCppRealtime(url, "asr", "ja", "mic", server_vad=False)
            await c.start()
            await c.commit()
            await until(lambda: c.state == "failed")
            with pytest.raises(module().RealtimeError):
                await c.next_update()
            await c.stop()

    asyncio.run(run())


@pytest.mark.parametrize(
    "audio,age",
    [
        (AudioFrame(b"\0\0" * 480, 48000), 0),
        (AudioFrame(b"\0\0" * 480, 24000, 2), 0),
        (AudioFrame(b"\0\0" * 480, 24000), 300_000_000),
    ],
)
def test_wrong_format_or_old_frame_is_not_sent(audio, age):
    async def run():
        async with mock_server() as (url, server):
            c = module().SpeechCppRealtime(url, "asr", "ja", "mic")
            await c.start()
            with pytest.raises(module().RealtimeError):
                await c.feed(audio, time.monotonic_ns() - age)
            assert not any(
                r["type"] == "input_audio_buffer.append" for r in server.requests
            )
            assert c.state == "failed"

    asyncio.run(run())


def test_stop_interrupts_start_waiting_for_configuration():
    async def run():
        async with mock_server("no_config") as (url, server):
            c = module().SpeechCppRealtime(url, "asr", "ja", "mic")
            start = asyncio.create_task(c.start())
            await asyncio.wait_for(server.configured.wait(), 1)
            then = time.monotonic()
            await c.stop()
            assert time.monotonic() - then < 0.8
            await asyncio.gather(start, return_exceptions=True)
            assert c.state == "closed"

    asyncio.run(run())


def test_stop_interrupts_tcp_connect_backlog():
    async def run():
        with socket.socket() as listener, socket.socket() as queued:
            listener.bind(("127.0.0.1", 0))
            listener.listen(0)
            queued.settimeout(1)
            queued.connect(listener.getsockname())
            c = module().SpeechCppRealtime(
                f"http://127.0.0.1:{listener.getsockname()[1]}", "asr", "ja", "mic"
            )
            start = asyncio.create_task(c.start())
            await asyncio.sleep(0.05)
            then = time.monotonic()
            await c.stop()
            await asyncio.gather(start, return_exceptions=True)
            assert time.monotonic() - then < 0.8 and c.state == "closed"

    asyncio.run(run())


def test_redirect_never_reaches_another_server():
    async def run():
        calls = []

        async def target(ws):
            calls.append(True)

        async with serve(target, "127.0.0.1", 0) as other:
            port = other.sockets[0].getsockname()[1]

            def redirect(connection, request):
                return Response(
                    302, "Found", Headers({"Location": f"ws://127.0.0.1:{port}/"}), b""
                )

            async with serve(target, "127.0.0.1", 0, process_request=redirect) as first:
                c = module().SpeechCppRealtime(
                    f"http://127.0.0.1:{first.sockets[0].getsockname()[1]}",
                    "asr",
                    "ja",
                    "mic",
                )
                with pytest.raises(module().RealtimeError):
                    await c.start()
        assert calls == []

    asyncio.run(run())


def test_concurrent_feed_does_not_build_an_unbounded_queue(monkeypatch):
    async def run():
        async with mock_server() as (url, _):
            c = module().SpeechCppRealtime(url, "asr", "ja", "mic")
            await c.start()
            entered, release = asyncio.Event(), asyncio.Event()

            async def stalled(data):
                entered.set()
                await release.wait()

            monkeypatch.setattr(c._ws, "send", stalled)
            first = asyncio.create_task(
                c.feed(AudioFrame(b"\0\0" * 480, 24000), time.monotonic_ns())
            )
            await entered.wait()
            with pytest.raises(module().RealtimeError):
                await c.feed(AudioFrame(b"\0\0" * 480, 24000), time.monotonic_ns())
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            assert c.state == "failed"

    asyncio.run(run())
