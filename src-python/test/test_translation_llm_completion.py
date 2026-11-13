"""LLM completion metadata must reach the existing empty-translation fallback.

Use real provider parsers, Translator and Model.getTranslate; only the LLM
response and CTranslate2 inference are mocked. No models or APIs are needed.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage

from model import Model
from models.translation.translation_gemini import GeminiClient
from models.translation.translation_groq import GroqClient
from models.translation.translation_lmstudio import LMStudioClient
from models.translation.translation_ollama import OllamaClient
from models.translation.translation_openai import OpenAIClient
from models.translation.translation_openai_compatible import OpenAICompatibleClient
from models.translation.translation_openrouter import OpenRouterClient
from models.translation.translation_plamo import PlamoClient
from models.translation.translation_translator import Translator


@pytest.fixture(params=[
    pytest.param(("OpenAI_API", OpenAIClient, "openai_llm", "finish_reason", "length", "stop"), id="openai"),
    pytest.param(("OpenAI_Compatible", OpenAICompatibleClient, "openai_llm", "finish_reason", "length", "stop"), id="openai-compatible"),
    pytest.param(("LMStudio", LMStudioClient, "openai_llm", "finish_reason", "length", "stop"), id="lmstudio"),
    pytest.param(("Groq_API", GroqClient, "groq_llm", "finish_reason", "length", "stop"), id="groq"),
    pytest.param(("OpenRouter_API", OpenRouterClient, "openrouter_llm", "finish_reason", "length", "stop"), id="openrouter"),
    pytest.param(("Plamo_API", PlamoClient, "plamo_llm", "finish_reason", "length", "stop"), id="plamo"),
    pytest.param(("Gemini_API", GeminiClient, "gemini_llm", "finish_reason", "MAX_TOKENS", "STOP"), id="gemini"),
    pytest.param(("Ollama", OllamaClient, "openai_llm", "done_reason", "length", "stop"), id="ollama"),
    pytest.param(("OpenAI_API", OpenAIClient, "openai_llm", "incomplete_details", {"reason": "max_output_tokens"}, None), id="openai-responses"),
    pytest.param(("OpenAI_Compatible", OpenAICompatibleClient, "openai_llm", "incomplete_details", {"reason": "max_output_tokens"}, None), id="openai-compatible-responses"),
])
def provider(request):
    engine, client_type, llm_attr, reason_key, truncated, stop = request.param
    client = client_type()
    translator = Translator()
    if engine == "OpenAI_Compatible":
        translator.openai_compatible_client = client
    elif engine == "LMStudio":
        translator.lmstudio_client = client
    elif engine == "Ollama":
        translator.ollama_client = client
    else:
        translator._provider_clients[engine] = client

    # Bypass the singleton without starting the application or loading models,
    # as in test_model_get_translate_unsupported_language.py.
    model = object.__new__(Model)
    model._inited = True
    model.translator = translator
    model.translation_history = []
    model.translation_history_max_items = 20

    def translate(content, metadata, fallback="fallback translation"):
        llm = Mock()
        if reason_key == "incomplete_details" and not isinstance(content, AIMessage):
            metadata = {
                "status": "incomplete" if metadata.get(reason_key) else "completed",
                **metadata,
            }
        llm.invoke.return_value = (
            content if isinstance(content, AIMessage)
            else AIMessage(content=content, response_metadata=metadata)
        )
        setattr(client, llm_attr, llm)
        with (
            patch.object(translator, "translateCTranslate2", return_value=fallback) as ct2,
            patch("models.translation.translation_translator.errorLogging") as provider_error,
            patch("model.errorLogging"),
            patch("model.printLog"),
        ):
            result = model.getTranslate(
                translator_name=engine,
                source_language="English",
                target_language="Japanese",
                target_country="Japan",
                message="original message",
            )
        llm.invoke.assert_called_once()
        # An accidental parser exception must not masquerade as truncation.
        provider_error.assert_not_called()
        return result, ct2

    return SimpleNamespace(
        translate=translate, reason_key=reason_key, truncated=truncated, stop=stop,
    )


@pytest.mark.parametrize("content", ["partial translation", ["partial", {"content": " translation"}]])
def test_truncated_translation_uses_ctranslate2(provider, content):
    result, ct2 = provider.translate(content, {provider.reason_key: provider.truncated})
    assert result == ("fallback translation", True)
    ct2.assert_called_once()


@pytest.mark.parametrize("fallback", [False, None, ""])
def test_truncated_translation_without_usable_fallback_returns_original_and_failure(provider, fallback):
    result, ct2 = provider.translate(
        "partial translation", {provider.reason_key: provider.truncated}, fallback=fallback,
    )
    assert result == ("original message", False)
    ct2.assert_called_once()


def test_normal_stop_succeeds_without_fallback(provider):
    result, ct2 = provider.translate(" complete translation ", {provider.reason_key: provider.stop})
    assert result == ("complete translation", True)
    ct2.assert_not_called()


@pytest.mark.parametrize("content", ["", " \n\t "])
def test_empty_translation_still_uses_failure_path(provider, content):
    result, ct2 = provider.translate(content, {provider.reason_key: provider.stop})
    assert result == ("fallback translation", True)
    ct2.assert_called_once()


def test_empty_translation_without_fallback_returns_original_and_failure(provider):
    result, ct2 = provider.translate("", {provider.reason_key: provider.stop}, fallback=False)
    assert result == ("original message", False)
    ct2.assert_called_once()


@pytest.mark.parametrize("metadata", [{}, {"finish_reason": None, "done_reason": None}])
def test_missing_truncation_signal_preserves_nonempty_translation(provider, metadata):
    result, ct2 = provider.translate("complete translation", metadata)
    assert result == ("complete translation", True)
    ct2.assert_not_called()


@pytest.fixture(params=["openai-responses", "gemini-3", "gemini-thinking", "gemini-signature"])
def sdk_response(request):
    """Convert valid SDK replies locally, without creating an API client."""
    if request.param == "openai-responses":
        from openai.types.responses import Response
        from langchain_openai.chat_models.base import _construct_lc_result_from_responses_api

        response = Response(
            id="resp_test", created_at=0, model="gpt-5-pro", object="response",
            status="completed", parallel_tool_calls=False, tool_choice="auto", tools=[],
            output=[
                {"id": "rs_test", "type": "reasoning",
                 "summary": [{"type": "summary_text", "text": "private reasoning"}]},
                {"id": "fc_test", "type": "function_call", "call_id": "call_test",
                 "name": "test_tool", "arguments": "{}", "status": "completed"},
                {"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                 "content": [
                     {"type": "output_text", "text": " 「こんにちは」", "annotations": []},
                     {"type": "refusal", "refusal": "not a translation"},
                     {"type": "output_text", "text": "<b>{世界}</b> ", "annotations": []},
                 ]},
            ],
        )
        return _construct_lc_result_from_responses_api(response).generations[0].message

    from google.genai.types import Candidate, Content, FinishReason, GenerateContentResponse, Part
    from langchain_google_genai.chat_models import _response_to_result

    parts = [Part(text=" 「こんにちは」"), Part(text="<b>{世界}</b> ")]
    if request.param == "gemini-thinking":
        parts.insert(0, Part(text="private reasoning", thought=True, thought_signature=b"test"))
    elif request.param == "gemini-signature":
        parts[0].thought_signature = b"test"
    response = GenerateContentResponse(
        model_version="gemini-3-pro-preview" if request.param == "gemini-3" else "gemini-2.5-pro",
        candidates=[Candidate(content=Content(role="model", parts=parts), finish_reason=FinishReason.STOP)],
    )
    generation = _response_to_result(response).generations[0]
    # BaseChatModel normally merges generation_info into response_metadata.
    generation.message.response_metadata.update(generation.generation_info)
    return generation.message


def test_sdk_text_blocks_succeed_without_fallback(provider, sdk_response):
    assert isinstance(sdk_response.content, list)
    assert any(part.get("type") == "text" for part in sdk_response.content if isinstance(part, dict))
    result, ct2 = provider.translate(sdk_response, {})
    assert result == ("「こんにちは」<b>{世界}</b>", True)
    ct2.assert_not_called()


def test_truncated_sdk_text_blocks_still_use_fallback(provider, sdk_response):
    result, ct2 = provider.translate(sdk_response.content, {provider.reason_key: provider.truncated})
    assert result == ("fallback translation", True)
    ct2.assert_called_once()


@pytest.mark.parametrize("content", [
    " 「こんにちは」<b>{世界}</b> ",
    [" 「こんにちは」", {"content": "<b>{世界}</b> "}],
    [
        {"type": "text", "text": " 「こんにちは」"},
        {"type": "text", "text": "<b>{世界}</b> "},
        {"type": "text", "text": None},
        {"type": "text", "text": {"nested": "not text"}},
        {"content": 123},
    ],
])
def test_text_formats_preserve_order_and_markup(provider, content):
    result, ct2 = provider.translate(content, {provider.reason_key: provider.stop})
    assert result == ("「こんにちは」<b>{世界}</b>", True)
    ct2.assert_not_called()


@pytest.mark.parametrize("block_type", ["reasoning", "thinking", "tool_call", "refusal", "unknown"])
@pytest.mark.parametrize("has_text", [False, True])
def test_non_text_blocks_are_never_translations(provider, block_type, has_text):
    content = [{"type": block_type, "text": "private content", "content": "private content"}]
    if has_text:
        content.append({"type": "text", "text": "translation"})
    result, ct2 = provider.translate(content, {provider.reason_key: provider.stop})
    assert result == ("translation" if has_text else "fallback translation", True)
    assert ct2.call_count == (0 if has_text else 1)
