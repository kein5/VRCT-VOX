"""F4 follow-up: preserve general diagnostics without exposing provider data."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIStatusError

from errors import VRCTError
from models.diagnostics import provider_errors, redact_diagnostic_text
import utils
from test.test_outbound_network_policy import LLMS


@pytest.fixture
def logger(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(utils, "error_logger", logger)
    return logger


@pytest.fixture
def configured_secrets(monkeypatch):
    values = ["FAKE_TRANSLATION_KEY", "FAKE_ASR_KEY", "FAKE_WEBSOCKET_TOKEN", "FAKE_AUTH_TOKEN"]
    fake = SimpleNamespace(
        _AUTH_KEYS={"OpenAI_API": values[0]},
        _TRANSCRIPTION_AUTH_KEYS={"Deepgram": values[1]},
        _WEBSOCKET_AUTH_TOKEN=values[2],
        _VOICE_SETTINGS={"provider": {"auth_token": values[3]}},
    )
    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(config=fake))
    return values


def test_general_error_keeps_path_message_and_chain(logger):
    path = "/recording-fixture/missing-config.json"
    try:
        try:
            raise KeyError("missing_setting")
        except KeyError as cause:
            raise FileNotFoundError(2, "No such file or directory", path) from cause
    except FileNotFoundError:
        utils.errorLogging()
    record = logger.error.call_args.args[0]
    assert isinstance(record, str)
    assert path in record and "No such file or directory" in record
    assert "missing_setting" in record and "direct cause" in record
    assert "Traceback (most recent call last)" in record


@pytest.mark.parametrize("fallback", [None, "write", "setup"])
def test_general_error_masks_configured_secrets_and_url(logger, configured_secrets, monkeypatch, capsys, fallback):
    if fallback == "write":
        logger.error.side_effect = OSError("cannot write")
    elif fallback == "setup":
        monkeypatch.setattr(utils, "error_logger", None)
        monkeypatch.setattr(utils, "setupLogger", Mock(side_effect=OSError("cannot open")))
    secret_url = "https://URL_USER:URL_PASSWORD@service.example/file?api_key=URL_SECRET&other=QUERY_TEXT"
    try:
        raise RuntimeError("operation failed " + " ".join(configured_secrets) + " " + secret_url)
    except RuntimeError:
        utils.errorLogging()
    record = capsys.readouterr().out if fallback else logger.error.call_args.args[0]
    assert "operation failed" in record
    assert "***MASKED***" in record
    assert "service.example/file" in record
    for secret in configured_secrets + ["URL_USER", "URL_PASSWORD", "URL_SECRET", "QUERY_TEXT"]:
        assert secret not in record


@pytest.mark.parametrize("text", [
    "request Bearer FAKE_CREDENTIAL failed",
    "Authorization: Bearer FAKE_CREDENTIAL\nnext diagnostic",
    "Authorization: Token FAKE_CREDENTIAL\nnext diagnostic",
    '{"Authorization": "Bearer FAKE_CREDENTIAL"}',
    "{'Authorization': 'Token FAKE_CREDENTIAL'}",
    "x-goog-api-key: FAKE_CREDENTIAL",
    '{"x-goog-api-key": "FAKE_CREDENTIAL"}',
    "api_key=FAKE_CREDENTIAL&version=1",
    "key=FAKE_CREDENTIAL",
    '{"api_key": "FAKE_CREDENTIAL", "message": "keep this"}',
    "{'key': 'FAKE_CREDENTIAL with spaces'}",
    '{"api_key": "FAKE_CREDENTIAL\\\"rest"}',
])
def test_common_credentials_are_redacted_without_config(text):
    result = redact_diagnostic_text(text)
    assert "FAKE_CREDENTIAL" not in result
    assert "***MASKED***" in result


def test_provider_error_keeps_type_status_provider_and_frames_only(logger):
    try:
        try:
            raise KeyError("CHAIN_SECRET")
        except KeyError as cause:
            error = RuntimeError("FAKE_KEY PRIVATE_CONVERSATION")
            error.response = SimpleNamespace(status_code=401)
            raise error from cause
    except RuntimeError:
        utils.errorLogging(provider="OpenAI")
    record = logger.error.call_args.args[0]
    assert record["error"] == "RuntimeError"
    assert record["status"] == 401 and record["provider"] == "OpenAI"
    assert record["frames"]
    for marker in ("CHAIN_SECRET", "FAKE_KEY", "PRIVATE_CONVERSATION", "raise error"):
        assert marker not in repr(record)


def test_exception_response_keeps_general_message_and_redacts(configured_secrets):
    message = "/recording-fixture/missing.json " + configured_secrets[0]
    message += " https://user:password@service.example?api_key=URL_SECRET"
    response = VRCTError.create_exception_error_response(FileNotFoundError(message))
    result = response["result"]
    assert "/recording-fixture/missing.json" in result["message"]
    assert "***MASKED***" in result["message"]
    assert configured_secrets[0] not in result["message"]
    assert "URL_SECRET" not in result["message"]
    assert "user:password" not in result["message"]
    assert result["details"]["exception_type"] == "FileNotFoundError"


@pytest.mark.parametrize("origin", ["explicit", "sdk", "marked", "wrapped"])
def test_exception_response_and_outer_log_remain_safe_for_provider_errors(origin, logger):
    kwargs = {}
    if origin == "sdk":
        error = APIStatusError("PRIVATE_CONVERSATION", response=httpx.Response(
            401, request=httpx.Request("GET", "https://service.example")), body=None)
    else:
        error = ValueError("PRIVATE_CONVERSATION")
        if origin == "explicit":
            kwargs["provider"] = "OpenAI"
        else:
            @provider_errors("OpenAI")
            def fail():
                raise error
            with pytest.raises(ValueError):
                fail()
            if origin == "wrapped":
                outer = RuntimeError("outer failure")
                outer.__cause__ = error
                error = outer
    result = VRCTError.create_exception_error_response(error, **kwargs)["result"]
    assert result["message"] == "Error: " + type(error).__name__
    try:
        raise error
    except Exception:
        utils.errorLogging(**kwargs)
    assert all(isinstance(call.args[0], dict) for call in logger.error.call_args_list)
    assert "PRIVATE_CONVERSATION" not in repr(logger.error.call_args_list)


@pytest.mark.parametrize("module_name,class_name,attr", LLMS)
def test_every_llm_failure_is_marked_and_safely_logged(module_name, class_name, attr, monkeypatch, logger):
    module = importlib.import_module("models.translation.translation_" + module_name)
    client = object.__new__(getattr(module, class_name))
    client.prompt_template = "Translate {input_lang} to {output_lang}"
    client.supported_languages = ["English", "Japanese"]
    client.history_cfg = {}
    failure = ValueError("UNSAVED_KEY PRIVATE_CONVERSATION")
    setattr(client, attr, SimpleNamespace(invoke=Mock(side_effect=failure)))
    with pytest.raises(ValueError):
        client.translate("PRIVATE_CONVERSATION", "English", "Japanese")
    assert logger.error.call_args.args[0]["provider"] == client.provider_name
    assert "PRIVATE_CONVERSATION" not in repr(logger.error.call_args_list)
    assert "UNSAVED_KEY" not in repr(logger.error.call_args_list)
    assert VRCTError.create_exception_error_response(failure)["result"]["message"] == "Error: ValueError"


@pytest.mark.parametrize("module_name,class_name,attr", LLMS)
def test_llm_discovery_failure_is_safely_logged(module_name, class_name, attr, monkeypatch, logger):
    module = importlib.import_module("models.translation.translation_" + module_name)
    client = object.__new__(getattr(module, class_name))
    client.api_key = "configured-key"
    client.base_url = "https://service.example"
    monkeypatch.setattr(module, "_get_available_text_models", Mock(
        side_effect=ValueError("UNSAVED_KEY PRIVATE_CONVERSATION")))
    try:
        assert client.getModelList() == []  # Compatible adapter returns an empty list.
    except ValueError:
        utils.errorLogging()
    assert logger.error.called
    assert all(call.args[0]["provider"] == client.provider_name for call in logger.error.call_args_list)
    assert "UNSAVED_KEY" not in repr(logger.error.call_args_list)
    assert "PRIVATE_CONVERSATION" not in repr(logger.error.call_args_list)


@pytest.mark.parametrize("module_name,function_name,kwargs", [
    ("transcription_openai_compatible", "checkTranscriptionApiKey", {"api_key": "new-key", "base_url": "https://service.example"}),
    ("transcription_openai_compatible", "getAvailableTranscriptionModels", {"api_key": "new-key", "base_url": "https://service.example"}),
    ("transcription_deepgram", "checkDeepgramApiKey", {"api_key": "new-key"}),
    ("transcription_deepgram", "getAvailableDeepgramModelsDetailed", {"api_key": "new-key"}),
])
def test_asr_discovery_failure_is_safely_logged(module_name, function_name, kwargs, monkeypatch, logger):
    module = importlib.import_module("models.transcription." + module_name)
    target = "fetch_openai_models" if module_name.endswith("compatible") else "api_request"
    monkeypatch.setattr(module, target, Mock(side_effect=ValueError("UNSAVED_KEY PRIVATE_CONVERSATION")))
    try:
        assert getattr(module, function_name)(**kwargs) in (False, [])
    except ValueError:
        utils.errorLogging()
    assert logger.error.called
    assert all(isinstance(call.args[0], dict) for call in logger.error.call_args_list)
    assert "UNSAVED_KEY" not in repr(logger.error.call_args_list)
    assert "PRIVATE_CONVERSATION" not in repr(logger.error.call_args_list)


@pytest.mark.parametrize("engine", ["Google", "Deepgram", "OpenAI"])
def test_asr_provider_failures_include_malformed_responses(engine, monkeypatch, logger):
    from models.transcription import transcription_providers as module
    failure = ValueError("UNSAVED_KEY PRIVATE_CONVERSATION")
    if engine == "Google":
        client = module.GoogleProvider(SimpleNamespace(recognize_google=Mock(side_effect=failure)))
    elif engine == "Deepgram":
        client = module.DeepgramProvider("key", "model")
        monkeypatch.setattr(module.requests, "post", Mock(return_value=SimpleNamespace(
            status_code=200, json=Mock(side_effect=failure))))
    else:
        client = object.__new__(module.OpenAICompatibleTranscriptionProvider)
        client.engine_name = "OpenAI_Whisper"
        client.model = "whisper-1"
        client._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(
            create=Mock(side_effect=failure))))
    try:
        client.transcribe(Mock(), "English", "United States", avg_logprob=-1,
                          no_speech_prob=0.6, no_repeat_ngram_size=3, force_language=False)
    except Exception as error:
        utils.errorLogging()
        assert VRCTError.create_exception_error_response(error)["result"]["message"] == "Error: " + type(error).__name__
    else:
        pytest.fail("Expected provider failure")
    assert logger.error.called
    assert all(isinstance(call.args[0], dict) for call in logger.error.call_args_list)
    assert "PRIVATE_CONVERSATION" not in repr(logger.error.call_args_list)
    assert "UNSAVED_KEY" not in repr(logger.error.call_args_list)


@pytest.mark.parametrize("engine,method,key,operation", [
    ("OpenAI_API", "setOpenAIAuthKey", "sk-" + "a" * 161, "prepareTranslatorCredential"),
    ("DeepL_API", "setDeeplAuthKey", "d" * 36, "prepareTranslatorCredential"),
    ("OpenAI_Compatible", "setOpenAICompatibleAuthKey", "new-key", "prepareTranslatorCredential"),
    ("OpenAI_Whisper", "setOpenAIWhisperAuthKey", "new-key", "authenticationTranscriptionApiKey"),
    ("Deepgram", "setDeepgramAuthKey", "new-key", "authenticationDeepgramApiKey"),
])
def test_settings_key_validation_logs_only_safe_provider_record(engine, method, key, operation, monkeypatch, logger):
    import controller as module
    backend = Mock()
    getattr(backend, operation).side_effect = ValueError("UNSAVED_KEY PRIVATE_CONVERSATION")
    cfg = SimpleNamespace(AUTH_KEYS={engine: "old-key"}, TRANSCRIPTION_AUTH_KEYS={engine: "old-key"},
                          OPENAI_COMPATIBLE_URL="https://service.example/v1", SELECTED_OPENAI_MODEL="model",
                          SELECTED_OPENAI_COMPATIBLE_MODEL="model", OPENAI_WHISPER_BASE_URL="https://api.openai.com/v1")
    monkeypatch.setattr(module, "model", backend)
    monkeypatch.setattr(module, "config", cfg)
    controller = module.Controller.__new__(module.Controller)
    result = getattr(controller, method)(key)
    assert result["status"] == 400 and result["result"]["data"] == "old-key"
    getattr(backend, operation).assert_called_once()
    record = logger.error.call_args.args[0]
    assert record["provider"] == engine and record["error"] == "ValueError"
    assert "UNSAVED_KEY" not in repr(record)
    assert "PRIVATE_CONVERSATION" not in repr(record)
