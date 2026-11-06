"""Offline regressions for provider timeouts, language selection and replies."""

from contextlib import contextmanager
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests
from openai import OpenAI
from speech_recognition import AudioData

from errors import AudioPipelineError, ErrorCode
from models.message_pipeline import (
    CHAT_MESSAGE_SPEC, MIC_MESSAGE_SPEC, OCR_MESSAGE_SPEC,
    REALTIME_MIC_SPEC, REALTIME_SPEAKER_SPEC, SPEAKER_MESSAGE_SPEC,
)
from models.message_snapshot import MessageSnapshot
from models.transcription import transcription_providers as providers
from models.transcription.transcription_transcriber import AudioTranscriber


AUDIO = AudioData(b"\x00\x00" * 160, 16000, 2)
OPTIONS = dict(avg_logprob=-0.8, no_speech_prob=0.6, no_repeat_ngram_size=0, force_language=False)
SECRET = "private-provider-response"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Use an in-memory provider transport")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def _deepgram_payload(language="en", text="hello", confidence=0.9):
    return {"results": {"channels": [{
        "detected_language": language,
        "alternatives": [{"transcript": text, "confidence": confidence}],
    }]}}


@contextmanager
def _provider(engine, detected_language, *, model="whisper-1"):
    """Use real adapters with a fake model or an in-memory HTTP response."""
    if engine == "Whisper":
        model_stub = MagicMock()
        model_stub.transcribe.return_value = (
            [SimpleNamespace(text="hello", avg_logprob=-0.1, no_speech_prob=0.1)],
            SimpleNamespace(language=detected_language, language_probability=0.9),
        )
        yield providers.LocalWhisperProvider(model_stub), model_stub.transcribe
    elif engine == "Deepgram":
        response = requests.Response()
        response.status_code = 200
        response.json = lambda: _deepgram_payload(detected_language)
        with patch.object(providers.requests, "post", return_value=response) as post:
            yield providers.DeepgramProvider("test-key", "nova-3", ["ja", "en"]), post
    else:
        response = {"text": "hello"}
        if detected_language is not None:
            response["language"] = detected_language
        if model == "whisper-1":
            response.update(task="transcribe", duration=0.01)
        handler = MagicMock(side_effect=lambda request: httpx.Response(200, json=response))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with patch.object(providers, "api_http_client", return_value=client):
                provider = providers.OpenAICompatibleTranscriptionProvider(
                    "test-key", "https://asr.example/v1", model, engine,
                )
            yield provider, handler


def _transcribe(provider, engine, languages=None, countries=None):
    transcriber = AudioTranscriber(False, None, 3, 10, "Google")
    transcriber.transcription_engine = engine
    transcriber.audio_sources["process_data_func"] = lambda: AUDIO
    with patch.object(transcriber, "_resolve_provider", return_value=provider):
        transcriber._finalizeAndTranscribe(
            languages or ["Japanese", "English"], countries or ["Japan", "United States"],
            -0.8, 0.6, 0,
        )
    return transcriber


@pytest.mark.parametrize("engine", ["Whisper", "Deepgram", "OpenAI_Whisper", "Groq_Whisper", "Custom_Whisper"])
@pytest.mark.parametrize("detected_language", ["en", " English ", "EN_us"])
def test_detected_english_maps_to_second_candidate(engine, detected_language):
    with _provider(engine, detected_language) as (provider, call):
        transcriber = _transcribe(provider, engine)
    assert transcriber.getTranscript()["language"] == "English"
    assert call.call_count == 1


@pytest.mark.parametrize("engine", ["Whisper", "Deepgram", "OpenAI_Whisper"])
@pytest.mark.parametrize("detected_language", [None, "", "unrecognized-code", "fr"])
def test_unavailable_or_unselected_detection_does_not_label_first_candidate(engine, detected_language):
    with _provider(engine, detected_language) as (provider, call):
        transcriber = _transcribe(provider, engine)
    result = transcriber.getTranscript()
    assert result["text"] == "hello"
    assert result["language"] is None
    assert call.call_count == 1


def test_json_only_openai_response_preserves_unknown_language():
    with _provider("OpenAI_Whisper", None, model="gpt-4o-transcribe") as (provider, call):
        result = _transcribe(provider, "OpenAI_Whisper").getTranscript()
    assert result["text"] == "hello"
    assert result["language"] is None
    assert call.call_count == 1


@pytest.mark.parametrize("spec,expected", [
    (MIC_MESSAGE_SPEC, None), (SPEAKER_MESSAGE_SPEC, None),
    (CHAT_MESSAGE_SPEC, "Japanese"), (OCR_MESSAGE_SPEC, "Japanese"),
    (REALTIME_MIC_SPEC, "Japanese"), (REALTIME_SPEAKER_SPEC, "Japanese"),
])
def test_message_language_selection_preserves_unknown_batch_asr_language(spec, expected):
    config = SimpleNamespace(
        SELECTED_TAB_NO="1",
        SELECTED_YOUR_LANGUAGES={"1": {"1": {"language": "Japanese"}}},
        SELECTED_TARGET_LANGUAGES={"1": {"1": {"language": "Japanese"}}},
        ENABLE_TRANSLATION=True, SELECTED_TRANSLATION_ENGINES={"1": "OpenAI_API"},
        CTRANSLATE2_WEIGHT_TYPE="m2m100_418M", CONVERT_MESSAGE_TO_HIRAGANA=False,
        CONVERT_MESSAGE_TO_ROMAJI=False, SEND_ONLY_TRANSLATED_MESSAGES=False,
        OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES=False,
        SEND_MESSAGE_FORMAT_PARTS={}, RECEIVED_MESSAGE_FORMAT_PARTS={},
    )
    assert MessageSnapshot.capture(config, spec, None).source_language == expected
    assert MessageSnapshot.capture(config, spec, "English").source_language == "English"


@pytest.mark.parametrize("engine", ["Whisper", "Deepgram", "OpenAI_Whisper"])
def test_explicit_single_language_survives_missing_detection(engine):
    with _provider(engine, None) as (provider, call):
        result = _transcribe(provider, engine, ["Japanese"], ["Japan"]).getTranscript()
    assert result["language"] == "Japanese"
    assert call.call_count == 1


@pytest.mark.parametrize("detected_language,expected", [
    ("ZH_hant_TW", "Chinese Traditional"),
    ("zh-TW", "Chinese Traditional"),
    ("zh-Hant", "Chinese Traditional"),
    ("Chinese Traditional", "Chinese Traditional"),
    ("cmn-Hans-CN", "Chinese Simplified"),
    ("chinese", "Chinese Simplified"),
    ("cantonese", "Chinese Traditional"),
])
def test_detected_language_uses_selected_country_and_normalized_names(detected_language, expected):
    country = "Hong Kong" if detected_language == "cantonese" else "Taiwan"
    with _provider("Deepgram", detected_language) as (provider, _):
        result = _transcribe(provider, "Deepgram",
                             ["Chinese Simplified", "Chinese Traditional"], ["China", country]).getTranscript()
    assert result["language"] == expected


@pytest.mark.parametrize("confidence", [0.9, 0.5, 0.0])
def test_definitive_result_replaces_previous_candidate_even_with_lower_confidence(confidence):
    provider = MagicMock()
    provider.transcribe.side_effect = [("wrong", 0.9, False, "ja"), ("hello", confidence, True, "en")]
    result = _transcribe(provider, "Whisper").getTranscript()
    assert result["text"] == "hello"
    assert result["language"] == "English"


def test_google_still_compares_explicit_candidates_by_confidence():
    recognizer = MagicMock()
    recognizer.recognize_google.side_effect = [("wrong", 0.2), ("hello", 0.9)]
    result = _transcribe(providers.GoogleProvider(recognizer), "Google").getTranscript()
    assert result["language"] == "English"
    assert [call.kwargs["language"] for call in recognizer.recognize_google.call_args_list] == ["ja-JP", "en-US"]


def test_deepgram_auto_fallback_does_not_claim_forced_language():
    response = MagicMock(status_code=200)
    response.json.return_value = _deepgram_payload(language=None)
    provider = providers.DeepgramProvider("test-key", "nova-3", ["multi"])
    with patch.object(providers.requests, "post", return_value=response) as post:
        result = _transcribe(provider, "Deepgram", ["Japanese"], ["Japan"]).getTranscript()
    assert result["text"] == "hello"
    assert result["language"] is None
    assert post.call_args.kwargs["params"] == {"model": "nova-3", "detect_language": "true"}


@pytest.mark.parametrize("base_url", ["https://api.openai.com/v1", "https://api.groq.com/openai/v1", "http://127.0.0.1:8000/v1"])
def test_sdk_multipart_upload_has_bounded_write_timeout(base_url):
    requests_seen = []

    def stalled_upload(request):
        requests_seen.append(request)
        assert request.url.path.endswith("/audio/transcriptions")
        assert b"audio.wav" in request.read()
        assert request.extensions["timeout"] == {"connect": 10, "read": 60, "write": 60, "pool": 10}
        raise httpx.WriteTimeout(SECRET, request=request)

    # Keep api_http_client and the SDK real; replace only the socket transport.
    with patch.object(httpx.HTTPTransport, "handle_request", side_effect=stalled_upload), \
         patch.object(httpx.Client, "_get_proxy_map", return_value={}):
        provider = providers.OpenAICompatibleTranscriptionProvider("test-key", base_url, "whisper-1", "Custom_Whisper")
        provider._client.max_retries = 0
        try:
            assert isinstance(provider._client, OpenAI)
            assert provider._client._client.follow_redirects is False
            assert provider._client._client.trust_env is (not base_url.startswith("http://127."))
            with pytest.raises(providers.TranscriptionApiError) as caught:
                provider.transcribe(AUDIO, "English", "United States", **OPTIONS)
            assert caught.value.error_code == ErrorCode.TRANSCRIPTION_API_TIMEOUT
            assert str(caught.value) == ErrorCode.TRANSCRIPTION_API_TIMEOUT.value
            assert len(requests_seen) == 1
        finally:
            provider._client.close()


MALFORMED_PAYLOADS = [
    {"error": SECRET}, {"results": {"channels": []}}, None, [],
    {"results": None}, {"results": {"channels": None}},
    {"results": {"channels": [None]}},
    {"results": {"channels": [{"alternatives": []}]}},
    {"results": {"channels": [{"alternatives": [None]}]}},
    {"results": {"channels": [{"alternatives": [{}]}]}},
    _deepgram_payload(text=None), _deepgram_payload(text=123),
    _deepgram_payload(confidence=SECRET), _deepgram_payload(confidence=None),
    _deepgram_payload(confidence=float("nan")), _deepgram_payload(confidence=float("inf")),
    _deepgram_payload(confidence=-0.1), _deepgram_payload(confidence=1.1),
    _deepgram_payload(confidence=True),
]


@pytest.mark.parametrize("payload", MALFORMED_PAYLOADS)
def test_malformed_deepgram_success_raises_sanitized_provider_error(payload):
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    provider = providers.DeepgramProvider("test-key", "nova-3")
    with patch.object(providers.requests, "post", return_value=response), \
         patch.object(providers, "errorLogging") as log:
        with pytest.raises(providers.TranscriptionApiError) as caught:
            provider.transcribe(AUDIO, "Japanese", "Japan", **OPTIONS)
    assert caught.value.error_code == ErrorCode.TRANSCRIPTION_API_SERVER_ERROR
    assert str(caught.value) == ErrorCode.TRANSCRIPTION_API_SERVER_ERROR.value
    assert caught.value.__suppress_context__
    log.assert_called_once_with(provider="Deepgram")


def test_invalid_deepgram_json_raises_sanitized_provider_error():
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError(SECRET)
    with patch.object(providers.requests, "post", return_value=response):
        with pytest.raises(providers.TranscriptionApiError) as caught:
            providers.DeepgramProvider("test-key", "nova-3").transcribe(AUDIO, "Japanese", "Japan", **OPTIONS)
    assert str(caught.value) == ErrorCode.TRANSCRIPTION_API_SERVER_ERROR.value


def test_malformed_deepgram_success_reaches_pipeline_error_state():
    response = MagicMock(status_code=200)
    response.json.return_value = {"error": SECRET}
    transcriber = AudioTranscriber(False, None, 3, 10, "Deepgram", api_key="test-key", api_model="nova-3")
    transcriber.audio_sources["process_data_func"] = lambda: AUDIO
    with patch.object(providers.requests, "post", return_value=response), \
         patch("utils.error_logger") as logger:
        with pytest.raises(AudioPipelineError):
            transcriber._finalizeAndTranscribe(["Japanese"], ["Japan"], -0.8, 0.6, 0)
    assert transcriber.last_recognition_error
    assert transcriber.last_api_error_code == ErrorCode.TRANSCRIPTION_API_SERVER_ERROR
    assert not transcriber.hasTranscript()
    assert logger.error.called
    assert SECRET not in str(logger.error.call_args_list)
    assert "test-key" not in str(logger.error.call_args_list)


def test_valid_deepgram_silence_is_not_a_pipeline_error():
    response = MagicMock(status_code=200)
    response.json.return_value = _deepgram_payload(text="", confidence=0.0)
    with patch.object(providers.requests, "post", return_value=response):
        transcriber = _transcribe(providers.DeepgramProvider("test-key", "nova-3"), "Deepgram")
    assert not transcriber.last_recognition_error
    assert transcriber.last_api_error_code is None
    assert not transcriber.hasTranscript()
