"""Translated microphone speech is opt-in, bounded and independently cancellable."""

import pytest
from threading import Event
from time import monotonic_ns, sleep

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import AudioFrame, SpeechMessageEvent
from test_scheduler import Sink, event, until


def mic_event(identity="session:utterance", **kwargs):
    fields = dict(translated_text="Hello", source_language="ja", target_language="en")
    fields.update(kwargs)
    return SpeechMessageEvent(identity, "mic", "こんにちは", utterance_id=identity, **fields)


def test_mic_mode_is_independent_and_never_falls_back_to_original():
    settings = VoiceSettings.from_dict(dict(
        mic_mode="translated", routing="managed", multilingual_url="http://127.0.0.1:8081"))
    assert settings.mode == "off"
    assert settings.direct_policy == "suppress"
    assert VoiceSettings.from_dict(settings.to_dict()) == settings
    assert settings.request_for(mic_event()) == ("http://127.0.0.1:8081", "ryan", "en", "Hello")
    with pytest.raises(ValueError):
        settings.request_for(mic_event(translated_text=None))
    with pytest.raises(ValueError):
        VoiceSettings().request_for(mic_event())


@pytest.mark.parametrize("value", [
    {"mic_mode": "original"}, {"mic_mode": True}, {"direct_policy": "duck"},
    {"mic_mode": "translated", "output_device": "cable"},
    {"mic_mode": "translated", "direct_policy": "mix"},
])
def test_mic_settings_require_valid_mode_and_explicit_routing(value):
    with pytest.raises((ValueError, TypeError)):
        VoiceSettings.from_dict(value)


def test_external_mic_speech_requires_explicit_mixing_choice():
    settings = VoiceSettings.from_dict(dict(mic_mode="translated", direct_policy="mix", output_device="cable"))
    assert settings.playback_device == "cable"
    assert VoiceSettings.from_dict({}).mic_mode == "off"


def speech_settings(**kwargs):
    return VoiceSettings(mic_mode="translated", direct_policy="mix", output_device="cable", **kwargs)


def test_final_mic_translation_is_spoken_once_and_remote_partial_missing_are_rejected(pcm_server):
    sink = Sink()
    with pcm_server() as (url, requests):
        bus = VoiceEventBus(speech_settings(multilingual_url=url), router=AudioRouter(lambda *args: sink))
        try:
            for rejected in (mic_event(is_final=False), mic_event(translated_text=None),
                             event(source="speaker"), event(source="ocr"), event(source="remote")):
                assert not bus.publish(rejected)
            assert bus.publish(mic_event())
            assert not bus.publish(mic_event(revision=2))
            until(lambda: bus.status()["completed"] == 1)
            assert requests == [("/v1/audio/speech", {"input": "Hello", "voice": "ryan", "language": "en", "response_format": "pcm"})]
            assert b"".join(sink.data) == b"\x01\x00\x02\x00"
        finally:
            assert bus.close()


def test_mic_stop_interrupts_http_and_rejects_old_generation_but_preserves_chat(pcm_server):
    entered, release = Event(), Event()
    def stall_first(index):
        if not entered.is_set():
            entered.set()
            release.wait(2)
    sink = Sink()
    with pcm_server(before_chunk=stall_first) as (url, requests):
        bus = VoiceEventBus(speech_settings(mode="original", multilingual_url=url, japanese_url=url),
                            router=AudioRouter(lambda *args: sink))
        # Use Japanese translation so both requests legitimately share Irodori.
        mic = mic_event(translated_text="訳文", target_language="ja")
        try:
            generation = bus.source_generation("mic")
            assert bus.publish(mic, expected_source_generation=generation)
            assert entered.wait(1)
            assert bus.publish(event("chat"))
            bus.cancel_source("mic")
            assert not bus.publish(mic_event("late"), expected_source_generation=generation)
            until(lambda: bus.status()["completed"] == 1)
            assert [body["input"] for _, body in requests] == ["訳文", "こんにちは"]
            assert b"".join(sink.data) == b"\x01\x00\x02\x00"
            assert bus.status()["cancelled"] == 1
        finally:
            release.set()
            assert bus.close()


def test_mic_with_invalid_or_old_receipt_time_never_opens_output():
    bus = VoiceEventBus(speech_settings(multilingual_url="http://127.0.0.1:8081"))
    try:
        for stamp in (0, monotonic_ns() + 10_000_000_000):
            assert not bus.publish(mic_event(str(stamp), timestamp_ns=stamp))
        bus.publish(mic_event("old", timestamp_ns=monotonic_ns() - 6_000_000_000))
        until(lambda: bus.status()["dropped"] == 3)
        assert bus.status()["completed"] == 0
    finally:
        assert bus.close()


@pytest.mark.parametrize("overflow", [False, True])
def test_queued_chat_precedes_mic_and_overflow_evicts_oldest_mic(overflow):
    entered, release = Event(), Event()
    spoken = []
    class Provider:
        def __init__(self, url):
            pass
        def synthesize_stream(self, text, voice, language, token):
            spoken.append(text)
            if text == "active":
                entered.set()
                assert release.wait(2)
            token.check()
            yield AudioFrame(b"\x01\x00", 48000)
    bus = VoiceEventBus(speech_settings(mode="original", multilingual_url="http://localhost:8081"),
                        provider_factory=Provider, router=AudioRouter(lambda *args: Sink()), capacity=2)
    try:
        assert bus.publish(mic_event("active", translated_text="active"))
        assert entered.wait(1)
        assert bus.publish(mic_event("old", translated_text="old"))
        assert bus.publish(SpeechMessageEvent("chat", "chat", "chat", source_language="ja"))
        if overflow:
            assert bus.publish(mic_event("new", translated_text="new"))
        release.set()
        until(lambda: bus.status()["completed"] == 3)
        assert spoken == ["active", "chat", "new" if overflow else "old"]
        assert bus.status()["dropped"] == int(overflow)
    finally:
        release.set()
        assert bus.close()


def test_mic_cannot_evict_queued_chat_or_cancel_active_chat():
    entered, release = Event(), Event()
    spoken = []
    class Provider:
        def __init__(self, url):
            pass
        def synthesize_stream(self, text, voice, language, token):
            if not spoken:
                entered.set()
                assert release.wait(2)
            token.check()
            spoken.append(text)
            yield AudioFrame(b"\x01\x00", 48000)
    bus = VoiceEventBus(speech_settings(mode="original", multilingual_url="http://localhost:8081"),
                        provider_factory=Provider, router=AudioRouter(lambda *args: Sink()), capacity=2)
    try:
        for identity in ("active", "chat1", "chat2"):
            assert bus.publish(SpeechMessageEvent(identity, "chat", identity, source_language="ja"))
            assert entered.wait(1)
        assert not bus.publish(mic_event())
        bus.cancel_source("mic")
        release.set()
        until(lambda: bus.status()["completed"] == 3)
        assert spoken == ["active", "chat1", "chat2"]
        assert bus.status()["cancelled"] == 0
        assert bus.status()["dropped"] == 1
    finally:
        release.set()
        assert bus.close()


@pytest.mark.parametrize("delay", ["headers", "pcm", "output"])
def test_start_deadline_includes_inference_and_output_open(pcm_server, delay):
    entered, release = Event(), Event()
    sink = Sink()
    # The stall outlasts the wait below, so expiry must happen while the
    # server is still blocked; teardown releases it.
    def stall(*args):
        entered.set()
        release.wait(10)
    def output(*args):
        if delay == "output":
            stall()
        return sink
    with pcm_server(before_headers=stall if delay == "headers" else None,
                    before_chunk=stall if delay == "pcm" else None) as (url, _):
        bus = VoiceEventBus(speech_settings(multilingual_url=url), max_age=.15,
                            router=AudioRouter(output))
        try:
            assert bus.publish(mic_event())
            assert entered.wait(1)
            if delay == "output":
                sleep(.2)
                release.set()
            try:
                until(lambda: bus.status()["errors"] == 1, timeout=3)
            except AssertionError:
                raise AssertionError(f"expiry not reported: {bus.status()}") from None
            assert bus.status()["last_error"] == "speech_expired"
            assert sink.data == []
        finally:
            release.set()
            assert bus.close()


def test_start_deadline_never_truncates_started_speech(pcm_server):
    sink = Sink()
    def delayed_second(index):
        if index == 1:
            sleep(.25)
    with pcm_server(chunks=(b"\x01\x00", b"\x02\x00"), before_chunk=delayed_second) as (url, _):
        bus = VoiceEventBus(speech_settings(multilingual_url=url), max_age=.15,
                            router=AudioRouter(lambda *args: sink))
        try:
            assert bus.publish(mic_event())
            until(lambda: bus.status()["completed"] == 1)
            assert b"".join(sink.data) == b"\x01\x00\x02\x00"
            assert bus.status()["errors"] == 0
        finally:
            assert bus.close()


def test_silent_pcm_does_not_disable_start_deadline(pcm_server):
    sink = Sink()
    release = Event()
    def after_silence(index):
        if index == 1:
            release.wait(10)
    with pcm_server(chunks=(b"\x00\x00", b"\x01\x00"), before_chunk=after_silence) as (url, _):
        bus = VoiceEventBus(speech_settings(multilingual_url=url), max_age=.15,
                            router=AudioRouter(lambda *args: sink))
        try:
            assert bus.publish(mic_event())
            until(lambda: bus.status()["errors"] == 1, timeout=3)
            assert bus.status()["last_error"] == "speech_expired"
            assert b"".join(sink.data) == b"\x00\x00"
            assert bus.status()["last_first_write_ms"] is None
        finally:
            release.set()
            assert bus.close()
