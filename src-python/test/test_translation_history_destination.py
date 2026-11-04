"""Destination boundaries through real history/prompt code and fake LLMs."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import socket

import pytest
from langchain_core.messages import AIMessage

import config as config_module
import model as model_module
from config import Config, ConfigValidationError
from model import Model
from models.message_pipeline import CHAT_MESSAGE_SPEC
from models.message_snapshot import MessageSnapshot
from models.translation.translation_gemini import GeminiClient
from models.translation.translation_groq import GroqClient
from models.translation.translation_lmstudio import LMStudioClient
from models.translation.translation_ollama import OllamaClient
from models.translation.translation_openai import OpenAIClient
from models.translation.translation_openai_compatible import OpenAICompatibleClient
from models.translation.translation_openrouter import OpenRouterClient
from models.translation.translation_plamo import PlamoClient
from models.translation.translation_translator import Translator


PROVIDERS = [
    ("OpenAI_API", OpenAIClient, "openai_llm", "SELECTED_OPENAI_MODEL"),
    ("Groq_API", GroqClient, "groq_llm", "SELECTED_GROQ_MODEL"),
    ("Plamo_API", PlamoClient, "plamo_llm", "SELECTED_PLAMO_MODEL"),
    ("Gemini_API", GeminiClient, "gemini_llm", "SELECTED_GEMINI_MODEL"),
    ("OpenRouter_API", OpenRouterClient, "openrouter_llm", "SELECTED_OPENROUTER_MODEL"),
    ("OpenAI_Compatible", OpenAICompatibleClient, "openai_llm", "SELECTED_OPENAI_COMPATIBLE_MODEL"),
    ("LMStudio", LMStudioClient, "openai_llm", "SELECTED_LMSTUDIO_MODEL"),
    ("Ollama", OllamaClient, "openai_llm", "SELECTED_OLLAMA_MODEL"),
]


@pytest.fixture(params=PROVIDERS, ids=[item[0] for item in PROVIDERS])
def app(request, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("History tests must never open a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    engine, client_type, llm_attr, model_attr = request.param
    # Exercise real validated config setters without loading config, writing
    # settings, enumerating devices or initializing the Model singleton.
    cfg = object.__new__(Config)
    cfg.saveConfig = Mock()
    cfg._SELECTABLE_TAB_NO_LIST = ["1", "2"]
    cfg._SELECTABLE_TRANSLATION_ENGINE_LIST = ["CTranslate2", *[item[0] for item in PROVIDERS]]
    cfg._SELECTED_TAB_NO = "1"
    cfg._SELECTED_TRANSLATION_ENGINES = {"1": engine, "2": "CTranslate2"}
    cfg._ENABLE_TRANSLATION = True
    cfg._CTRANSLATE2_WEIGHT_TYPE = "unused-local-weight"
    cfg._AUTH_KEYS = {engine: "fake-key"}
    cfg._LMSTUDIO_URL = "http://127.0.0.1:1234/v1"
    cfg._OPENAI_COMPATIBLE_URL = "https://first.invalid/v1"
    setattr(cfg, model_attr, "first-model")
    language = {"language": "English", "country": "United States", "enable": True}
    cfg._SELECTED_YOUR_LANGUAGES = {"1": {"1": language}}
    cfg._SELECTED_TARGET_LANGUAGES = {"1": {"1": dict(language, language="Japanese", country="Japan")}}
    for name in ("CONVERT_MESSAGE_TO_HIRAGANA", "CONVERT_MESSAGE_TO_ROMAJI",
                 "SEND_ONLY_TRANSLATED_MESSAGES", "OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES"):
        setattr(cfg, "_" + name, False)
    cfg._SEND_MESSAGE_FORMAT_PARTS = {}
    monkeypatch.setattr(config_module, "config", cfg)
    monkeypatch.setattr(model_module, "config", cfg)

    client = client_type()  # Only loads the local prompt, no SDK/network setup.
    llm = Mock()
    llm.invoke.return_value = AIMessage(content="訳文", response_metadata={})
    setattr(client, llm_attr, llm)
    translator = Translator()
    client_attr = {"OpenAI_Compatible": "openai_compatible_client",
                   "LMStudio": "lmstudio_client", "Ollama": "ollama_client"}.get(engine)
    if client_attr:
        setattr(translator, client_attr, client)
    else:
        translator._provider_clients[engine] = client
    model = object.__new__(Model)
    model._inited = True
    model.translation_history = []
    model.translation_history_max_items = 20
    model.translator = translator
    monkeypatch.setattr(translator, "translateCTranslate2", Mock(return_value="local"))

    def select(name):
        cfg.SELECTED_TRANSLATION_ENGINES = {"1": name, "2": "CTranslate2"}

    def translate(generation=None):
        result = model.getTranslate(engine, "English", "Japanese", "Japan", "current text",
                                    history_generation=generation)
        assert result == ("訳文", True)
        messages = llm.invoke.call_args.args[0]
        assert messages[1] == {"role": "user", "content": "current text"}
        return messages[0]["content"]

    return SimpleNamespace(cfg=cfg, engine=engine, model=model, model_attr=model_attr,
                           client=client, llm=llm, llm_attr=llm_attr, select=select, translate=translate)


def test_stable_destination_keeps_recent_history_and_prompt(app):
    for index in range(7):
        app.model.addTranslationHistory(["chat", "mic", "speaker"][index % 3], f"history-{index}")
    app.model.addTranslationHistory("ocr", "past OCR must be filtered")
    app.select(app.engine)  # Re-saving the same selection must keep context.
    prompt = app.translate()
    assert "Translate" in prompt
    assert "history-0" not in prompt and "history-1" not in prompt
    assert all(f"history-{index}" in prompt for index in range(2, 7))
    assert "past OCR must be filtered" not in prompt
    assert "[speaker]" in prompt and "[mic]" in prompt and "[chat]" in prompt
    assert "history-6" in app.translate()


def test_local_history_is_not_sent_to_new_engine(app):
    app.select("CTranslate2")
    app.model.addTranslationHistory("mic", "local-only conversation")
    app.select(app.engine)
    assert "local-only conversation" not in app.translate()


def test_cloud_engine_switch_only_sends_new_destinations_history(app):
    app.model.addTranslationHistory("chat", "engine A context")
    assert "engine A context" in app.translate()
    other_engine = "Groq_API" if app.engine == "OpenAI_API" else "OpenAI_API"
    other_client = OpenAIClient()
    other_llm = Mock()
    other_llm.invoke.return_value = AIMessage(content="訳文", response_metadata={})
    other_client.openai_llm = other_llm
    app.model.translator._provider_clients[other_engine] = other_client
    app.select(other_engine)
    app.model.addTranslationHistory("speaker", "engine B context")
    assert app.model.getTranslate(other_engine, "English", "Japanese", "Japan", "new text") == ("訳文", True)
    prompt = other_llm.invoke.call_args.args[0][0]["content"]
    assert "engine A context" not in prompt
    assert "engine B context" in prompt
    app.select(app.engine)
    prompt = app.translate()
    assert "engine A context" not in prompt and "engine B context" not in prompt


def test_switching_back_never_resurrects_history_even_without_messages_between(app):
    app.model.addTranslationHistory("chat", "old cloud context")
    assert "old cloud context" in app.translate()
    app.select("CTranslate2")
    app.select(app.engine)
    assert "old cloud context" not in app.translate()
    app.select("CTranslate2")
    app.model.addTranslationHistory("speaker", "private local conversation")
    app.select(app.engine)
    assert "private local conversation" not in app.translate()
    app.model.addTranslationHistory("chat", "new cloud context")
    assert "new cloud context" in app.translate()


def test_model_change_and_return_invalidate_history(app):
    app.model.addTranslationHistory("chat", "old model context")
    setattr(app.cfg, app.model_attr, "second-model")
    setattr(app.cfg, app.model_attr, "first-model")
    assert "old model context" not in app.translate()


@pytest.mark.parametrize("url_attr", ["LMSTUDIO_URL", "OPENAI_COMPATIBLE_URL"])
def test_endpoint_change_and_return_invalidate_history(app, url_attr):
    app.model.addTranslationHistory("chat", "old endpoint context")
    previous = getattr(app.cfg, url_attr)
    setattr(app.cfg, url_attr, "http://127.0.0.1:4321/v1")
    setattr(app.cfg, url_attr, previous)
    assert "old endpoint context" not in app.translate()


def test_translation_off_messages_and_prior_context_are_excluded(app):
    app.model.addTranslationHistory("chat", "before disabling")
    app.cfg.ENABLE_TRANSLATION = False
    app.model.addTranslationHistory("mic", "translation disabled")
    app.cfg.ENABLE_TRANSLATION = True
    prompt = app.translate()
    assert "before disabling" not in prompt and "translation disabled" not in prompt


def test_late_completion_cannot_seed_new_destination_or_consume_its_history(app):
    snapshot = MessageSnapshot.capture(app.cfg, CHAT_MESSAGE_SPEC, None)
    app.select("CTranslate2")
    app.select(app.engine)
    app.model.addTranslationHistory("chat", "late old message", snapshot=snapshot)
    app.model.addTranslationHistory("chat", "new destination message")
    assert "late old message" not in app.translate()
    assert "new destination message" not in app.translate(snapshot.translation_history_generation)
    assert "new destination message" in app.translate()
    app.model.addTranslationHistory("chat", "admitted while disabled",
                                    snapshot=replace(snapshot, translation_enabled=False,
                                                     translation_history_generation=app.cfg.translation_history_generation))
    assert "admitted while disabled" not in app.translate()


def test_copied_history_is_rechecked_at_dispatch(app):
    app.model.addTranslationHistory("chat", "stale handoff")
    history = app.model.getTranslationHistory()
    app.select("CTranslate2")
    app.select(app.engine)
    app.model.translator.translate(app.engine, "unused", "English", "Japanese", "Japan",
                                   "current text", context_history=history)
    assert "stale handoff" not in app.llm.invoke.call_args.args[0][0]["content"]


def test_empty_history_does_not_reuse_cached_adapter_context(app):
    app.client.setContextHistory([{"source": "chat", "text": "cached adapter context"}])
    assert "cached adapter context" not in app.translate()
    app.model.addTranslationHistory("chat", "request-local context")
    assert "request-local context" in app.translate()
    assert app.client._context_history[0]["text"] == "cached adapter context"
    app.model.clearTranslationHistory()
    assert "request-local context" not in app.translate()


def test_tab_and_credentials_changes_invalidate_history(app):
    app.model.addTranslationHistory("chat", "previous tab context")
    app.cfg.SELECTED_TAB_NO = "2"
    app.cfg.SELECTED_TAB_NO = "1"
    assert "previous tab context" not in app.translate()
    app.model.addTranslationHistory("chat", "previous account context")
    app.cfg.AUTH_KEYS = {app.engine: "another-fake-key"}
    assert "previous account context" not in app.translate()


def test_rejected_or_unchanged_settings_preserve_context(app):
    app.model.addTranslationHistory("chat", "stable context")
    with pytest.raises(ConfigValidationError):
        app.cfg.SELECTED_TRANSLATION_ENGINES = "invalid"
    setattr(app.cfg, app.model_attr, getattr(app.cfg, app.model_attr))
    assert "stable context" in app.translate()


def test_overlapping_requests_keep_their_own_history_and_sdk(app, monkeypatch):
    app.model.addTranslationHistory("chat", "first request context")
    new_llm = Mock()
    new_llm.invoke.return_value = AIMessage(content="new destination", response_metadata={})
    original_translate = type(app.client).translate

    def translate(request_client, text, input_lang, output_lang):
        if text == "first request":
            # Pause between taking the request snapshot and formatting its
            # prompt. A new destination must not replace this request's SDK
            # or inherit its context, even when requests overlap.
            setattr(app.cfg, app.model_attr, "second-model")
            setattr(app.client, app.llm_attr, new_llm)
            assert app.model.getTranslate(app.engine, "English", "Japanese", "Japan",
                                          "second request") == ("new destination", True)
        return original_translate(request_client, text, input_lang, output_lang)

    monkeypatch.setattr(type(app.client), "translate", translate)
    assert app.model.getTranslate(app.engine, "English", "Japanese", "Japan",
                                  "first request") == ("訳文", True)
    assert "first request context" in app.llm.invoke.call_args.args[0][0]["content"]
    assert "first request context" not in new_llm.invoke.call_args.args[0][0]["content"]
