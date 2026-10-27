from threading import Event, Thread
from time import monotonic

import pytest

from models.tts.settings import VoiceSettings, local_url
from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS, SpeechError
from models.voice_events import SpeechMessageEvent


def test_pcm_contract_and_odd_http_boundaries(pcm_server):
    with pcm_server() as (url, requests):
        frames = list(SpeechCppTTS(url).synthesize_stream("こんにちは", "none", "ja", CancelToken()))
    assert b"".join(f.pcm for f in frames) == b"\x01\x00\x02\x00"
    assert all(f.sample_rate == 48000 and f.channels == 1 for f in frames)
    assert requests == [("/v1/audio/speech", {"input": "こんにちは", "voice": "none",
                                           "language": "ja", "response_format": "pcm"})]


def test_audio_arrives_before_response_completes(pcm_server):
    release = Event()
    with pcm_server(chunks=(b"\x01\x00", b"\x02\x00"),
                    before_chunk=lambda i: release.wait(2) if i == 1 else None) as (url, _):
        stream = SpeechCppTTS(url).synthesize_stream("x", "none", "ja", CancelToken())
        try:
            assert next(stream).pcm == b"\x01\x00"
            assert not release.is_set()
        finally:
            release.set()
            stream.close()


@pytest.mark.parametrize("options,code", [
    ({"status": 400}, "http_400"), ({"status": 404}, "http_404"),
    ({"status": 500}, "http_500"), ({"status": 503}, "http_503"),
    ({"content_type": "audio/wav"}, "expected_pcm"),
    ({"rate": None}, "invalid_sample_rate"), ({"rate": "0"}, "invalid_sample_rate"),
    ({"rate": "bad"}, "invalid_sample_rate"), ({"rate": "999999"}, "invalid_sample_rate"),
    ({"chunks": (b"\x01",)}, "truncated_pcm"), ({"chunks": ()}, "empty_pcm"),
    ({"status": 302, "headers": {"Location": "https://example.com"}}, "http_302"),
    ({"truncate": True}, "transport_error"),
])
def test_protocol_errors(pcm_server, options, code):
    with pcm_server(**options) as (url, _):
        with pytest.raises(SpeechError, match=code):
            list(SpeechCppTTS(url).synthesize_stream("secret", "none", "ja", CancelToken()))


def test_cancel_interrupts_a_stalled_body(pcm_server):
    arrived, release = Event(), Event()
    def wait(_):
        arrived.set()
        release.wait(2)
    with pcm_server(before_chunk=wait) as (url, _):
        token = CancelToken()
        result = []
        def consume():
            try:
                list(SpeechCppTTS(url).synthesize_stream("x", "none", "ja", token))
            except SpeechError as exc:
                result.append(str(exc))
        worker = Thread(target=consume)
        worker.start()
        assert arrived.wait(1)
        started = monotonic()
        token.cancel()
        worker.join(0.5)
        release.set()
        assert not worker.is_alive()
        assert monotonic() - started < 0.5
        assert result == ["cancelled"]


def test_read_timeout(pcm_server):
    release = Event()
    with pcm_server(before_chunk=lambda i: release.wait(0.5)) as (url, _):
        try:
            with pytest.raises(SpeechError, match="transport_error"):
                list(SpeechCppTTS(url, timeout=0.05).synthesize_stream("x", "none", "ja", CancelToken()))
        finally:
            release.set()


def test_server_not_running(pcm_server):
    with pcm_server() as (url, _):
        pass
    with pytest.raises(SpeechError, match="transport_error"):
        list(SpeechCppTTS(url).synthesize_stream("x", "none", "ja", CancelToken()))


@pytest.mark.parametrize("url", ["http://example.com", "http://192.168.1.1:8080", "https://127.0.0.1",
    "http://user:pass@127.0.0.1", "http://127.0.0.1/a", "http://127.0.0.1?x=y", "http://0.0.0.0",
    "http://127.0.0.1:70000", "http://127.0.0.1:0", "http://127.0.0.1#fragment", "file:///tmp/audio"])
def test_local_only(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_defaults_and_language_routing():
    assert VoiceSettings.from_dict({}).mode == "off"
    settings = VoiceSettings.from_dict({"mode": "original", "output_device": "cable"})
    ja = SpeechMessageEvent("1", "chat", "こんにちは", source_language="Japanese")
    assert settings.request_for(ja)[1:3] == ("none", "ja")
    en = SpeechMessageEvent("2", "chat", "hello", source_language="English")
    with pytest.raises(ValueError):
        settings.request_for(en)
    settings = VoiceSettings.from_dict({**settings.to_dict(), "multilingual_url": "http://127.0.0.1:8081"})
    assert settings.request_for(en) == ("http://127.0.0.1:8081", "ryan", "en", "hello")
    settings = VoiceSettings.from_dict({**settings.to_dict(), "mode": "translated"})
    with pytest.raises(ValueError):
        settings.request_for(ja)  # no fallback to original


@pytest.mark.parametrize("value", [{"mode": True}, {"mode": "original"}, {"target_slot": "4"},
    {"japanese_url": "http://remote"}, {"japanese_voice": ""}, {"output_device": "bad\n"}, {"unknown": 1}, None])
def test_settings_validation(value):
    with pytest.raises((ValueError, TypeError)):
        VoiceSettings.from_dict(value)
