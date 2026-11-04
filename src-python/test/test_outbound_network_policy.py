"""Outbound audit F2–F8: recording transports only, including local endpoints."""
import importlib
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import requests

from models import network_policy as policy


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Use a recording transport")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.mark.parametrize("url", [
    "https://public.example/v1", "https://10.1.2.3/v1", "http://localhost:1234/v1",
    "http://127.55.1.2/v1", "http://[::1]:12", "http://10.0.0.1", "http://172.16.0.1",
    "http://172.31.255.255", "http://192.168.1.1", "http://169.254.1.1",
    "http://[fc00::1]", "http://[fd00::1]", "http://[fe80::1]", "https://example.com?version=2",
])
def test_url_accepts_https_or_literal_local_http(url):
    assert policy.validate_api_url(url) == url


@pytest.mark.parametrize("url", [
    "http://public.example", "http://8.8.8.8", "http://172.15.1.1", "http://172.32.1.1",
    "http://100.64.0.1", "http://0.0.0.0", "http://[::]", "http://[2001:db8::1]",
    "http://local.example", "https://user:password@example.com", "http://x@localhost",
    "https://example.com?api_key=secret", "https://example.com?%74oken=secret",
    "https://example.com?X-Amz-Signature=secret", "https://example.com?access_token=x",
    "https://example.com#secret", "ftp://localhost", "https://example.com:99999",
    "https://example.com\n", "https://", "http://2130706433", "http://127.1", None,
])
def test_url_rejects_unsafe_values(url):
    with pytest.raises(ValueError, match="^endpoint_url_invalid$"):
        policy.validate_api_url(url)


@pytest.mark.parametrize("host,local", [("https://api.openai.com/v1", False),
    ("http://127.0.0.1:1234/v1", True), ("https://192.168.1.2/v1", True)])
def test_httpx_proxy_policy_and_redirects(host, local, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8888")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8888")
    monkeypatch.setenv("NO_PROXY", "")
    with policy.api_http_client(host, timeout=3) as client:
        assert client.trust_env is (not local)
        assert not client.follow_redirects
        assert bool(client._mounts) is (not local)


@pytest.mark.parametrize("url,proxied", [("http://localhost:11434", False),
    ("http://10.2.3.4/v1/models", False), ("https://cloud.example/v1/models", True)])
def test_requests_proxy_policy_and_no_redirect(url, proxied, monkeypatch):
    recorded = []
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8888")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8888")
    monkeypatch.setenv("NO_PROXY", "")
    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            recorded.append((request, kwargs))
            response = requests.Response()
            response.status_code = 307
            response.headers["Location"] = "https://unselected.example/steal"
            response._content = b""
            response.request = request
            return response
        def close(self):
            pass
    monkeypatch.setattr(requests.sessions, "HTTPAdapter", Adapter)
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", lambda *_: ("ambient-user", "ambient-password"))
    response = policy.api_request("POST", url, data=b"private", headers={"Authorization": "key"}, timeout=3)
    assert response.status_code == 307 and len(recorded) == 1
    assert recorded[0][0].headers["Authorization"] == "key"
    assert bool(recorded[0][1]["proxies"]) is proxied


@pytest.mark.parametrize("status", [307, 308])
def test_api_redirect_never_replays_credentials_or_body(status):
    requests_seen = []
    def send(request):
        requests_seen.append(request)
        return httpx.Response(status, headers={"Location": "https://unselected.example/steal"})
    with policy.api_http_client("https://api.openai.com/v1", timeout=3) as client:
        client._mounts = {}
        client._transport = httpx.MockTransport(send)
        response = client.post("https://api.openai.com/v1/chat/completions",
            content=b"private-conversation", headers={"Authorization": "Bearer key", "x-goog-api-key": "key"})
    assert response.status_code == status
    assert len(requests_seen) == 1
    assert requests_seen[0].url.host == "api.openai.com"


LLMS = [("openai", "OpenAIClient", "openai_llm"),
        ("openai_compatible", "OpenAICompatibleClient", "openai_llm"),
        ("groq", "GroqClient", "groq_llm"), ("plamo", "PlamoClient", "plamo_llm"),
        ("openrouter", "OpenRouterClient", "openrouter_llm"), ("gemini", "GeminiClient", "gemini_llm"),
        ("ollama", "OllamaClient", "openai_llm"), ("lmstudio", "LMStudioClient", "openai_llm")]


@pytest.mark.parametrize("module_name,class_name,attr", LLMS)
def test_every_llm_disables_ambient_tracing(module_name, class_name, attr, monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    import langchain_core.tracers.langchain as manager
    import langsmith
    module = importlib.import_module("models.translation.translation_" + module_name)
    client = getattr(module, class_name)()
    llm = FakeListChatModel(responses=["translation"])
    # Reintroduce the env inside invoke to prove the context guard, independently
    # of the sidecar/adapter environment scrubbing.
    def invoke(*args, **kwargs):
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        return llm.invoke(*args, **kwargs)
    setattr(client, attr, SimpleNamespace(invoke=invoke))
    created = []
    class RecordingTracer:
        def __init__(self, *args, **kwargs):
            created.append("tracer")
    monkeypatch.setattr(manager, "LangChainTracer", RecordingTracer)
    monkeypatch.setattr(langsmith, "Client", lambda *a, **k: created.append("client"))
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "marker-key")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://unselected.example")
    assert client.translate("marker-text", "English", "Japanese") == "translation"
    assert created == []


@pytest.mark.parametrize("module_name,class_name,attr", LLMS)
def test_runtime_clients_ignore_ambient_endpoints_and_ollama_key(module_name, class_name, attr, monkeypatch):
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "LANGSMITH_GATEWAY", "GOOGLE_GEMINI_BASE_URL", "GOOGLE_VERTEX_BASE_URL"):
        monkeypatch.setenv(name, "https://unselected.example")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("OLLAMA_API_KEY", "ambient-key")
    module = importlib.import_module("models.translation.translation_" + module_name)
    client = getattr(module, class_name)()
    client.api_key, client.model = "configured-key", "gemini-2.5-flash"
    client.updateClient()
    llm = getattr(client, attr)
    if module_name == "gemini":
        api = llm.client._api_client
        assert api._http_options.base_url == policy.GEMINI_BASE_URL
        assert not api.vertexai
        assert not api._httpx_client.follow_redirects
        llm.client.close()
    elif module_name == "ollama":
        http = llm._client._client
        assert "authorization" not in http.headers
        assert not http.trust_env and not http.follow_redirects
        http.close()
    else:
        url = str(llm.root_client.base_url)
        assert "unselected.example" not in url
        assert not llm.root_client._client.follow_redirects
        llm.root_client.close()


def test_discovery_has_short_timeouts_no_retries_and_closes(monkeypatch):
    made = []
    class Client:
        def __init__(self, **kwargs):
            made.append(self)
            self.kwargs = kwargs
            self.closed = False
            self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[]))
        def close(self):
            self.closed = True
    result = policy.fetch_openai_models(Client, "key")
    assert result.data == []
    assert made[0].kwargs["base_url"] == policy.OPENAI_BASE_URL
    assert made[0].kwargs["timeout"] == 3 and made[0].kwargs["max_retries"] == 0
    assert made[0].closed and made[0].kwargs["http_client"].is_closed


def test_discovery_abandonment_closes_clients_and_rejects_later_requests():
    client = Mock()
    with pytest.raises(TimeoutError, match="discovery_deadline"):
        with policy.discovery_scope() as scope:
            policy.own_discovery_client(client)
            scope.close()
            policy.check_discovery_deadline()
    client.close.assert_called_once()


def test_error_logs_drop_provider_bodies_and_chained_secrets(monkeypatch):
    import utils
    logger = Mock()
    monkeypatch.setattr(utils, "error_logger", logger)
    try:
        try:
            raise ValueError("FAKE_KEY FAKE_CONVERSATION")
        except ValueError as exc:
            error = RuntimeError("FAKE_KEY FAKE_CONVERSATION")
            error.status_code = 401
            raise error from exc
    except RuntimeError:
        utils.errorLogging(provider="OpenAI")
    recorded = str(logger.error.call_args)
    assert "FAKE_KEY" not in recorded and "FAKE_CONVERSATION" not in recorded
    assert "RuntimeError" in recorded and "401" in recorded and "OpenAI" in recorded


@pytest.mark.parametrize("scheme", ["https", "HTTPS"])
def test_url_log_redaction_in_process_and_response_logs(monkeypatch, scheme):
    import utils
    logger = Mock()
    monkeypatch.setattr(utils, "process_logger", logger)
    monkeypatch.setattr(utils, "_enqueueLogLine", lambda *_: None)
    monkeypatch.setattr(utils, "_enqueueResponseLine", lambda *_: None)
    url = f"{scheme}://user:FAKE_KEY@host.example/v1?api_key=FAKE_KEY&search='FAKE_CONVERSATION'"
    utils.printLog("Set URL", {"url": url})
    utils.printResponse(200, "/get/data/openai_compatible_url", url)
    recorded = str(logger.info.call_args_list)
    assert "FAKE_KEY" not in recorded and "FAKE_CONVERSATION" not in recorded and "user:" not in recorded
    assert "host.example/v1" in recorded


def test_download_probe_uses_pinned_origin_without_redirects(monkeypatch):
    from models.model_downloads import transport
    calls = []
    response = Mock(status=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock()
    opener = Mock()
    opener.open.return_value = response
    def build(*handlers):
        calls.extend(handlers)
        return opener
    monkeypatch.setattr(transport, "build_opener", build)
    assert transport.probe_download_host()
    request = opener.open.call_args.args[0]
    assert request.full_url == "https://huggingface.co/" and request.method == "HEAD"
    assert opener.open.call_args.kwargs["timeout"] == 3
    assert calls[0].proxies == {}
    with pytest.raises(ValueError):
        calls[1].redirect_request(request, None, 307, "", {}, "https://other.example")


@pytest.mark.parametrize("module_name,host", [("openai", "https://api.openai.com/v1"),
    ("groq", "https://api.groq.com/openai/v1"), ("plamo", "https://api.platform.preferredai.jp/v1"),
    ("openrouter", "https://openrouter.ai/api/v1"), ("openai_compatible", "http://127.0.0.1:1234/v1")])
def test_discovery_adapters_pin_destinations_and_limits(module_name, host, monkeypatch):
    module = importlib.import_module("models.translation.translation_" + module_name)
    factory_module = importlib.import_module("models.translation.translation_openai") if module_name == "openai_compatible" else module
    fake = Mock()
    fake.return_value.models.list.return_value = SimpleNamespace(data=[])
    monkeypatch.setattr(factory_module, "OpenAI", fake)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unselected.example")
    monkeypatch.setenv("OPENAI_API_BASE", "https://unselected.example")
    monkeypatch.setenv("LANGSMITH_GATEWAY", "https://unselected.example")
    if module_name in ("openrouter", "openai_compatible"):
        module._get_available_text_models("configured-key", host)
    else:
        module._fetch_models("configured-key")
    kwargs = fake.call_args.kwargs
    assert kwargs["base_url"] == host
    assert kwargs["timeout"] == 3 and kwargs["max_retries"] == 0
    assert kwargs["http_client"].is_closed
    fake.return_value.close.assert_called_once()


def test_gemini_discovery_materializes_pages_and_closes(monkeypatch):
    from models.translation import translation_gemini as module
    fake = Mock()
    fake.return_value.models.list.return_value = [SimpleNamespace(name="models/gemini-test", supported_actions=["generateContent"])]
    monkeypatch.setattr(module.genai, "Client", fake)
    assert module._get_available_text_models("configured-key") == ["gemini-test"]
    kwargs = fake.call_args.kwargs
    assert kwargs["vertexai"] is False
    assert kwargs["http_options"]["base_url"] == policy.GEMINI_BASE_URL
    assert kwargs["http_options"]["timeout"] == 3000
    assert kwargs["http_options"]["retry_options"] == {"attempts": 1}
    assert kwargs["http_options"]["client_args"]["follow_redirects"] is False
    fake.return_value.close.assert_called_once()


@pytest.mark.parametrize("status", [307, 308])
@pytest.mark.parametrize("module_name,class_name,attr", LLMS)
def test_installed_llm_sdk_does_not_follow_cross_origin_redirect(module_name, class_name, attr, status, monkeypatch):
    module = importlib.import_module("models.translation.translation_" + module_name)
    client = getattr(module, class_name)()
    client.api_key, client.model = "configured-key", "gemini-2.5-flash"
    client.updateClient()
    llm = getattr(client, attr)
    if module_name == "gemini":
        http = llm.client._api_client._httpx_client
    elif module_name == "ollama":
        http = llm._client._client
    else:
        http = llm.root_client._client
    seen = []
    def send(request):
        seen.append(request)
        transport = importlib.import_module(type(request).__module__.split(".")[0])
        return transport.Response(status, request=request, headers={"Location": "https://unselected.example/steal"}, json={"error": "redirect"})
    monkeypatch.setattr(http, "_send_single_request", send)
    try:
        try:
            client.translate("private-conversation", "English", "Japanese")
        except Exception:
            pass  # Each SDK maps an unfollowed redirect differently.
        assert len(seen) == 1
        assert seen[0].url.host != "unselected.example"
        assert b"private-conversation" in seen[0].content
    finally:
        http.close()


def test_sidecar_scrubs_before_runtime_imports(monkeypatch):
    import ast
    from pathlib import Path
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_ENDPOINT",
                 "LANGSMITH_ENDPOINT", "LANGSMITH_RUNS_ENDPOINTS", "LANGSMITH_GATEWAY", "OLLAMA_API_KEY"):
        monkeypatch.setenv(name, "ambient")
    policy.scrub_network_environment()
    import os
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert "LANGCHAIN_API_KEY" not in os.environ and "OLLAMA_API_KEY" not in os.environ
    source = Path(__file__).resolve().parents[1] / "mainloop.py"
    tree = ast.parse(source.read_text())
    scrub_line = next(node.lineno for node in tree.body if isinstance(node, ast.Expr)
                      and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                      and node.value.func.id == "scrub_network_environment")
    controller_line = next(node.lineno for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "controller")
    assert scrub_line < controller_line


@pytest.mark.parametrize("status", [307, 308])
def test_asr_sdk_does_not_replay_audio(status, monkeypatch):
    from models.transcription.transcription_providers import OpenAICompatibleTranscriptionProvider, TranscriptionApiError
    provider = OpenAICompatibleTranscriptionProvider("key", policy.OPENAI_BASE_URL, "whisper-1", "OpenAI_Whisper")
    http = provider._client._client
    seen = []
    def send(request):
        seen.append(request)
        return httpx.Response(status, request=request, headers={"Location": "https://unselected.example/steal"}, json={"error": "redirect"})
    monkeypatch.setattr(http, "_send_single_request", send)
    audio = SimpleNamespace(get_wav_data=lambda **_: b"PRIVATE_AUDIO")
    try:
        with pytest.raises(TranscriptionApiError):
            provider.transcribe(audio, "Japanese", "Japan", avg_logprob=-1, no_speech_prob=1,
                                no_repeat_ngram_size=0, force_language=True)
        assert len(seen) == 1 and seen[0].url.host == "api.openai.com"
        assert b"PRIVATE_AUDIO" in seen[0].read()
    finally:
        http.close()


@pytest.mark.parametrize("status", [307, 308])
def test_deepl_auth_never_replays_key_or_text(status, monkeypatch):
    from deepl import DeepLClient
    from models.translation.translation_deepl import authenticateDeepL
    seen = []
    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            seen.append((request, kwargs))
            response = requests.Response()
            response.status_code = status
            response.headers["Location"] = "https://unselected.example/steal"
            response.request = request
            response._content = b'{}'
            return response
        def close(self):
            pass
    monkeypatch.setattr(requests.sessions, "HTTPAdapter", Adapter)
    with pytest.raises(Exception):
        authenticateDeepL(DeepLClient, "configured-key:fx")
    assert len(seen) == 1 and seen[0][0].url.startswith("https://api-free.deepl.com/")
    assert seen[0][1]["timeout"] == (3, 3)


def test_google_speech_transport_refuses_redirects_without_sending(monkeypatch):
    from models.transcription import transcription_providers as module
    requests_seen = []
    def build(handler):
        assert handler.redirect_request(None, None, 308, "", {}, "https://unselected.example") is None
        return SimpleNamespace(open=lambda request, **kwargs: requests_seen.append((request, kwargs)))
    monkeypatch.setattr(module, "build_opener", build)
    request = module._https_google_request("http://www.google.com/speech-api/v2/recognize", data=b"private-audio")
    module._speech_urlopen(request, timeout=10)
    assert requests_seen[0][0].full_url.startswith("https://www.google.com/speech-api/")
    assert requests_seen[0][1] == {"timeout": 10}


@pytest.mark.parametrize("module_name,class_name", [("openai", "OpenAIClient"),
    ("openai_compatible", "OpenAICompatibleClient"), ("lmstudio", "LMStudioClient")])
def test_empty_disabled_endpoint_never_falls_back_to_a_different_host(module_name, class_name):
    module = importlib.import_module("models.translation.translation_" + module_name)
    with pytest.raises(ValueError, match="endpoint_url_invalid"):
        getattr(module, class_name)(base_url="")
