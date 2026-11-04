"""Runtime timeouts use the transport, with no requests, models or workers."""

import importlib
import json
import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
import requests
from deepl import DeepLClient
from deepl.exceptions import ConnectionException

from model import Model
from models.translation import translation_translator as translator_module
from models.translation.translation_deepl import configureDeepLRuntimeTimeout
from test_controller_message_pipeline import _MessagePipelineTestBase


PROVIDERS = [
    ("OpenAI_API", "openai", "OpenAIClient", "ChatOpenAI", "openai_llm", 30.0),
    ("OpenAI_Compatible", "openai_compatible", "OpenAICompatibleClient", "ChatOpenAI", "openai_llm", 30.0),
    ("OpenRouter_API", "openrouter", "OpenRouterClient", "ChatOpenAI", "openrouter_llm", 30.0),
    ("Groq_API", "groq", "GroqClient", "ChatOpenAI", "groq_llm", 30.0),
    ("Plamo_API", "plamo", "PlamoClient", "ChatOpenAI", "plamo_llm", 30.0),
    ("Gemini_API", "gemini", "GeminiClient", "ChatGoogleGenerativeAI", "gemini_llm", 30.0),
    ("Ollama", "ollama", "OllamaClient", "ChatOllama", "openai_llm", 120.0),
    ("LMStudio", "lmstudio", "LMStudioClient", "ChatOpenAI", "openai_llm", 120.0),
]
WEB_ENGINES = ["Google", "Bing", "Papago"]
ENGINES = [row[0] for row in PROVIDERS] + ["DeepL_API"] + WEB_ENGINES


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must use fake transports")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def make_client(row):
    _, module_name, class_name, _, _, _ = row
    module = importlib.import_module(f"models.translation.translation_{module_name}")
    client = getattr(module, class_name)()
    client.api_key = "synthetic-test-key"
    client.model = "gemini-2.5-flash" if module_name == "gemini" else "test-model"
    return client


def install_client(translator, engine, client):
    attr = {
        "OpenAI_Compatible": "openai_compatible_client",
        "Ollama": "ollama_client", "LMStudio": "lmstudio_client",
        "DeepL_API": "deepl_client",
    }.get(engine)
    if attr:
        setattr(translator, attr, client)
    else:
        translator._provider_clients[engine] = client


@pytest.mark.parametrize("row", PROVIDERS, ids=[row[0] for row in PROVIDERS])
def test_provider_passes_timeout_to_client_without_creating_workers(row, monkeypatch):
    engine, module_name, _, factory_name, _, read_seconds = row
    # OpenAI-compatible inherits the official provider's updateClient method.
    factory_module = "openai" if module_name == "openai_compatible" else module_name
    module = importlib.import_module(f"models.translation.translation_{factory_module}")
    llm = Mock()
    llm.invoke.return_value = SimpleNamespace(content="translation", response_metadata={})
    factory = Mock(return_value=llm)
    monkeypatch.setattr(module, factory_name, factory)
    client = make_client(row)

    with patch.object(threading.Thread, "__init__", side_effect=AssertionError("Per-call worker")):
        client.updateClient()
        for _ in range(3):
            assert client.translate("hello", "English", "Japanese") == "translation"

    kwargs = factory.call_args.kwargs
    if engine == "Gemini_API":
        assert kwargs["timeout"] == 30.0  # seconds, not Google SDK milliseconds
        assert kwargs["max_retries"] == 2  # initial attempt plus one retry
    else:
        timeout = kwargs["client_kwargs"]["timeout"] if engine == "Ollama" else kwargs["timeout"]
        assert timeout.as_dict() == {
            "connect": 5.0, "read": read_seconds, "write": 10.0, "pool": 5.0,
        }
        if engine == "Ollama":
            assert llm.invoke.call_args.kwargs == {"stream": False}
        else:
            assert kwargs["max_retries"] == (0 if engine == "LMStudio" else 1)


@pytest.mark.parametrize("row", PROVIDERS, ids=[row[0] for row in PROVIDERS])
@pytest.mark.parametrize("failure", ["timeout", "connection", 429, 502, 401, "retry_after"])
@pytest.mark.parametrize("recovers", [False, True])
def test_installed_sdk_timeout_and_retry_policy_reaches_fallback(row, failure, recovers, monkeypatch):
    """Real LangChain/SDK request construction, fake HTTP send (no sockets)."""
    engine, _, _, _, llm_attr, read_seconds = row
    client = make_client(row)
    client.updateClient()
    llm = getattr(client, llm_attr)
    if engine == "Gemini_API":
        http_client = llm.client._api_client._httpx_client
        expected = dict.fromkeys(("connect", "read", "write", "pool"), 30.0)
    elif engine == "Ollama":
        http_client = llm._client._client
        expected = {"connect": 5.0, "read": read_seconds, "write": 10.0, "pool": 5.0}
    else:
        http_client = llm.root_client._client
        expected = {"connect": 5.0, "read": read_seconds, "write": 10.0, "pool": 5.0}
    calls = []
    sleep = Mock()
    monkeypatch.setattr("time.sleep", sleep)
    ct2 = Mock(return_value=False)

    def send(request, **kwargs):
        assert ct2.call_count == 0  # SDK retry must precede application fallback.
        calls.append(request)
        # OpenAI 3.x also supports httpx2; use the actual transport's exception.
        transport_module = importlib.import_module(type(request).__module__.split(".")[0])
        if len(calls) == 1 or not recovers:
            if failure == "timeout":
                raise transport_module.ReadTimeout("synthetic timeout", request=request)
            if failure == "connection":
                raise transport_module.ConnectError("synthetic dropped connection", request=request)
            status = 429 if failure == "retry_after" else failure
            return transport_module.Response(status, request=request,
                headers={"Retry-After": "120"} if failure == "retry_after" else {},
                json={"error": {"code": status, "message": "synthetic failure"}})
        if engine == "Gemini_API":
            response = {"candidates": [{"content": {"role": "model", "parts": [{"text": "translation"}]},
                                        "finishReason": "STOP"}]}
        elif engine == "Ollama":
            response = {"model": "test-model", "message": {"role": "assistant", "content": "translation"},
                        "done": True, "done_reason": "stop"}
        else:
            response = {"id": "fake", "object": "chat.completion", "created": 0, "model": "test-model",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "translation"},
                                     "finish_reason": "stop"}]}
        return transport_module.Response(200, json=response, request=request)

    monkeypatch.setattr(http_client, "send", send)
    translator = translator_module.Translator()
    install_client(translator, engine, client)
    monkeypatch.setattr(translator, "translateCTranslate2", ct2)
    model = make_model(translator)
    log = Mock()
    monkeypatch.setattr(translator_module, "printLog", log)
    monkeypatch.setattr("model.errorLogging", Mock())
    with patch.object(threading.Thread, "__init__", side_effect=AssertionError("Per-call worker")):
        result = model.getTranslate(engine, "English", "Japanese", "Japan", "hello")
    retries = int(engine not in ("Ollama", "LMStudio") and failure != 401)
    assert len(calls) == 1 + retries
    assert sleep.call_count == retries
    if retries:
        delay = sleep.call_args.args[0]
        if engine == "Gemini_API":
            assert 1.0 <= delay <= 2.0  # Google does not use Retry-After here.
        elif failure == "retry_after":
            assert delay == 120.0
        else:
            assert 0.375 <= delay <= 0.5
    for request in calls:
        assert request.extensions["timeout"] == expected
        if engine == "Ollama":
            assert json.loads(request.content)["stream"] is False
    if recovers and retries:
        assert result == ("translation", True)
        ct2.assert_not_called()
        log.assert_not_called()
    else:
        assert result == ("hello", False)
        ct2.assert_called_once()
        log.assert_called_once()
        if failure == "timeout":
            error_type = "ReadTimeout" if engine in ("Gemini_API", "Ollama") else "OpenAITimeoutError"
            assert log.call_args.args[1] == {"engine": engine, "error_type": error_type}


@pytest.mark.parametrize("credential_path", ["prepare", "startup"])
def test_deepl_probe_keeps_defaults_and_runtime_uses_explicit_limits(credential_path, monkeypatch):
    received = []

    def send(session, request, **kwargs):
        received.append(kwargs["timeout"])
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"translations":[{"text":"translation","detected_source_language":"EN","billed_characters":5}]}'
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    translator = translator_module.Translator()
    translator.is_enable_translators = True
    if credential_path == "prepare":
        candidate = translator.prepareCredential("DeepL_API", "synthetic-test-key")
        translator.commitCredential("DeepL_API", candidate)
    else:
        assert translator.authenticationDeepLAuthKey("synthetic-test-key") is True
    assert received == [10.0]  # existing authentication request, unchanged
    with patch.object(threading.Thread, "__init__", side_effect=AssertionError("Per-call worker")):
        for _ in range(3):
            assert translator.translate("DeepL_API", "", "English", "Japanese", "Japan", "hello") == "translation"
    assert received == [10.0, (5.0, 10.0), (5.0, 10.0), (5.0, 10.0)]
    translator.deepl_client.close()


def test_deepl_timeout_retries_once_without_changing_global_defaults(monkeypatch):
    from deepl import http_client

    defaults = (http_client.min_connection_timeout, http_client.max_network_retries)
    client = DeepLClient("synthetic-test-key")
    probe_transport = client._client
    close = Mock(wraps=probe_transport.close)
    monkeypatch.setattr(probe_transport, "close", close)
    configureDeepLRuntimeTimeout(client)
    close.assert_called_once()
    send = Mock(side_effect=requests.ReadTimeout("synthetic timeout"))
    monkeypatch.setattr(client._client._session, "send", send)
    sleep = Mock()
    monkeypatch.setattr("time.sleep", sleep)
    with patch.object(threading.Thread, "__init__", side_effect=AssertionError("Per-call worker")):
        with pytest.raises(ConnectionException):
            client.translate_text("hello", target_lang="JA")
    assert send.call_count == 2
    assert all(call.kwargs["timeout"] == (5.0, 10.0) for call in send.call_args_list)
    sleep.assert_called_once()
    assert 0.0 <= sleep.call_args.args[0] <= 1.0
    assert (http_client.min_connection_timeout, http_client.max_network_retries) == defaults
    client.close()


@pytest.mark.parametrize("failure", ["timeout", "connection", 429, 502, 403, "invalid_url"])
@pytest.mark.parametrize("recovers", [False, True])
def test_deepl_retry_policy_reaches_fallback(failure, recovers, monkeypatch):
    client = DeepLClient("synthetic-test-key")
    configureDeepLRuntimeTimeout(client)
    calls = []
    ct2 = Mock(return_value=False)

    def send(request, **kwargs):
        assert ct2.call_count == 0
        calls.append(kwargs)
        if len(calls) == 1 or not recovers:
            if failure == "timeout":
                raise requests.ReadTimeout("synthetic timeout")
            if failure == "connection":
                raise requests.ConnectionError("synthetic dropped connection")
            if failure == "invalid_url":
                raise requests.exceptions.InvalidURL("synthetic invalid URL")
            response = requests.Response()
            response.status_code = failure
            response._content = b'{"message":"synthetic failure"}'
        else:
            response = requests.Response()
            response.status_code = 200
            response._content = b'{"translations":[{"text":"translation","detected_source_language":"EN","billed_characters":5}]}'
        return response

    monkeypatch.setattr(client._client._session, "send", send)
    sleep = Mock()
    monkeypatch.setattr("time.sleep", sleep)
    translator = translator_module.Translator()
    translator.is_enable_translators = True
    translator.deepl_client = client
    monkeypatch.setattr(translator, "translateCTranslate2", ct2)
    monkeypatch.setattr(translator_module, "printLog", Mock())
    monkeypatch.setattr("model.errorLogging", Mock())
    model = make_model(translator)
    try:
        with patch.object(threading.Thread, "__init__", side_effect=AssertionError("Per-call worker")):
            result = model.getTranslate("DeepL_API", "English", "Japanese", "Japan", "hello")
        retries = int(failure not in (403, "invalid_url"))
        assert len(calls) == 1 + retries
        assert all(call["timeout"] == (5.0, 10.0) for call in calls)
        assert sleep.call_count == retries
        if retries:
            assert 0.0 <= sleep.call_args.args[0] <= 1.0
        if recovers and retries:
            assert result == ("translation", True)
            ct2.assert_not_called()
        else:
            assert result == ("hello", False)
            ct2.assert_called_once()
    finally:
        client.close()


def make_model(translator):
    model = object.__new__(Model)
    model._inited = True
    model.translator = translator
    model.translation_history = []
    model.translation_history_max_items = 20
    return model


@pytest.fixture(params=ENGINES)
def failing_provider(request, monkeypatch):
    engine = request.param
    translator = translator_module.Translator()
    translator.is_enable_translators = True
    timeout = httpx.ReadTimeout("synthetic-api-key-must-not-be-logged")
    invoke = Mock(side_effect=timeout)
    if engine in WEB_ENGINES:
        monkeypatch.setattr(translator_module, "ENABLE_TRANSLATORS", True)
        monkeypatch.setattr(translator_module, "other_web_Translator", invoke)
    elif engine == "DeepL_API":
        install_client(translator, engine, SimpleNamespace(translate_text=invoke))
    else:
        row = next(row for row in PROVIDERS if row[0] == engine)
        client = make_client(row)
        setattr(client, row[4], SimpleNamespace(invoke=invoke))
        install_client(translator, engine, client)
    model = make_model(translator)
    log = Mock()
    monkeypatch.setattr(translator_module, "printLog", log)
    monkeypatch.setattr("model.errorLogging", Mock())
    monkeypatch.setattr("model.printLog", Mock())
    return SimpleNamespace(engine=engine, model=model, translator=translator, invoke=invoke, log=log)


def translate(subject):
    return subject.model.getTranslate(subject.engine, "English", "Japanese", "Japan", "hello")


@pytest.mark.parametrize("fallback", ["fallback translation", False, None, ""])
def test_timeout_follows_existing_fallback_and_redacts_provider_exception(failing_provider, fallback, monkeypatch):
    subject = failing_provider
    ct2 = Mock(return_value=fallback)
    monkeypatch.setattr(subject.translator, "translateCTranslate2", ct2)
    with patch.object(threading.Thread, "__init__", side_effect=AssertionError("Per-call worker")):
        result = translate(subject)
    assert result == ((fallback, True) if fallback else ("hello", False))
    ct2.assert_called_once()
    subject.invoke.assert_called_once()
    subject.log.assert_called_once_with("Translation provider failed", {
        "engine": subject.engine, "error_type": "ReadTimeout",
    })
    assert "synthetic-api-key-must-not-be-logged" not in repr(subject.log.call_args)
    if subject.engine in WEB_ENGINES:
        assert subject.invoke.call_args.kwargs["timeout"] == 10


def test_timeout_preserves_loaded_ctranslate2_retry(failing_provider, monkeypatch):
    subject = failing_provider
    ct2 = Mock(side_effect=[False, "fallback translation"])
    monkeypatch.setattr(subject.translator, "translateCTranslate2", ct2)
    monkeypatch.setattr(subject.translator, "isLoadedCTranslate2Model", lambda: True)
    with patch("model.sleep") as sleep:
        assert translate(subject) == ("fallback translation", True)
    assert ct2.call_count == 2
    sleep.assert_called_once_with(0.1)


@pytest.mark.parametrize("fallback", [False, "fallback translation"])
def test_timeout_reaches_controller_existing_error_code(failing_provider, fallback, monkeypatch):
    subject = failing_provider
    monkeypatch.setattr(subject.translator, "translateCTranslate2", Mock(return_value=fallback))
    # Reuse the existing pipeline harness: all publication/voice paths are fake.
    harness = _MessagePipelineTestBase()
    harness.setUp()
    try:
        def get_input(message, source_language=None):
            text, success = translate(subject)
            return [text], [success]

        harness._model.getInputTranslate.side_effect = get_input
        with patch("controller.printLog"):
            harness.controller.micMessage({"text": "hello", "language": "English"})
        errors = [call for call in harness.run_calls if call[1] == "/run/error_translation_engine"]
        if fallback:
            assert errors == []
            harness.controller.changeToCTranslate2Process.assert_not_called()
        else:
            assert len(errors) == 1
            status, _, result = errors[0]
            assert status == 400
            assert result["error_code"] == "TRANSLATION_ENGINE_LIMIT"
            harness.controller.changeToCTranslate2Process.assert_called_once()
    finally:
        harness.tearDown()
