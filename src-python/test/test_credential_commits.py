"""Credential transactions with synthetic keys and entirely stubbed providers."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, current_thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as controller_module
from config import Config
from controller import Controller
from model import Model
from models.translation import translation_translator as translator_module
from models.translation.translation_providers import TRANSLATION_PROVIDER_REGISTRY


TRANSLATION = [
    ("Plamo_API", "Plamo", "p" * 72),
    ("Gemini_API", "Gemini", "g" * 39),
    ("OpenAI_API", "OpenAI", "sk-" + "a" * 161),
    ("Groq_API", "Groq", "gsk" + "g" * 37),
    ("OpenRouter_API", "OpenRouter", "r" * 20),
    ("OpenAI_Compatible", "OpenAICompatible", "synthetic-compatible-key"),
    ("DeepL_API", "Deepl", "d" * 36),
]
TRANSCRIPTION = [
    ("Groq_Whisper", "GroqWhisper"), ("OpenAI_Whisper", "OpenAIWhisper"),
    ("Custom_Whisper", "CustomWhisper"), ("Deepgram", "Deepgram"),
]


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.auth_key = args[0] if args else None  # DeepL constructor
        self.base_url = kwargs.get("base_url")
        self.ready = False
        self._client = Mock()  # DeepL probe transport, replaced after success.

    def setAuthKey(self, key):
        self.auth_key = key
        return True

    def getModelList(self):
        return ["new-model", "working-model"]

    def setModel(self, model):
        self.selected_model = model
        return True

    def updateClient(self):
        self.ready = True

    def translate_text(self, text, target_lang):
        self.ready = True
        return "synthetic-result"


@pytest.fixture
def subject(monkeypatch):
    # Real descriptors and commit helper, with no singleton init or disk saves.
    cfg = object.__new__(Config)
    cfg.saveConfig = Mock()
    cfg._AUTH_KEYS = {engine: "synthetic-old-key" for engine, _, _ in TRANSLATION}
    cfg._TRANSCRIPTION_AUTH_KEYS = {engine: "synthetic-old-key" for engine, _ in TRANSCRIPTION}
    cfg.SELECTABLE_TRANSLATION_ENGINE_STATUS = {engine: True for engine, _, _ in TRANSLATION}
    cfg.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS = {engine: True for engine, _ in TRANSCRIPTION}
    cfg._OPENAI_COMPATIBLE_URL = "https://previous.invalid/v1"
    cfg._TRANSCRIPTION_CUSTOM_URL = "https://transcription.invalid/v1"
    cfg._PATH_LOCAL = "."
    for prefix in ["PLAMO", "GEMINI", "OPENAI", "GROQ", "OPENROUTER", "OPENAI_COMPATIBLE",
                   "GROQ_WHISPER", "OPENAI_WHISPER", "CUSTOM_WHISPER", "DEEPGRAM"]:
        setattr(cfg, f"SELECTABLE_{prefix}_MODEL_LIST", ["working-model"])
        setattr(cfg, f"SELECTED_{prefix}_MODEL", "working-model")
    cfg.DEEPGRAM_MODEL_LANGUAGES = {"working-model": ["en"]}

    translator = translator_module.Translator()
    previous = FakeClient()
    previous.ready = True
    for engine, _, _ in TRANSLATION:
        translator.commitCredential(engine, (previous, [], None))
    for engine, spec in TRANSLATION_PROVIDER_REGISTRY.items():
        monkeypatch.setitem(TRANSLATION_PROVIDER_REGISTRY, engine, replace(spec, client_class=FakeClient))
    monkeypatch.setattr(translator_module, "OpenAICompatibleClient", FakeClient)
    monkeypatch.setattr(translator_module, "DeepLClient", FakeClient)

    # Exercise the actual Model facade as well as the actual Translator methods.
    facade = object.__new__(Model)
    facade.translator = translator
    facade.ensure_initialized = lambda: None
    facade.authenticationTranscriptionApiKey = Mock(return_value=True)
    facade.getTranscriptionApiModelList = Mock(return_value=["new-model", "working-model"])
    facade.authenticationDeepgramApiKey = Mock(return_value=True)
    facade.getDeepgramModelListDetailed = Mock(return_value=[
        {"name": "new-model", "languages": ["ja"]},
        {"name": "working-model", "languages": ["en"]},
    ])
    monkeypatch.setattr(controller_module, "config", cfg)
    monkeypatch.setattr(controller_module, "model", facade)
    monkeypatch.setattr(controller_module, "errorLogging", Mock())
    monkeypatch.setattr(controller_module, "printLog", Mock())
    control = object.__new__(Controller)
    control.run_mapping = {f"{kind}_{prefix}_model{suffix}": f"/run/{kind}_{prefix}_model{suffix}"
                           for prefix in ["plamo", "gemini", "openai", "groq", "openrouter",
                                          "openai_compatible", "groq_whisper", "openai_whisper",
                                          "custom_whisper", "deepgram"]
                           for kind, suffix in [("selectable", "_list"), ("selected", "")]}
    control.run = Mock()
    control.updateTranslationEngineAndEngineList = Mock()
    control.updateTranscriptionEngine = Mock()
    return SimpleNamespace(config=cfg, translator=translator, model=facade, controller=control, previous=previous)


def live_client(s, engine):
    if engine == "DeepL_API":
        return s.translator.deepl_client
    if engine == "OpenAI_Compatible":
        return s.translator.openai_compatible_client
    return s.translator._provider_clients[engine]


def model_prefix(engine):
    return engine.removesuffix("_API").upper()


@pytest.mark.parametrize("engine,name,key", TRANSLATION)
@pytest.mark.parametrize("available", [False, True])
def test_translation_success_commits_ready_client(subject, engine, name, key, available):
    s = subject
    s.config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] = available
    result = getattr(s.controller, f"set{name}AuthKey")(key)
    assert result == {"status": 200, "result": key}
    assert s.config.AUTH_KEYS[engine] == key
    client = live_client(s, engine)
    assert client is not s.previous and client.ready and client.auth_key == key
    assert s.config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] is True
    if engine != "DeepL_API":
        assert getattr(s.config, f"SELECTED_{model_prefix(engine)}_MODEL") == "working-model"
        assert client.selected_model == "working-model"


@pytest.mark.parametrize("engine,name,key", TRANSLATION[:-1])
@pytest.mark.parametrize("failure", ["auth", "empty", "list_exception", "invalid_model", "selection", "client"])
@pytest.mark.parametrize("available", [False, True])
def test_translation_failure_preserves_all_working_state(subject, monkeypatch, engine, name, key, failure, available):
    s = subject
    s.config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] = available
    method, replacement = {
        "auth": ("setAuthKey", Mock(return_value=False)),
        "empty": ("getModelList", Mock(return_value=[])),
        "list_exception": ("getModelList", Mock(side_effect=RuntimeError("synthetic provider failure"))),
        "invalid_model": ("getModelList", Mock(return_value=[None])),
        "selection": ("setModel", Mock(return_value=False)),
        "client": ("updateClient", Mock(side_effect=RuntimeError("synthetic client failure"))),
    }[failure]
    monkeypatch.setattr(FakeClient, method, replacement)
    s.config.saveConfig.reset_mock()
    result = getattr(s.controller, f"set{name}AuthKey")(key)
    expected = ("AUTH_OPENAI_COMPATIBLE_FAILED" if engine == "OpenAI_Compatible"
                else TRANSLATION_PROVIDER_REGISTRY[engine].error_auth_failed.value)
    assert result["status"] == 400 and result["result"]["error_code"] == expected
    assert result["result"]["data"] == "synthetic-old-key"
    assert s.config.AUTH_KEYS[engine] == "synthetic-old-key"
    assert s.config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] is available
    assert live_client(s, engine) is s.previous
    assert getattr(s.config, f"SELECTABLE_{model_prefix(engine)}_MODEL_LIST") == ["working-model"]
    assert getattr(s.config, f"SELECTED_{model_prefix(engine)}_MODEL") == "working-model"
    s.config.saveConfig.assert_not_called()
    s.controller.run.assert_not_called()


def test_deepl_failure_preserves_client_and_key(subject, monkeypatch):
    monkeypatch.setattr(FakeClient, "translate_text", Mock(side_effect=RuntimeError("synthetic error")))
    result = subject.controller.setDeeplAuthKey("d" * 36)
    assert result["result"]["error_code"] == "AUTH_DEEPL_FAILED"
    assert result["result"]["data"] == subject.config.AUTH_KEYS["DeepL_API"] == "synthetic-old-key"
    assert live_client(subject, "DeepL_API") is subject.previous


@pytest.mark.parametrize("engine,name", TRANSCRIPTION)
@pytest.mark.parametrize("failure", [None, "empty", "discovery", "auth"])
@pytest.mark.parametrize("available", [False, True])
def test_transcription_prepare_and_commit(subject, engine, name, failure, available):
    s = subject
    s.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = available
    discovery = (s.model.getDeepgramModelListDetailed if engine == "Deepgram"
                 else s.model.getTranscriptionApiModelList)
    auth = (s.model.authenticationDeepgramApiKey if engine == "Deepgram"
            else s.model.authenticationTranscriptionApiKey)
    if failure == "empty":
        discovery.return_value = []
    elif failure == "discovery":
        discovery.side_effect = RuntimeError("synthetic discovery failure")
    elif failure == "auth":
        auth.return_value = False
    s.config.saveConfig.reset_mock()
    result = getattr(s.controller, f"set{name}AuthKey")("synthetic-new-key")
    assert result["status"] == (400 if failure else 200)
    assert s.config.TRANSCRIPTION_AUTH_KEYS[engine] == ("synthetic-old-key" if failure else "synthetic-new-key")
    assert s.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] is (available if failure else True)
    assert getattr(s.config, f"SELECTED_{engine.upper()}_MODEL") == "working-model"
    if failure:
        assert result["result"]["error_code"] == "TRANSCRIPTION_API_AUTH_FAILED"
        assert result["result"]["data"] == "synthetic-old-key"
        assert getattr(s.config, f"SELECTABLE_{engine.upper()}_MODEL_LIST") == ["working-model"]
        s.config.saveConfig.assert_not_called()
        s.controller.run.assert_not_called()
    else:
        assert getattr(s.config, f"SELECTABLE_{engine.upper()}_MODEL_LIST") == ["new-model", "working-model"]


def test_deepgram_missing_language_metadata_is_checked_before_commit(subject):
    subject.model.getDeepgramModelListDetailed.return_value = [{"name": "new-model"}]
    result = subject.controller.setDeepgramAuthKey("synthetic-new-key")
    assert result["result"]["error_code"] == "TRANSCRIPTION_API_AUTH_FAILED"
    assert subject.config.TRANSCRIPTION_AUTH_KEYS["Deepgram"] == "synthetic-old-key"
    assert subject.config.DEEPGRAM_MODEL_LANGUAGES == {"working-model": ["en"]}
    assert subject.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS["Deepgram"] is True


@pytest.mark.parametrize("failure", ["empty", "auth", "client"])
def test_url_failure_restores_url_without_replacing_client(subject, monkeypatch, failure):
    method, replacement = {
        "empty": ("getModelList", Mock(return_value=[])),
        "auth": ("setAuthKey", Mock(return_value=False)),
        "client": ("updateClient", Mock(side_effect=RuntimeError("synthetic failure"))),
    }[failure]
    monkeypatch.setattr(FakeClient, method, replacement)
    result = subject.controller.setOpenAICompatibleURL("https://candidate.invalid/v1")
    replacement.assert_called_once()
    assert result["status"] == 400
    assert result["result"]["error_code"] == "CONNECTION_OPENAI_COMPATIBLE_URL_INVALID"
    assert result["result"]["data"] == subject.config.OPENAI_COMPATIBLE_URL == "https://previous.invalid/v1"
    assert subject.config.AUTH_KEYS["OpenAI_Compatible"] == "synthetic-old-key"
    assert live_client(subject, "OpenAI_Compatible") is subject.previous
    assert subject.config.SELECTABLE_TRANSLATION_ENGINE_STATUS["OpenAI_Compatible"] is True
    assert subject.config.SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST == ["working-model"]
    subject.controller.run.assert_not_called()


def test_url_success_commits_prepared_client(subject):
    result = subject.controller.setOpenAICompatibleURL("https://candidate.invalid/v1")
    assert result == {"status": 200, "result": "https://candidate.invalid/v1"}
    assert subject.config.OPENAI_COMPATIBLE_URL == result["result"]
    client = live_client(subject, "OpenAI_Compatible")
    assert client.ready and client.base_url == result["result"]
    assert client.auth_key == "synthetic-old-key"


def test_url_without_a_key_only_saves_url(subject):
    subject.config.updateCredential("AUTH_KEYS", "OpenAI_Compatible", None)
    subject.model.prepareTranslatorCredential = Mock(side_effect=AssertionError("Must not authenticate"))
    result = subject.controller.setOpenAICompatibleURL("https://candidate.invalid/v1")
    assert result == {"status": 200, "result": "https://candidate.invalid/v1"}
    subject.model.prepareTranslatorCredential.assert_not_called()
    assert live_client(subject, "OpenAI_Compatible") is subject.previous


@pytest.mark.parametrize("engine,name,key", TRANSLATION[:-1])
def test_translation_candidate_cannot_overwrite_newer_model_selection(subject, engine, name, key):
    s = subject
    prefix = model_prefix(engine)
    setattr(s.config, f"SELECTABLE_{prefix}_MODEL_LIST", ["working-model", "new-model"])
    original = s.model.prepareTranslatorCredential

    def prepare(*args, **kwargs):
        candidate = original(*args, **kwargs)
        assert getattr(s.controller, f"set{name}Model")("new-model") == {
            "status": 200, "result": "new-model",
        }
        return candidate

    s.model.prepareTranslatorCredential = prepare
    result = getattr(s.controller, f"set{name}AuthKey")(key)
    assert result["status"] == 400
    assert result["result"]["data"] == s.config.AUTH_KEYS[engine] == "synthetic-old-key"
    assert getattr(s.config, f"SELECTED_{prefix}_MODEL") == "new-model"
    assert live_client(s, engine) is s.previous
    assert live_client(s, engine).selected_model == "new-model"
    s.controller.run.assert_not_called()


def test_compatible_url_candidate_cannot_overwrite_newer_model_selection(subject):
    s = subject
    s.config.SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST = ["working-model", "new-model"]
    original = s.model.prepareTranslatorCredential

    def prepare(*args, **kwargs):
        candidate = original(*args, **kwargs)
        assert s.controller.setOpenAICompatibleModel("new-model")["status"] == 200
        return candidate

    s.model.prepareTranslatorCredential = prepare
    result = s.controller.setOpenAICompatibleURL("https://candidate.invalid/v1")
    assert result["status"] == 400
    assert result["result"]["data"] == s.config.OPENAI_COMPATIBLE_URL == "https://previous.invalid/v1"
    assert s.config.SELECTED_OPENAI_COMPATIBLE_MODEL == live_client(s, "OpenAI_Compatible").selected_model == "new-model"
    assert live_client(s, "OpenAI_Compatible") is s.previous
    s.controller.run.assert_not_called()


@pytest.mark.parametrize("failure", ["auth", "empty", "invalid_model", "discovery"])
@pytest.mark.parametrize("available", [False, True])
def test_custom_whisper_url_failure_preserves_working_state(subject, failure, available):
    s = subject
    s.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS["Custom_Whisper"] = available
    if failure == "auth":
        s.model.authenticationTranscriptionApiKey.return_value = False
    elif failure == "discovery":
        s.model.getTranscriptionApiModelList.side_effect = RuntimeError("synthetic failure")
    else:
        s.model.getTranscriptionApiModelList.return_value = [] if failure == "empty" else [None]
    s.config.saveConfig.reset_mock()
    result = s.controller.setCustomWhisperURL("https://candidate.invalid/v1")
    assert result["status"] == 400
    assert result["result"]["error_code"] == (
        "GENERAL_EXCEPTION" if failure == "discovery" else "CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID"
    )
    assert result["result"]["data"] == s.config.TRANSCRIPTION_CUSTOM_URL == "https://transcription.invalid/v1"
    assert s.config.TRANSCRIPTION_AUTH_KEYS["Custom_Whisper"] == "synthetic-old-key"
    assert s.config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST == ["working-model"]
    assert s.config.SELECTED_CUSTOM_WHISPER_MODEL == "working-model"
    assert s.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS["Custom_Whisper"] is available
    s.config.saveConfig.assert_not_called()
    s.controller.run.assert_not_called()
    s.controller.updateTranscriptionEngine.assert_not_called()


@pytest.mark.parametrize("change", ["delete", "replace", "url"])
def test_custom_whisper_url_candidate_rejected_after_newer_setting(subject, change):
    s = subject

    def discover(**kwargs):
        if change == "delete":
            assert s.controller.delCustomWhisperAuthKey()["status"] == 200
        elif change == "replace":
            s.config.updateCredential("TRANSCRIPTION_AUTH_KEYS", "Custom_Whisper", "synthetic-other-key")
        else:
            s.config.TRANSCRIPTION_CUSTOM_URL = "https://other.invalid/v1"
        s.config.saveConfig.reset_mock()
        s.controller.run.reset_mock()
        s.controller.updateTranscriptionEngine.reset_mock()
        return ["new-model"]

    s.model.getTranscriptionApiModelList.side_effect = discover
    result = s.controller.setCustomWhisperURL("https://candidate.invalid/v1")
    assert result["status"] == 400
    assert result["result"]["error_code"] == "CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID"
    assert result["result"]["data"] == s.config.TRANSCRIPTION_CUSTOM_URL == (
        "https://other.invalid/v1" if change == "url" else "https://transcription.invalid/v1"
    )
    assert s.config.TRANSCRIPTION_AUTH_KEYS["Custom_Whisper"] == {
        "delete": None, "replace": "synthetic-other-key", "url": "synthetic-old-key",
    }[change]
    assert s.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS["Custom_Whisper"] is (change != "delete")
    assert s.config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST == ([] if change == "delete" else ["working-model"])
    assert s.config.SELECTED_CUSTOM_WHISPER_MODEL == (None if change == "delete" else "working-model")
    s.config.saveConfig.assert_not_called()
    s.controller.run.assert_not_called()
    s.controller.updateTranscriptionEngine.assert_not_called()


@pytest.mark.parametrize("models,selected", [(["new-model", "working-model"], "working-model"),
                                           (["new-model"], "new-model")])
def test_custom_whisper_url_success_commits_validated_state(subject, models, selected):
    s = subject
    s.model.getTranscriptionApiModelList.return_value = models
    result = s.controller.setCustomWhisperURL("https://candidate.invalid/v1")
    assert result == {"status": 200, "result": "https://candidate.invalid/v1"}
    assert s.config.TRANSCRIPTION_CUSTOM_URL == result["result"]
    assert s.config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST == models
    assert s.config.SELECTED_CUSTOM_WHISPER_MODEL == selected
    assert s.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS["Custom_Whisper"] is True
    s.controller.updateTranscriptionEngine.assert_called_once()


@pytest.mark.parametrize("engine,name,key", TRANSLATION[:-1])
def test_translation_falls_back_to_first_candidate_model(subject, engine, name, key):
    # A previously selected model has disappeared from the new provider's list.
    prefix = model_prefix(engine)
    setattr(subject.config, f"SELECTABLE_{prefix}_MODEL_LIST", ["removed-model"])
    setattr(subject.config, f"SELECTED_{prefix}_MODEL", "removed-model")
    result = getattr(subject.controller, f"set{name}AuthKey")(key)
    assert result["status"] == 200
    assert getattr(subject.config, f"SELECTED_{prefix}_MODEL") == "new-model"
    assert live_client(subject, engine).selected_model == "new-model"


@pytest.mark.parametrize("engine,name", TRANSCRIPTION)
def test_transcription_falls_back_to_first_candidate_model(subject, engine, name):
    setattr(subject.config, f"SELECTABLE_{engine.upper()}_MODEL_LIST", ["removed-model"])
    setattr(subject.config, f"SELECTED_{engine.upper()}_MODEL", "removed-model")
    result = getattr(subject.controller, f"set{name}AuthKey")("synthetic-new-key")
    assert result["status"] == 200
    assert getattr(subject.config, f"SELECTED_{engine.upper()}_MODEL") == "new-model"


@pytest.mark.parametrize("changing_url", [False, True])
def test_compatible_candidate_rejected_if_other_setting_changes_during_check(subject, changing_url):
    s = subject
    original = s.model.prepareTranslatorCredential
    def prepare(*args, **kwargs):
        candidate = original(*args, **kwargs)
        # Simulate a second request committing while the provider check ran.
        with s.config.credential_lock:
            if changing_url:
                s.config.updateCredential("AUTH_KEYS", "OpenAI_Compatible", "synthetic-other-key")
            else:
                s.config.OPENAI_COMPATIBLE_URL = "https://other.invalid/v1"
        return candidate
    s.model.prepareTranslatorCredential = prepare
    if changing_url:
        result = s.controller.setOpenAICompatibleURL("https://candidate.invalid/v1")
        assert result["result"]["error_code"] == "CONNECTION_OPENAI_COMPATIBLE_URL_INVALID"
        assert result["result"]["data"] == s.config.OPENAI_COMPATIBLE_URL == "https://previous.invalid/v1"
        assert s.config.AUTH_KEYS["OpenAI_Compatible"] == "synthetic-other-key"
    else:
        result = s.controller.setOpenAICompatibleAuthKey("synthetic-candidate-key")
        assert result["result"]["error_code"] == "AUTH_OPENAI_COMPATIBLE_FAILED"
        assert result["result"]["data"] == s.config.AUTH_KEYS["OpenAI_Compatible"] == "synthetic-old-key"
        assert s.config.OPENAI_COMPATIBLE_URL == "https://other.invalid/v1"
    assert result["status"] == 400
    assert live_client(s, "OpenAI_Compatible") is s.previous
    s.controller.run.assert_not_called()


@pytest.mark.parametrize("transcription", [False, True])
def test_overlapping_provider_checks_commit_both_keys(subject, monkeypatch, transcription):
    s = subject
    barrier = Barrier(2)
    if transcription:
        def authenticate(**kwargs):
            barrier.wait(timeout=5)
            return True
        s.model.authenticationTranscriptionApiKey.side_effect = authenticate
        methods = [s.controller.setGroqWhisperAuthKey, s.controller.setOpenAIWhisperAuthKey]
        keys = ["synthetic-groq", "synthetic-openai"]
        engines = ["Groq_Whisper", "OpenAI_Whisper"]
        map_name = "TRANSCRIPTION_AUTH_KEYS"
    else:
        original = FakeClient.setAuthKey
        def authenticate(client, key):
            barrier.wait(timeout=5)  # Provider checks must not hold the shared commit lock.
            return original(client, key)
        monkeypatch.setattr(FakeClient, "setAuthKey", authenticate)
        methods = [s.controller.setOpenAIAuthKey, s.controller.setGroqAuthKey]
        keys = ["sk-" + "a" * 161, "gsk" + "g" * 37]
        engines = ["OpenAI_API", "Groq_API"]
        map_name = "AUTH_KEYS"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(method, key) for method, key in zip(methods, keys)]
        assert [future.result(timeout=10)["status"] for future in futures] == [200, 200]
    assert all(getattr(s.config, map_name)[engine] == key for engine, key in zip(engines, keys))
    if not transcription:
        assert all(live_client(s, engine).auth_key == key for engine, key in zip(engines, keys))


@pytest.mark.parametrize("map_name,engines", [
    ("AUTH_KEYS", ["OpenAI_API", "Groq_API"]),
    ("TRANSCRIPTION_AUTH_KEYS", ["OpenAI_Whisper", "Groq_Whisper"]),
])
def test_map_read_cannot_be_interleaved_with_another_commit(subject, map_name, engines):
    read, resume, second_started = Event(), Event(), Event()
    class PausingConfig(Config):
        def __getattribute__(self, name):
            value = super().__getattribute__(name)
            if name == map_name and current_thread().name.endswith("_0") and not read.is_set():
                read.set()
                assert resume.wait(5)
            return value
    subject.config.__class__ = PausingConfig
    def second():
        second_started.set()
        subject.config.updateCredential(map_name, engines[1], "synthetic-second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(subject.config.updateCredential, map_name, engines[0], "synthetic-first")
        try:
            assert read.wait(5)
            other = pool.submit(second)
            assert second_started.wait(5)
            assert not other.done()  # It cannot overwrite the snapshot held by first.
        finally:
            resume.set()
        first.result(timeout=5)
        other.result(timeout=5)
    assert getattr(subject.config, map_name)[engines[0]] == "synthetic-first"
    assert getattr(subject.config, map_name)[engines[1]] == "synthetic-second"


@pytest.mark.parametrize("engine,name,key", TRANSLATION)
def test_translation_delete_changes_only_its_key(subject, engine, name, key):
    before = subject.config.AUTH_KEYS
    result = getattr(subject.controller, f"del{name}AuthKey")()
    assert result == {"status": 200, "result": None}
    assert subject.config.AUTH_KEYS == {**before, engine: None}
    assert subject.config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] is False


@pytest.mark.parametrize("engine,name", TRANSCRIPTION)
def test_transcription_delete_changes_only_its_key(subject, engine, name):
    before = subject.config.TRANSCRIPTION_AUTH_KEYS
    result = getattr(subject.controller, f"del{name}AuthKey")()
    assert result == {"status": 200, "result": None}
    assert subject.config.TRANSCRIPTION_AUTH_KEYS == {**before, engine: None}
    assert subject.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] is False
