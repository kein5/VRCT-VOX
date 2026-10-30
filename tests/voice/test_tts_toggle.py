"""TTS intent is independent of route mute and direct microphone capture."""

from threading import Event, Thread

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.tts.speechcpp_tts import SpeechCppTTS, SpeechError
from models.voice_events import AudioFrame
from test_scheduler import Sink as Sink, event as event, until as until
from test_direct_voice_controller import app as app, managed as managed, start as start
from test_controller_integration import controller_module as controller_module
from test_priority_cancel import (
    mainloop_module as mainloop_module,
    wire_message as wire_message,
)

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['app', 'mainloop_module']


def test_health_check_never_synthesizes(pcm_server):
    with pcm_server() as (url, requests):
        SpeechCppTTS(url).check_health()
        assert not requests


@pytest.mark.parametrize(
    "kwargs",
    [
        {"health_status": 503},
        {"health_body": b'{"status":"loading"}'},
        {"health_body": b"private path and transcript"},
        {"health_body": b"x" * 5000},
    ],
)
def test_health_failures_are_bounded_safe_codes(pcm_server, kwargs):
    with pcm_server(**kwargs) as (url, requests):
        with pytest.raises(SpeechError, match="^speech_server_not_ready$"):
            SpeechCppTTS(url).check_health()
        assert not requests


def test_disabled_bus_rejects_both_sources_until_explicit_enable():
    sink = Sink()

    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            yield AudioFrame(b"\x01\x00", 48000)

    bus = VoiceEventBus(
        VoiceSettings(mode="original", mic_mode="translated", output_device="cable"),
        enabled=False,
        provider_factory=Provider,
        router=AudioRouter(lambda *a: sink),
    )
    try:
        assert not bus.publish(event("off-chat"))
        assert not bus.publish(
            event(
                "off-mic",
                source="mic",
                translated_text="訳文",
                target_language="Japanese",
            )
        )
        old = bus.generation()
        assert bus.set_enabled(True, expected_generation=old)
        assert bus.publish(event("on-chat"))
        assert bus.publish(
            event(
                "on-mic",
                source="mic",
                translated_text="訳文",
                target_language="Japanese",
            )
        )
        until(lambda: bus.status()["completed"] == 2)
        assert b"".join(sink.data) == b"\x01\x00\x01\x00"
        bus.set_enabled(False)
        bus.set_muted(True)
        bus.set_muted(False)
        bus.configure(bus.settings)
        assert not bus.status()["tts_enabled"]
        assert not bus.publish(event("still-off"))
    finally:
        bus.close()


def test_off_cancels_active_and_queue_and_invalidates_delayed_enable():
    entered, release = Event(), Event()

    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            entered.set()
            release.wait(2)
            token.check()
            yield AudioFrame(b"\x01\x00", 48000)

    bus = VoiceEventBus(
        VoiceSettings(mode="original", output_device="cable"), provider_factory=Provider
    )
    try:
        bus.publish(event("active"))
        assert entered.wait(1)
        bus.publish(event("queued"))
        old = bus.status()["tts_generation"]
        assert bus.set_enabled(False)
        assert bus.status()["queued"] == 0
        assert bus.status()["tts_stopping"]
        assert not bus.set_enabled(True, expected_generation=old)
        newer = bus.status()["tts_generation"]
        bus.set_enabled(False)  # Repeated OFF still revokes queued enables.
        assert not bus.set_enabled(True, expected_generation=newer)
        assert bus.set_enabled(True, expected_generation=bus.generation())
        assert not bus.publish(event("late-final"), expected_generation=old)
        release.set()
        until(lambda: not bus.status()["active"])
        assert not bus.status()["tts_stopping"]
        assert bus.status()["cancelled"] == 1
    finally:
        release.set()
        bus.close()


def test_controller_starts_off_and_disable_never_stops_direct_input(app):
    c, backend, gate, _ = app
    assert c.getVoiceStatus()["result"]["tts_enabled"] is False
    managed(c)
    start(c)
    before = c.getDirectVoiceState()["result"]["generation"]
    c.disableTts()
    assert c.getDirectVoiceState()["result"]["active"]
    assert c.getDirectVoiceState()["result"]["generation"] == before
    assert backend.children[0].poll() is None


def test_enable_checks_generation_settings_and_health_without_resuming_mute(
    app, monkeypatch
):
    c, _, gate, module = app
    initial_native_mute = gate.muted
    generation = c.voice_events.generation()
    assert (
        c.enableTts({"generation": generation})["status"] == 409
    )  # No source mode selected.
    c.setVoiceSettings({"mode": "original", "output_device": "cable"})
    c.voice_events.set_muted(False)
    checked = []
    monkeypatch.setattr(
        module.SpeechCppTTS, "check_health", lambda self: checked.append(self.base_url)
    )
    assert c.enableTts({"generation": generation})["status"] == 409
    assert not checked
    assert c.enableTts({"generation": c.voice_events.generation()})["status"] == 200
    assert checked == ["http://127.0.0.1:8080"]
    assert c.voice_events.status()["tts_enabled"]
    c.disableTts()
    c.voice_events.set_muted(True)
    assert c.enableTts({"generation": c.voice_events.generation()})["status"] == 409
    assert (
        c.voice_events.status()["muted"] and not c.voice_events.status()["tts_enabled"]
    )
    assert gate.muted is initial_native_mute  # No native route operation.


def test_disable_during_health_check_cannot_be_undone_by_delayed_enable(
    app, monkeypatch
):
    c, _, _, module = app
    entered, release = Event(), Event()
    c.setVoiceSettings({"mode": "original", "output_device": "cable"})
    c.voice_events.set_muted(False)

    def health(self):
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(module.SpeechCppTTS, "check_health", health)
    result = []
    worker = Thread(
        target=lambda: result.append(
            c.enableTts({"generation": c.voice_events.generation()})
        )
    )
    worker.start()
    try:
        assert entered.wait(1)
        assert c.disableTts()["status"] == 200
        release.set()
        worker.join(2)
        assert result[0]["status"] == 409
        assert not c.voice_events.status()["tts_enabled"]
    finally:
        release.set()
        worker.join(2)


@pytest.mark.parametrize(
    "data", [None, {}, {"generation": True}, {"generation": -1}, {"generation": "0"}]
)
def test_bad_toggle_request_never_enables(app, data):
    c, *_ = app
    assert c.enableTts(data)["status"] == 400
    assert not c.voice_events.status()["tts_enabled"]


def test_disable_receiver_bypasses_ordinary_work(mainloop_module, monkeypatch):
    from queue import Queue

    m = mainloop_module
    entered, release, disabled = Event(), Event(), Event()
    pending = Queue()

    def busy(data):
        entered.set()
        release.wait(2)
        return {"status": 200, "result": None}

    def stop(data):
        result = m.controller.disableTts()
        disabled.set()
        return result

    main = m.Main(
        m.controller,
        {
            "/busy": {"status": True, "variable": busy},
            "/run/disable_tts": {"status": True, "variable": stop},
        },
    )
    monkeypatch.setattr(
        m.sys, "stdin", type("Input", (), {"readline": lambda self: pending.get()})()
    )
    # Receiver is deliberately started without ordinary workers.
    main.startReceiver()
    try:
        pending.put(wire_message("/busy"))
        pending.put(wire_message("/run/disable_tts"))
        assert disabled.wait(0.5), "disable was queued instead of handled immediately"
        assert not entered.is_set()
        assert not m.controller.voice_events.status()["tts_enabled"]
    finally:
        main._stop_event.set()
        release.set()
        pending.put("")
        for thread in main._threads:
            thread.join(2)
