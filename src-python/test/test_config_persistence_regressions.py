"""Config audit regressions with no application imports or live services.

Run with --noconftest: the legacy conftest imports the config singleton before
redirecting its path. Execute production definitions with fake dependencies
instead; all persistence tests use pytest's temporary directory.
"""

import ast
import copy
import errno
import json
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from errors import ErrorCode, VRCTError
from models.network_policy import redact_urls


SOURCE = Path(__file__).resolve().parents[1]
MAPS = ("SELECTED_YOUR_LANGUAGES", "SELECTED_TARGET_LANGUAGES", "SELECTED_TRANSLATION_ENGINES")
THRESHOLDS = (
    ("MIC_AVG_LOGPROB", "setMicAvgLogprob", -0.8, -2, 0),
    ("MIC_NO_SPEECH_PROB", "setMicNoSpeechProb", 0.6, 0, 1),
    ("SPEAKER_AVG_LOGPROB", "setSpeakerAvgLogprob", -0.8, -2, 0),
    ("SPEAKER_NO_SPEECH_PROB", "setSpeakerNoSpeechProb", 0.6, 0, 1),
)


class FakeTimer:
    def __init__(self, interval, function):
        self.interval, self.function = interval, function
        self.alive = False
        self.cancelled = False

    def start(self):
        self.alive = True

    def cancel(self):
        self.cancelled = True
        self.alive = False

    def is_alive(self):
        return self.alive

    def fire(self):
        assert self.alive
        try:
            # Like threading.Timer, is_alive remains true inside the callback.
            self.function()
        finally:
            self.alive = False


class InlineThread:
    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def definitions(filename, namespace, *, class_methods=None):
    """Load actual source bodies, omitting import-time singleton construction."""
    path = SOURCE / filename
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if class_methods is not None:
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Controller")
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in class_methods]
        tree.body = [cls]
    else:
        tree.body = [node for node in tree.body if
                     isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import)) or
                     isinstance(node, ast.ImportFrom) and node.module in {"os", "json", "secrets", "typing", "models.network_policy"} or
                     isinstance(node, ast.Assign) and not any(
                         isinstance(target, ast.Name) and target.id == "config" for target in node.targets)]
    exec(compile(tree, str(path), "exec"), namespace)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VRCT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "runtime_paths", SimpleNamespace(data_root=lambda _: tmp_path))
    languages = {"Japanese": {"Japan": {"Google": "ja"}}, "English": {"United States": {"Google": "en"}}}
    def normalize(value, *args):
        return value

    ns = dict(
        __file__=str(tmp_path / "config.py"), device_manager=None,
        transcription_lang=languages, translation_lang={}, ctranslate2_weights={}, whisper_models={},
        ocr_selectable_languages=(), DEFAULT_CTRANSLATE2_WEIGHT_TYPE="fake-weight",
        loadTranslationLanguages=lambda _: {"CTranslate2": {}, "OpenAI_API": {}},
        getComputeDeviceList=lambda: [{"device": "cpu", "compute_types": ["auto"]}],
        errorLogging=Mock(), printLog=Mock(), validateDictStructure=Mock(return_value=True),
        isValidIpAddress=Mock(return_value=True), isWildcardBindAddress=Mock(return_value=False),
        VoiceSettings=lambda: SimpleNamespace(to_dict=lambda: {}),
        DirectSettings=lambda: SimpleNamespace(to_dict=lambda: {}),
        normalize_settings=normalize, normalize_direct_settings=normalize,
        normalize_realtime_settings=normalize, normalize_speech_server_settings=normalize,
    )
    definitions("config.py", ns)
    ns["threading"] = SimpleNamespace(Timer=FakeTimer, Thread=InlineThread)
    ns["_auto_register_descriptors"]()
    config = object.__new__(ns["Config"])
    config.init_config()
    config._file_lock = threading.Lock()
    config._SELECTABLE_TRANSLATION_ENGINE_STATUS = {"OpenAI_API": True, "CTranslate2": True}
    config.on_save_failed, config.on_save_recovered = Mock(), Mock()
    controller_ns = dict(config=config, ConfigValidationError=ns["ConfigValidationError"],
                         ErrorCode=ErrorCode, VRCTError=VRCTError, nullcontext=nullcontext,
                         printLog=Mock(), copy=copy,
                         model=SimpleNamespace(findTranslationEngines=Mock(return_value=["CTranslate2", "OpenAI_API"])))
    methods = {row[1] for row in THRESHOLDS} | {
        "setSelectedYourLanguages", "setSelectedTargetLanguages", "setSelectedTranslationEngines",
        "setSelectedTabNo", "swapYourLanguageAndTargetLanguage", "getTranslationEngines",
        "updateTranslationEngineAndEngineList", "_updateTranslationEngineAndEngineListLocked",
    }
    definitions("controller.py", controller_ns, class_methods=methods)
    controller = controller_ns["Controller"]()
    controller._voice_settings_lock = threading.Lock()
    controller._language_settings_lock = threading.RLock()
    controller._cancelMicVoice = Mock()
    controller.fallbackUnsupportedLanguagesForEngine = Mock(return_value=False)
    controller.run_mapping = {key: key for key in ("selected_translation_engines", "translation_engines")}
    controller.run = Mock()
    return SimpleNamespace(config=config, controller=controller, ns=ns, path=tmp_path / "config.json")


def strict_json(text):
    def reject(value):
        raise AssertionError(f"Nonfinite JSON: {value}")
    return json.loads(text, parse_constant=reject)


@pytest.mark.parametrize("key,method,previous,lower,upper", THRESHOLDS)
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", float("nan"), float("inf"), -float("inf"), "1e999", None, True])
def test_threshold_rejection_keeps_previous(isolated, key, method, previous, lower, upper, value):
    config = isolated.config
    config.saveConfig = Mock()
    reply = getattr(isolated.controller, method)(value)
    assert reply["status"] == 400
    assert reply["result"]["error_code"] == "VALIDATION_CONFIG_VALUE_INVALID"
    assert reply["result"]["data"] == previous
    assert getattr(config, key) == previous
    config.saveConfig.assert_not_called()
    strict_json(json.dumps(reply, allow_nan=False))


@pytest.mark.parametrize("key,method,previous,lower,upper", THRESHOLDS)
def test_threshold_bounds_and_descriptor_validation(isolated, key, method, previous, lower, upper):
    config = isolated.config
    for value in (lower - 0.1, upper + 0.1):
        assert getattr(isolated.controller, method)(value)["status"] == 400
        assert getattr(config, key) == previous
    for value in (float("nan"), float("inf"), -float("inf"), None, True):
        with pytest.raises(isolated.ns["ConfigValidationError"]):
            setattr(config, key, value)
        assert getattr(config, key) == previous
    for value in (lower, upper):
        assert getattr(isolated.controller, method)(str(value)) == {"status": 200, "result": value}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_serialization_failure_preserves_last_good_file_and_recovers(isolated, value):
    config = isolated.config
    config.saveConfigToFile()
    original = isolated.path.read_bytes()
    # Bypass the descriptor to exercise the independent persistence defense.
    config._MESSAGE_BOX_RATIO = value
    config.saveConfigToFile()
    assert isolated.path.read_bytes() == original
    strict_json(isolated.path.read_text())
    assert not isolated.path.with_suffix(".json.tmp").exists()
    config.on_save_failed.assert_called_once_with("write_failed", str(isolated.path))
    config._MESSAGE_BOX_RATIO = 20
    config._save_retry_timer.fire()
    assert strict_json(isolated.path.read_text())["MESSAGE_BOX_RATIO"] == 20
    config.on_save_recovered.assert_called_once_with()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_ipc_nonfinite_result_uses_parseable_500_fallback(value):
    path = SOURCE / "utils.py"
    tree = ast.parse(path.read_text())
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"printResponse", "_shapeOf"}]
    lines = []
    ns = dict(Any=object, json=json, redact_urls=redact_urls, process_logger=Mock(), errorLogging=Mock(),
              _isSensitiveEndpoint=lambda _: False, _maskSensitiveData=lambda result: result,
              _CONVERSATION_ENDPOINTS=set(), _UNLOGGED_ENDPOINTS=set(),
              isQuietPoll=lambda *args: False, _enqueueResponseLine=lines.append)
    exec(compile(tree, str(path), "exec"), ns)
    ns["printResponse"](200, "/test", {"nested": [value]})
    assert len(lines) == 1
    reply = strict_json(lines[0])
    assert reply["status"] == 500
    assert reply["endpoint"] == "/test"
    ns["errorLogging"].assert_called_once_with()


@pytest.mark.parametrize("key,method", list(zip(MAPS, ("setSelectedYourLanguages", "setSelectedTargetLanguages", "setSelectedTranslationEngines"))))
@pytest.mark.parametrize("damage", ["empty", "missing_tab", "unknown_tab", "bad_tab", "missing_slot", "unknown_slot", "missing_field", "unknown_field"])
def test_invalid_map_structure_has_no_mutation_or_side_effects(isolated, key, method, damage):
    config = isolated.config
    previous = getattr(config, key)
    value = copy.deepcopy(previous)
    if damage == "empty":
        value = {}
    elif damage == "missing_tab":
        del value["2"]
    elif damage == "unknown_tab":
        value["4"] = value["1"]
    elif damage == "bad_tab" or key == "SELECTED_TRANSLATION_ENGINES":
        value["1"] = []
    elif damage == "missing_slot":
        del value["1"]["1"]
    elif damage == "unknown_slot":
        value["1"]["4"] = value["1"]["1"]
    elif damage == "missing_field":
        del value["1"]["1"]["country"]
    else:
        value["1"]["1"]["extra"] = True
    config.saveConfig = Mock()
    reply = getattr(isolated.controller, method)(value)
    assert reply["status"] == 400
    assert reply["result"]["error_code"] == "VALIDATION_CONFIG_VALUE_INVALID"
    assert reply["result"]["data"] == previous
    assert getattr(config, key) == previous
    config.saveConfig.assert_not_called()
    isolated.controller._cancelMicVoice.assert_not_called()
    isolated.controller.run.assert_not_called()


def test_invalid_language_value_still_falls_back_per_slot(isolated):
    config = isolated.config
    value = config.SELECTED_TARGET_LANGUAGES
    value["1"]["1"]["language"] = []
    value["2"]["1"] = {"language": "Japanese", "country": "Japan", "enable": True}
    config.SELECTED_TARGET_LANGUAGES = value
    assert config.SELECTED_TARGET_LANGUAGES["1"]["1"]["language"] == "English"
    assert config.SELECTED_TARGET_LANGUAGES["2"]["1"]["language"] == "Japanese"


def test_startup_repairs_broken_parts_and_nonfinite_thresholds(isolated):
    config = isolated.config
    defaults = {key: getattr(config, key) for key in MAPS}
    valid = {"language": "English", "country": "United States", "enable": True}
    broken = {
        "SELECTED_YOUR_LANGUAGES": {"1": {"1": valid}, "2": []},
        "SELECTED_TARGET_LANGUAGES": {"1": {"1": {}}, "2": {}, "4": {}},
        "SELECTED_TRANSLATION_ENGINES": {"1": "CTranslate2", "2": {}},
        "MIC_AVG_LOGPROB": float("nan"), "SPEAKER_NO_SPEECH_PROB": float("inf"),
    }
    isolated.path.write_text(json.dumps(broken))
    config.load_config()
    defaults["SELECTED_YOUR_LANGUAGES"]["1"]["1"] = valid
    defaults["SELECTED_TRANSLATION_ENGINES"]["1"] = "CTranslate2"
    for key in MAPS:
        assert getattr(config, key) == defaults[key]
    assert config.MIC_AVG_LOGPROB == -0.8
    assert config.SPEAKER_NO_SPEECH_PROB == 0.6
    saved = strict_json(isolated.path.read_text())
    assert saved["SELECTED_YOUR_LANGUAGES"] == defaults["SELECTED_YOUR_LANGUAGES"]
    isolated.controller.updateTranslationEngineAndEngineList()  # no KeyError


@pytest.mark.parametrize("broken", [{}, [], None])
def test_startup_empty_or_wrong_type_maps_use_defaults(isolated, broken):
    config = isolated.config
    defaults = {key: getattr(config, key) for key in MAPS}
    isolated.path.write_text(json.dumps({key: broken for key in MAPS}))
    config.load_config()
    for key in MAPS:
        assert getattr(config, key) == defaults[key]
    strict_json(isolated.path.read_text())


def test_old_debounce_cannot_overwrite_new_immediate_save(isolated):
    config = isolated.config
    snapshot_taken, resume_old, new_waiting = (threading.Event() for _ in range(3))
    real_lock = threading.Lock()

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == "new-save":
                new_waiting.set()
            real_lock.acquire()

        def __exit__(self, *args):
            real_lock.release()

    config._file_lock = ObservedLock()
    failures = []

    def snapshot(instance):
        value = instance.MESSAGE_BOX_RATIO
        if threading.current_thread().name == "old-save":
            snapshot_taken.set()
            if not resume_old.wait(5):
                failures.append("old save was not released")
        return value

    isolated.ns["json_serializable_vars"] = {"MESSAGE_BOX_RATIO": snapshot}
    old = threading.Thread(target=config.saveConfigToFile, name="old-save", daemon=True)
    new = threading.Thread(target=lambda: setattr(config, "MESSAGE_BOX_RATIO", 20), name="new-save", daemon=True)
    old.start()
    try:
        assert snapshot_taken.wait(5)
        new.start()
        assert new_waiting.wait(5)
        # Pre-fix: the old snapshot is outside the lock, so the new save can
        # complete first. Post-fix: it waits and writes last. Release either way.
        new.join(0.1)
    finally:
        resume_old.set()
        old.join(5)
        if new.ident is not None:
            new.join(5)
    assert not old.is_alive() and not new.is_alive()
    assert not failures
    assert strict_json(isolated.path.read_text())["MESSAGE_BOX_RATIO"] == 20


def test_retry_rearms_across_repeated_failures_and_stops_on_success(isolated):
    config = isolated.config
    real_replace = isolated.ns["os_replace"]
    isolated.ns["os_replace"] = Mock(side_effect=OSError(errno.ENOSPC, "fake full disk"))
    config.saveConfigToFile()
    timers = []
    for _ in range(3):
        timer = config._save_retry_timer
        timers.append(timer)
        assert timer.interval == 30
        timer.fire()
        assert config._save_retry_timer is not timer
        assert config._save_retry_timer.is_alive()
    assert isolated.ns["os_replace"].call_count == 4
    config.on_save_failed.assert_called_once_with("disk_full", str(isolated.path))
    config.on_save_recovered.assert_not_called()
    isolated.ns["os_replace"] = real_replace
    config._save_retry_timer.fire()
    assert config._save_retry_timer is None
    assert all(not timer.is_alive() for timer in timers)
    config.on_save_recovered.assert_called_once_with()
    strict_json(isolated.path.read_text())


def test_success_cancels_a_pending_retry_and_ignores_its_late_callback(isolated):
    config = isolated.config
    real_replace = isolated.ns["os_replace"]
    isolated.ns["os_replace"] = Mock(side_effect=OSError(errno.EACCES, "fake permission failure"))
    config.saveConfigToFile()
    pending = config._save_retry_timer
    isolated.ns["os_replace"] = Mock(wraps=real_replace)
    config.saveConfigToFile()
    assert pending.cancelled
    pending.function()  # already dispatched before cancellation
    assert isolated.ns["os_replace"].call_count == 1
    assert config._save_retry_timer is None


def test_swap_preserves_cloud_engine_and_reconciles_final_pair_once(isolated):
    config, controller = isolated.config, isolated.controller
    config._SELECTED_TRANSLATION_ENGINES = {tab: "OpenAI_API" for tab in ("1", "2", "3")}
    old_your, old_target = config.SELECTED_YOUR_LANGUAGES, config.SELECTED_TARGET_LANGUAGES
    reconcile = controller.updateTranslationEngineAndEngineList
    pairs = []

    def observe():
        assert controller._voice_settings_lock.locked()
        pairs.append((config.SELECTED_YOUR_LANGUAGES, config.SELECTED_TARGET_LANGUAGES))
        reconcile()

    controller.updateTranslationEngineAndEngineList = observe
    reply = controller.swapYourLanguageAndTargetLanguage()
    assert reply["status"] == 200
    assert len(pairs) == 1
    assert pairs[0][0]["1"]["1"] == old_target["1"]["1"]
    assert pairs[0][1]["1"]["1"] == old_your["1"]["1"]
    assert reply["result"] == {"your": pairs[0][0], "target": pairs[0][1]}
    assert config.SELECTED_TRANSLATION_ENGINES["1"] == "OpenAI_API"
    assert config.SELECTED_YOUR_LANGUAGES["2"] == old_your["2"]
    controller._cancelMicVoice.assert_called_once_with()
    controller.fallbackUnsupportedLanguagesForEngine.assert_called_once_with("1", "OpenAI_API")


def test_pair_validation_rejects_invalid_second_map_before_first_commit(isolated):
    config = isolated.config
    old_your, old_target = config.SELECTED_YOUR_LANGUAGES, config.SELECTED_TARGET_LANGUAGES
    your = copy.deepcopy(old_your)
    your["1"]["1"] = old_target["1"]["1"]
    config.saveConfig = Mock()
    with pytest.raises(isolated.ns["ConfigValidationError"]):
        config.setSelectedLanguages(your, {})
    assert config.SELECTED_YOUR_LANGUAGES == old_your
    assert config.SELECTED_TARGET_LANGUAGES == old_target
    config.saveConfig.assert_not_called()
