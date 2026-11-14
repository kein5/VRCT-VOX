"""Speech from engines the user installs: VOICEVOX, SHAREVOX, AivisSpeech, COEIROINK v2 (ADR-008).

Local fake servers stand in for the engines. They answer the way VOICEVOX ENGINE 0.26.1 and
COEIROINK 2.13.0 did on this project's test PC (their /openapi.json and real responses).
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from threading import Event, Thread
from time import monotonic
from urllib.parse import parse_qs, urlsplit
import wave

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.tts import external_engine
from models.tts.coeiroink_tts import CoeiroinkTTS
from models.tts.engines import engine_client
from models.tts.external_engine import EngineVoice, split_text
from models.tts.settings import VoiceSettings
from models.tts.speechcpp_tts import CancelToken, SpeechError
from models.tts.tts_scheduler import VoiceEventBus
from models.tts.voicevox_tts import VoicevoxTTS
from models.voice_events import AudioFrame
from test_scheduler import Sink, event, until

VOICEVOX_SPEAKERS = [
    {"name": "四国めたん", "speaker_uuid": "7ffcb7ce", "styles": [
        {"name": "ノーマル", "id": 2, "type": "streaming_talk"}, {"name": "あまあま", "id": 0, "type": "talk"}]},
    {"name": "ずんだもん", "speaker_uuid": "388f246b", "styles": [
        {"name": "ノーマル", "id": 3, "type": "streaming_talk"}, {"name": "ハミング", "id": 3001, "type": "frame_decode"}]},
]
COEIROINK_SPEAKERS = [{"speakerName": "つくよみちゃん", "speakerUuid": "3c37646f-3881-5374-2a83-149267990abc",
                       "styles": [{"styleName": "れいせい", "styleId": 0, "pathIcon": "C:\\x\\0.png"}]}]


def wav(samples=4800, rate=24000, width=2, channels=1, value=1):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(value.to_bytes(width, "little", signed=width > 1) * samples * channels)
    return stream.getvalue()


@contextmanager
def engine_server(kind, *, speakers=None, synthesis=None, stall=None):
    """`synthesis(text) -> (status, content_type, body)`; `stall` blocks a synthesis until set."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            requests.append(("GET", path, None))
            if kind == "voicevox" and path == "/version":
                return self.send(200, "application/json", b'"0.26.1"')
            if kind == "voicevox" and path == "/speakers":
                return self.send(200, "application/json", json.dumps(speakers or VOICEVOX_SPEAKERS).encode())
            if kind == "coeiroink" and path == "/v1/engine_info":
                return self.send(200, "application/json", b'{"device":"cpu","version":"2.13.0"}')
            if kind == "coeiroink" and path == "/v1/speakers_path_variant":
                return self.send(200, "application/json", json.dumps(speakers or COEIROINK_SPEAKERS).encode())
            self.send(404, "text/plain", b"not found")

        def do_POST(self):
            url = urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            requests.append(("POST", url.path, {**query, **(json.loads(body) if body else {})}))
            if kind == "voicevox" and url.path == "/audio_query":
                # The real query is a large JSON document; the client must hand it back unchanged.
                document = {"accent_phrases": [], "speedScale": 1.0, "kana": query["text"], "outputSamplingRate": 24000}
                return self.send(200, "application/json", json.dumps(document, ensure_ascii=False).encode())
            text = (json.loads(body)["kana"] if kind == "voicevox" else json.loads(body)["text"])
            if stall is not None:
                stall.wait(2)
            status, content_type, data = synthesis(text) if synthesis else (200, "audio/wav", wav())
            self.send(status, content_type, data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requests
    finally:
        server.shutdown()
        server.server_close()


# --- Splitting -------------------------------------------------------------------------------

def test_text_is_split_into_sentences_and_long_sentences_at_commas():
    assert split_text("こんにちは。元気ですか？\nはい!") == ["こんにちは。", "元気ですか？", "はい!"]
    long = "あ" * 30 + "、" + "い" * 30 + "、" + "う" * 10 + "。"
    pieces = split_text(long)
    assert "".join(pieces) == long and len(pieces) == 3
    assert all(len(piece) <= external_engine.MAX_PIECE for piece in pieces)
    short = "あ" * 10 + "、" + "い" * 10 + "、" + "う" * 10 + "。"
    assert split_text(short) == [short]  # A short sentence keeps its commas.
    assert split_text("  \n\n 。") == ["。"]
    assert split_text("区切りのない長い文" * 10) == ["区切りのない長い文" * 10]  # Never cut inside words.


# --- VOICEVOX family ---------------------------------------------------------------------------

def test_voicevox_lists_only_styles_that_read_text():
    with engine_server("voicevox") as (url, _):
        voices = VoicevoxTTS(url).list_voices()
    assert voices == [{"id": "2", "speaker": "四国めたん", "style": "ノーマル"},
                      {"id": "0", "speaker": "四国めたん", "style": "あまあま"},
                      {"id": "3", "speaker": "ずんだもん", "style": "ノーマル"}]


def test_voicevox_reads_each_sentence_and_hands_the_query_back_unchanged():
    with engine_server("voicevox") as (url, requests):
        frames = list(VoicevoxTTS(url).synthesize_stream(
            "こんにちは。今日は晴れ。", EngineVoice("3", "ずんだもん", "ノーマル"), "ja", CancelToken()))
    posts = [request for request in requests if request[0] == "POST"]
    assert [(path, body.get("text"), body.get("speaker")) for _, path, body in posts if path == "/audio_query"] == [
        ("/audio_query", "こんにちは。", "3"), ("/audio_query", "今日は晴れ。", "3")]
    synthesis = [body for _, path, body in posts if path == "/synthesis"]
    assert [body["kana"] for body in synthesis] == ["こんにちは。", "今日は晴れ。"]
    assert all(frame.sample_rate == 24000 and frame.channels == 1 for frame in frames)
    assert sum(len(frame.pcm) for frame in frames) == 2 * 4800 * 2
    assert max(len(frame.pcm) for frame in frames) <= int(24000 * external_engine.FRAME_SECONDS) * 2


@pytest.mark.parametrize("voice,expected", [
    (EngineVoice("3", "ずんだもん", "ノーマル"), "3"),
    (EngineVoice("99", "ずんだもん", "ノーマル"), "3"),  # The id changed in an engine update.
    (EngineVoice("2", "ずんだもん", "ノーマル"), "3"),  # The id now belongs to another voice.
    (EngineVoice("2"), "2"),  # No names saved: the id is all there is.
])
def test_a_saved_voice_is_found_by_id_or_by_its_names(voice, expected):
    with engine_server("voicevox") as (url, requests):
        list(VoicevoxTTS(url).synthesize_stream("あ。", voice, "ja", CancelToken()))
    assert {body["speaker"] for _, path, body in requests if path == "/audio_query"} == {expected}


@pytest.mark.parametrize("voice,code", [
    (EngineVoice("99", "いない", "ノーマル"), "tts_engine_voice_missing"),
    (EngineVoice("99"), "tts_engine_voice_missing"),
    (EngineVoice(""), "tts_engine_voice_unset"),
])
def test_a_voice_the_engine_no_longer_has_is_a_safe_error(voice, code):
    with engine_server("voicevox") as (url, requests):
        with pytest.raises(SpeechError, match=f"^{code}$"):
            list(VoicevoxTTS(url).synthesize_stream("あ。", voice, "ja", CancelToken()))
    assert not [request for request in requests if request[0] == "POST"]


@pytest.mark.parametrize("response,code", [
    ((500, "text/plain", b"secret text"), "http_500"),
    ((200, "text/html", b"<html>"), "tts_engine_synthesis_failed"),
    ((200, "audio/wav", b"RIFF broken"), "invalid_wav"),
    ((200, "audio/wav", wav(width=1)), "unsupported_wav"),
    ((200, "audio/wav", wav(samples=0)), "empty_pcm"),
    ((200, "audio/wav", wav(rate=4000)), "invalid_sample_rate"),
])
def test_bad_engine_answers_are_safe_codes(response, code):
    with engine_server("voicevox", synthesis=lambda text: response) as (url, _):
        with pytest.raises(SpeechError, match=f"^{code}$") as raised:
            list(VoicevoxTTS(url).synthesize_stream("秘密の文。", EngineVoice("3"), "ja", CancelToken()))
    assert "秘密" not in str(raised.value) and "secret" not in str(raised.value)


def test_a_message_longer_than_a_minute_of_audio_stops(monkeypatch):
    monkeypatch.setattr(external_engine, "MAX_AUDIO_SECONDS", 0.3)
    with engine_server("voicevox") as (url, _):
        with pytest.raises(SpeechError, match="audio_duration_limit"):
            list(VoicevoxTTS(url).synthesize_stream("一。二。", EngineVoice("3"), "ja", CancelToken()))


def test_an_engine_that_is_not_running_is_reported_as_not_ready():
    with engine_server("voicevox") as (url, _):
        pass
    client = VoicevoxTTS(url)
    with pytest.raises(SpeechError, match="^tts_engine_not_ready$"):
        client.check_health()
    with pytest.raises(SpeechError, match="^tts_engine_not_ready$"):
        list(client.synthesize_stream("あ。", EngineVoice("3"), "ja", CancelToken()))
    assert external_engine.probe(client) is False


def test_engines_read_japanese_only():
    with engine_server("voicevox") as (url, requests):
        with pytest.raises(SpeechError, match="tts_engine_language"):
            list(VoicevoxTTS(url).synthesize_stream("hello", EngineVoice("3"), "en", CancelToken()))
    assert not requests


def test_cancel_interrupts_a_synthesis_in_progress():
    stall = Event()
    with engine_server("voicevox", stall=stall) as (url, _):
        token, result = CancelToken(), []

        def consume():
            try:
                list(VoicevoxTTS(url).synthesize_stream("あ。", EngineVoice("3"), "ja", token))
            except SpeechError as error:
                result.append(str(error))

        worker = Thread(target=consume)
        worker.start()
        Event().wait(0.2)
        started = monotonic()
        token.cancel()
        worker.join(1)
        stall.set()
        assert not worker.is_alive() and monotonic() - started < 0.5
        assert result == ["cancelled"]


def synthesis_count(requests):
    return sum(1 for method, path, _ in requests if path == "/synthesis")


def test_the_next_sentence_is_synthesized_while_one_plays():
    with engine_server("voicevox") as (url, requests):
        stream = VoicevoxTTS(url).synthesize_stream("一つ目。二つ目。", EngineVoice("3"), "ja", CancelToken())
        try:
            next(stream)  # Playback holds the first sentence; nothing more is consumed.
            until(lambda: synthesis_count(requests) == 2, timeout=2)
        finally:
            stream.close()


def test_stopping_playback_stops_the_prefetch():
    with engine_server("voicevox") as (url, requests):
        stream = VoicevoxTTS(url).synthesize_stream("一。二。三。四。五。六。", EngineVoice("3"), "ja", CancelToken())
        next(stream)
        stream.close()
        Event().wait(0.5)
        assert synthesis_count(requests) <= 3  # The playing one, one queued, at most one in flight.


@pytest.mark.parametrize("url", ["http://192.168.1.5:50021", "https://127.0.0.1:50021", "http://example.com"])
def test_engines_are_reached_on_this_pc_only(url):
    with pytest.raises(ValueError):
        VoicevoxTTS(url)


# --- COEIROINK v2 ------------------------------------------------------------------------------

def test_coeiroink_lists_voices_without_their_portraits_and_sends_every_required_field():
    with engine_server("coeiroink") as (url, requests):
        client = CoeiroinkTTS(url)
        assert client.check_health() == "2.13.0"
        voice_id = "3c37646f-3881-5374-2a83-149267990abc:0"
        assert client.list_voices() == [{"id": voice_id, "speaker": "つくよみちゃん", "style": "れいせい"}]
        frames = list(client.synthesize_stream("こんにちは。", EngineVoice(voice_id, "つくよみちゃん", "れいせい"),
                                               "ja", CancelToken()))
    assert ("GET", "/v1/speakers", None) not in requests  # The ~1 MB list with base64 portraits.
    body = next(body for method, path, body in requests if path == "/v1/synthesis")
    assert body["speakerUuid"] == "3c37646f-3881-5374-2a83-149267990abc" and body["styleId"] == 0
    assert body["text"] == "こんにちは。"
    for field in ("volumeScale", "pitchScale", "intonationScale", "prePhonemeLength", "postPhonemeLength",
                  "outputSamplingRate", "speedScale"):
        assert field in body
    assert sum(len(frame.pcm) for frame in frames) == 4800 * 2


def test_the_factory_picks_the_api_of_each_engine():
    assert type(engine_client("voicevox", "http://127.0.0.1:50021")) is VoicevoxTTS
    assert type(engine_client("aivis", "http://127.0.0.1:10101")) is VoicevoxTTS
    assert type(engine_client("sharevox", "http://127.0.0.1:50025")) is VoicevoxTTS
    assert type(engine_client("coeiroink", "http://127.0.0.1:50032")) is CoeiroinkTTS
    with pytest.raises(ValueError):
        engine_client("speechcpp", "http://127.0.0.1:8080")


# --- Settings ---------------------------------------------------------------------------------

def test_settings_default_to_speechcpp_and_keep_older_files_readable():
    settings = VoiceSettings.from_dict({"mode": "original", "output_device": "cable"})
    assert settings.japanese_engine == "speechcpp" and settings.engine_voice_id == ""
    assert settings.voicevox_url == "http://127.0.0.1:50021" and settings.coeiroink_url == "http://127.0.0.1:50032"


def test_japanese_goes_to_the_chosen_engine_and_other_languages_stay_on_speechcpp():
    settings = VoiceSettings.from_dict({"mode": "original", "output_device": "cable", "japanese_engine": "voicevox",
                                        "engine_voice_id": "3", "engine_voice_speaker": "ずんだもん",
                                        "engine_voice_style": "ノーマル", "japanese_seed": "7",
                                        "multilingual_url": "http://127.0.0.1:8081"})
    url, voice, language, text = settings.request_for(event())
    assert (url, voice, language) == ("http://127.0.0.1:50021", EngineVoice("3", "ずんだもん", "ノーマル"), "ja")
    assert settings.engine_for("Japanese") == "voicevox" and settings.engine_for("English") == "speechcpp"
    assert settings.options_for("Japanese") == {}  # The seed is speech.cpp's.
    from models.voice_events import SpeechMessageEvent
    english = SpeechMessageEvent("en", "chat", "hello", source_language="English")
    assert settings.request_for(english) == ("http://127.0.0.1:8081", "ryan", "en", "hello")


def test_an_engine_without_a_chosen_voice_fails_with_a_code_the_ui_can_explain():
    settings = VoiceSettings.from_dict({"mode": "original", "output_device": "cable", "japanese_engine": "coeiroink"})
    with pytest.raises(SpeechError, match="^tts_engine_voice_unset$"):
        settings.request_for(event())


@pytest.mark.parametrize("value", [
    {"japanese_engine": "unknown"}, {"japanese_engine": "multilingual"},
    {"voicevox_url": "http://192.168.1.5:50021"}, {"coeiroink_url": "https://127.0.0.1:50032"},
    {"aivis_url": "http://127.0.0.1:10101/path"}, {"engine_voice_id": "1 or 1"},
    {"engine_voice_id": "x" * 80}, {"engine_voice_speaker": "bad\nname"}, {"engine_voice_style": "y" * 200},
])
def test_engine_settings_are_validated(value):
    with pytest.raises((ValueError, TypeError)):
        VoiceSettings.from_dict(value)


# --- Scheduler ---------------------------------------------------------------------------------

def test_the_scheduler_plays_japanese_through_the_engine_and_keeps_speechcpp_for_the_rest():
    sink, used = Sink(), []

    class SpeechCpp:
        def __init__(self, url):
            used.append(("speechcpp", url))

        def synthesize_stream(self, text, voice, language, token, **options):
            yield AudioFrame(b"\x01\x00", 48000)

    class Engine:
        def __init__(self, engine, url):
            used.append((engine, url))

        def synthesize_stream(self, text, voice, language, token, **options):
            assert voice == EngineVoice("3", "ずんだもん", "ノーマル") and options == {}
            yield AudioFrame(b"\x02\x00", 24000)

    settings = VoiceSettings(mode="original", output_device="cable", japanese_engine="voicevox",
                             engine_voice_id="3", engine_voice_speaker="ずんだもん", engine_voice_style="ノーマル")
    bus = VoiceEventBus(settings, provider_factory=SpeechCpp, engine_factory=Engine, router=AudioRouter(lambda *a: sink))
    try:
        assert bus.publish(event("ja"))
        until(lambda: bus.status()["completed"] == 1)
    finally:
        bus.close()
    assert used == [("voicevox", "http://127.0.0.1:50021")]
    assert b"".join(sink.data) == b"\x02\x00"
