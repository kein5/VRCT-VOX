"""Session ownership tests never instantiate an OS capture device."""

import asyncio
import importlib
from queue import Queue, Empty
from threading import Event, Thread
import time
from uuid import uuid4

import pytest

from models.audio_routing.source_bridge import Endpoint
from models.transcription.realtime_audio import CapturedAudio
from models.transcription.realtime_events import TranscriptUpdate
from models.transcription.speechcpp_asr import RecognitionModel
from models.voice_events import AudioFrame


def eventually(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "session did not reach expected state"
        time.sleep(0.005)


class Dependencies:
    def __init__(self):
        self.clients, self.captures = [], []
        self.start_release = Event()
        self.start_release.set()
        self.preflight_release = Event()
        self.preflight_release.set()
        self.start_error = False
        self.capture_error = False
        self.capture_started = Event()
        self.capture_release = Event()
        self.capture_release.set()
        self.models = (RecognitionModel("asr", ("ja",), True),)
        self.preflight_started = Event()

    def rest(self, url, timeout):
        owner = self

        class REST:
            def recognizers(self, cancel_token):
                owner.preflight_started.set()
                while not owner.preflight_release.wait(0.005):
                    cancel_token.check()
                return owner.models

        return REST()

    def client(self, url, model, language, source, options=None):
        owner = self

        class Client:
            namespace = uuid4().hex
            state = "new"
            error = None

            def __init__(self):
                self.incoming = Queue()
                self.feed_count = 0
                self.stopped = Event()

            async def start(self):
                while not owner.start_release.is_set():
                    await asyncio.sleep(0.005)
                if owner.start_error:
                    raise RuntimeError("private server body")
                self.state = "ready"

            async def stop(self):
                self.state = "closed"
                self.stopped.set()

            async def feed(self, audio, captured_ns):
                assert audio.sample_rate == 24000 and audio.channels == 1
                self.feed_count += 1

            async def next_update(self):
                while self.state != "closed":
                    try:
                        event = self.incoming.get_nowait()
                        if isinstance(event, Exception):
                            raise event
                        return event
                    except Empty:
                        await asyncio.sleep(0.005)
                raise RuntimeError("closed")

        c = Client()
        self.clients.append(c)
        return c

    def capture(self, endpoint, source, on_audio, on_error):
        owner = self

        class Capture:
            def __init__(self):
                self.ended = Event()
                self.thread = None

            def start(self):
                owner.capture_started.set()
                while not owner.capture_release.wait(0.005):
                    if self.ended.is_set():
                        return
                if owner.capture_error:
                    raise RuntimeError("private device path")

                def feed():
                    while not self.ended.wait(0.02):
                        if (
                            on_audio(
                                CapturedAudio(
                                    AudioFrame(b"\0" * 1920, 48000),
                                    time.monotonic_ns() - 20_000_000,
                                )
                            )
                            is False
                        ):
                            break

                self.thread = Thread(target=feed, daemon=True)
                self.thread.start()

            def request_stop(self):
                self.ended.set()

            def stop(self):
                self.request_stop()
                if self.thread:
                    self.thread.join(0.5)

        capture = Capture()
        self.captures.append(capture)
        return capture


def session(monkeypatch, source="mic", dependencies=None):
    m = importlib.import_module("models.transcription.realtime_session")
    settings = importlib.import_module("models.transcription.realtime_settings")
    deps = dependencies or Dependencies()
    monkeypatch.setattr(m, "SpeechCppASR", deps.rest)
    endpoint = Endpoint(
        1, 2, "selected", "Audio/Source" if source == "mic" else "Audio/Sink"
    )
    instance = m.RealtimeSession(
        source,
        settings.SessionOptions("http://127.0.0.1:8080", "asr", "ja"),
        endpoint,
        capture_factory=deps.capture,
        client_factory=deps.client,
    )
    return instance, deps


def test_updates_keep_namespace_source_and_stop_discards_queued_results(monkeypatch):
    s, d = session(monkeypatch)
    try:
        s.start()
        eventually(lambda: s.health()["state"] == "ready")
        c = d.clients[0]
        eventually(lambda: c.feed_count > 0)
        assert s.is_current(c.namespace)
        partial = TranscriptUpdate(
            "mic", c.namespace, "u1", 1, "part", False, "partial"
        )
        final = TranscriptUpdate("mic", c.namespace, "u1", 2, "final", True, "final")
        c.incoming.put(partial)
        c.incoming.put(final)
        assert s.pop_update(timeout=1) == partial
        assert s.pop_update(timeout=1) == final
        c.incoming.put(
            TranscriptUpdate("mic", c.namespace, "u2", 1, "queued", True, "final")
        )
        time.sleep(0.03)
        s.request_stop()
        assert not s.is_current(c.namespace) and s.pop_update(timeout=0.01) is None
        assert (
            s.close()
            and c.stopped.is_set()
            and all(c.ended.is_set() for c in d.captures)
        )
        with pytest.raises(RuntimeError):
            s.start()
    finally:
        s.close()


def test_two_sources_are_independent(monkeypatch):
    a, da = session(monkeypatch, "mic")
    b, db = session(monkeypatch, "speaker")
    try:
        a.start()
        b.start()
        eventually(lambda: a.health()["state"] == b.health()["state"] == "ready")
        assert a.health()["namespace"] != b.health()["namespace"]
        a.request_stop()
        assert a.close()
        assert b.health()["state"] == "ready" and b.is_current(db.clients[0].namespace)
        assert all(c.ended.is_set() for c in da.captures)
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("stage", ["preflight", "client", "capture"])
def test_stop_during_start_invalidates_without_waiting_for_initialization(
    monkeypatch, stage
):
    d = Dependencies()
    if stage == "preflight":
        d.preflight_release.clear()
    if stage == "client":
        d.start_release.clear()
    if stage == "capture":
        d.capture_release.clear()
    s, d = session(monkeypatch, dependencies=d)
    try:
        s.start()
        assert d.preflight_started.wait(1)
        if stage == "client":
            eventually(lambda: bool(d.clients))
        if stage == "capture":
            assert d.capture_started.wait(1)
        began = time.monotonic()
        s.request_stop()
        assert time.monotonic() - began < 0.1
        assert s.pop_update(timeout=0.01) is None
        assert s.close(timeout=1)
        assert all(c.stopped.is_set() for c in d.clients)
        assert all(c.ended.is_set() for c in d.captures)
    finally:
        d.start_release.set()
        d.preflight_release.set()
        d.capture_release.set()
        s.close()


@pytest.mark.parametrize(
    "fault",
    ["model", "language", "client_start", "capture_start", "disconnect", "overflow"],
)
def test_failure_stops_owned_resources_and_redacts_errors(monkeypatch, fault):
    s, d = session(monkeypatch)
    if fault == "model":
        d.models = ()
    if fault == "language":
        d.models = (RecognitionModel("asr", ("en",), True),)
    if fault == "client_start":
        d.start_error = True
    if fault == "capture_start":
        d.capture_error = True
    try:
        s.start()
        if fault in ("disconnect", "overflow"):
            eventually(lambda: s.health()["state"] == "ready")
            c = d.clients[0]
            if fault == "disconnect":
                c.incoming.put(RuntimeError("private server body"))
            else:
                for i in range(33):
                    c.incoming.put(
                        TranscriptUpdate(
                            "mic", c.namespace, str(i), 1, "data", True, "final"
                        )
                    )
        eventually(lambda: s.health()["state"] == "failed")
        assert s.pop_update(timeout=0.01) is None
        assert "private" not in str(s.health())
        assert s.close()
        assert all(c.stopped.is_set() for c in d.clients)
        assert all(c.ended.is_set() for c in d.captures)
    finally:
        s.close()


def test_stop_before_start_is_terminal(monkeypatch):
    s, d = session(monkeypatch)
    s.request_stop()
    assert s.close()
    with pytest.raises(RuntimeError):
        s.start()
    assert not d.clients and not d.captures


@pytest.mark.parametrize("mode", ["clear", "no_config"])
def test_real_transport_owner_can_stop_while_streaming_or_connecting(monkeypatch, mode):
    from test_speechcpp_realtime import mock_server
    from models.transcription.speechcpp_realtime import SpeechCppRealtime

    m = importlib.import_module("models.transcription.realtime_session")
    settings = importlib.import_module("models.transcription.realtime_settings")
    d = Dependencies()
    monkeypatch.setattr(m, "SpeechCppASR", d.rest)

    async def run():
        async with mock_server(mode) as (url, server):
            s = m.RealtimeSession(
                "mic",
                settings.SessionOptions(url, "asr", "ja"),
                Endpoint(1, 2, "selected", "Audio/Source"),
                capture_factory=d.capture,
                client_factory=SpeechCppRealtime,
            )
            try:
                s.start()
                await asyncio.wait_for(server.configured.wait(), 2)
                if mode == "clear":
                    update = await asyncio.to_thread(s.pop_update, 2)
                    assert update and update.state == "partial"
                    assert 0 < update.received_ns <= time.monotonic_ns()
                s.request_stop()
                assert await asyncio.to_thread(s.close, 2)
                assert s.pop_update(0.01) is None
                assert all(c.ended.is_set() for c in d.captures)
            finally:
                await asyncio.to_thread(s.close)

    asyncio.run(run())


def test_repeated_close_preserves_terminal_health(monkeypatch):
    s, _ = session(monkeypatch)
    try:
        s.start()
        eventually(lambda: s.health()['state'] == 'ready')
        assert s.close()
        assert s.health()['state'] == 'closed'
        assert s.close()
        assert s.health()['state'] == 'closed'
    finally:
        s.close()
