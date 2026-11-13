"""Settings validation regressions without importing the live config singleton."""

import ast
import copy
import functools
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from errors import ErrorCode, VRCTError
from test_config_persistence_regressions import SOURCE, definitions, isolated, strict_json  # noqa: F401


CPU = {"device": "cpu", "device_index": 0, "device_name": "cpu", "compute_types": ["auto", "float32"]}
GPU = {"device": "cuda", "device_index": 0, "device_name": "Test RTX", "compute_types": ["auto", "float16", "float32"]}
OVERLAYS = ("OVERLAY_SMALL_LOG_SETTINGS", "OVERLAY_LARGE_LOG_SETTINGS",
            "OVERLAY_VR_PANEL_SETTINGS", "OVERLAY_VR_LAUNCHER_SETTINGS")
ASR_INTEGERS = [
    (f"{source}_{suffix}", upper)
    for source in ("MIC", "SPEAKER")
    for suffix, upper in (("THRESHOLD", 2000), ("RECORD_TIMEOUT", 30),
                          ("PHRASE_TIMEOUT", 30), ("MAX_PHRASES", 30 if source == "MIC" else 60),
                          ("NO_REPEAT_NGRAM_SIZE", None))
]
NULLABLE = ("SELECTED_TRANSCRIPTION_ENGINE",) + tuple(
    f"SELECTED_{provider}_MODEL" for provider in
    ("PLAMO", "GEMINI", "OPENAI", "GROQ", "OPENROUTER", "LMSTUDIO", "OPENAI_COMPATIBLE",
     "OLLAMA", "GROQ_WHISPER", "OPENAI_WHISPER", "CUSTOM_WHISPER", "DEEPGRAM")
)


@pytest.fixture
def settings(isolated):  # noqa: F811 - imported pytest fixture
    config = isolated.config
    config._SELECTABLE_COMPUTE_DEVICE_LIST = copy.deepcopy([CPU, GPU])
    config._SELECTED_TRANSLATION_COMPUTE_DEVICE = copy.deepcopy(CPU)
    config._SELECTED_TRANSCRIPTION_COMPUTE_DEVICE = copy.deepcopy(CPU)
    return isolated


@pytest.fixture
def ipc(settings):
    ns = dict(config=settings.config, ConfigValidationError=settings.ns["ConfigValidationError"],
              ErrorCode=ErrorCode, VRCTError=VRCTError, functools=functools, printLog=Mock(),
              model=SimpleNamespace(updateOverlaySmallLogSettings=Mock(), updateOverlayLargeLogSettings=Mock()))
    path = SOURCE / "controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_configValidationErrorResponse"]
    exec(compile(tree, str(path), "exec"), ns)
    methods = {f"set{source}{suffix}" for source in ("Mic", "Speaker")
               for suffix in ("Threshold", "RecordTimeout", "PhraseTimeout", "MaxPhrases")}
    definitions("controller.py", ns, class_methods=methods | {
        "setMessageBoxRatio", "setOverlaySmallLogSettings", "setOverlayLargeLogSettings"})
    return SimpleNamespace(controller=ns["Controller"](), model=ns["model"])


@pytest.mark.parametrize("order", ["serialized", "type_first", "device_first"])
def test_gpu_compute_types_survive_save_load(settings, order):
    config = settings.config
    for source in ("TRANSLATION", "TRANSCRIPTION"):
        setattr(config, f"SELECTED_{source}_COMPUTE_DEVICE", GPU)
        setattr(config, f"SELECTED_{source}_COMPUTE_TYPE", "float16")
    config.saveConfigToFile()
    saved = strict_json(settings.path.read_text())
    if order != "serialized":
        first = "TYPE" if order == "type_first" else "DEVICE"
        saved = dict(sorted(saved.items(), key=lambda item: not item[0].endswith(f"COMPUTE_{first}")))
        settings.path.write_text(json.dumps(saved), encoding="utf-8")
    for source in ("TRANSLATION", "TRANSCRIPTION"):
        setattr(config, f"_SELECTED_{source}_COMPUTE_DEVICE", copy.deepcopy(CPU))
        setattr(config, f"_SELECTED_{source}_COMPUTE_TYPE", "auto")
    config.load_config()
    saved = strict_json(settings.path.read_text())
    for source in ("TRANSLATION", "TRANSCRIPTION"):
        assert getattr(config, f"SELECTED_{source}_COMPUTE_DEVICE") == GPU
        assert saved[f"SELECTED_{source}_COMPUTE_TYPE"] == "float16"
    config.on_save_failed.assert_not_called()


@pytest.mark.parametrize("source", ["TRANSLATION", "TRANSCRIPTION"])
@pytest.mark.parametrize("capabilities,expected_type", [
    (["float32", "float16", "auto", "bfloat16"], "float16"), (["auto", "float32"], "auto"),
])
def test_gpu_capability_changes_preserve_identity(settings, source, capabilities, expected_type):
    device_key, type_key = f"SELECTED_{source}_COMPUTE_DEVICE", f"SELECTED_{source}_COMPUTE_TYPE"
    current = dict(GPU, compute_types=capabilities)
    settings.config._SELECTABLE_COMPUTE_DEVICE_LIST = copy.deepcopy([CPU, current])
    settings.path.write_text(json.dumps({type_key: "float16", device_key: GPU}), encoding="utf-8")
    settings.config.load_config()
    assert getattr(settings.config, device_key) == current
    assert getattr(settings.config, type_key) == expected_type
    saved = strict_json(settings.path.read_text())
    assert saved[device_key] == current
    assert saved[type_key] == expected_type
    setattr(settings.config, device_key, GPU)
    assert getattr(settings.config, device_key) == current


@pytest.mark.parametrize("damage", ["name", "index", "kind", "missing", "bool_index"])
def test_gpu_identity_mismatch_falls_back_and_rejects_setter(settings, damage):
    invalid = copy.deepcopy(GPU)
    if damage == "missing":
        del invalid["device_index"]
    else:
        key, value = {"name": ("device_name", "Other RTX"), "index": ("device_index", 1),
                      "kind": ("device", "other"), "bool_index": ("device_index", False)}[damage]
        invalid[key] = value
    key = "SELECTED_TRANSCRIPTION_COMPUTE_DEVICE"
    settings.path.write_text(json.dumps({"SELECTED_TRANSCRIPTION_COMPUTE_TYPE": "float16", key: invalid}), encoding="utf-8")
    settings.config.load_config()
    assert getattr(settings.config, key) == CPU
    assert settings.config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE == "auto"
    with pytest.raises(settings.ns["ConfigValidationError"]):
        setattr(settings.config, key, invalid)


def test_runtime_compute_type_validation_uses_current_device(settings):
    settings.config._config_data = {"SELECTED_TRANSCRIPTION_COMPUTE_DEVICE": GPU}
    with pytest.raises(settings.ns["ConfigValidationError"]):
        settings.config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE = "float16"
    assert settings.config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE == "auto"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), json.loads("1e999")])
def test_all_float_descriptors_reject_nonfinite_before_saving(settings, value):
    config = settings.config
    config.saveConfig = Mock()
    keys = [key for key, descriptor in type(config).__dict__.items()
            if isinstance(descriptor, settings.ns["ManagedProperty"])
            and isinstance(descriptor.type_, tuple) and float in descriptor.type_]
    assert "MESSAGE_BOX_RATIO" in keys
    for key in keys:
        previous = getattr(config, key)
        with pytest.raises(settings.ns["ConfigValidationError"]):
            setattr(config, key, value)
        assert getattr(config, key) == previous
    config.saveConfig.assert_not_called()


@pytest.mark.parametrize("key", OVERLAYS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_overlay_nonfinite_numbers_rejected_before_saving(settings, key, value):
    config = settings.config
    previous = getattr(config, key)
    config.saveConfig = Mock()
    for field, original in previous.items():
        if isinstance(original, (int, float)):
            with pytest.raises(settings.ns["ConfigValidationError"]):
                setattr(config, key, dict(previous, **{field: value}))
            assert getattr(config, key) == previous
    config.saveConfig.assert_not_called()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_saved_numbers_repair_and_allow_later_saves(settings, value):
    config = settings.config
    keys = [key for key, descriptor in type(config).__dict__.items()
            if isinstance(descriptor, settings.ns["ManagedProperty"])
            and isinstance(descriptor.type_, tuple) and float in descriptor.type_]
    defaults = {key: getattr(config, key) for key in keys + list(OVERLAYS)}
    saved = {key: json.loads(value) for key in keys}
    saved.update({key: dict(defaults[key], x_pos=json.loads(value)) for key in OVERLAYS})
    settings.path.write_text(json.dumps(saved).replace("Infinity", "1e999") if value == "1e999"
                             else json.dumps(saved), encoding="utf-8")
    config.load_config()
    for key, expected in defaults.items():
        assert getattr(config, key) == expected
    config.UI_LANGUAGE = "ja"
    config._timer.fire()
    assert strict_json(settings.path.read_text())["UI_LANGUAGE"] == "ja"
    config.on_save_failed.assert_not_called()


def test_nonfinite_ipc_ratio_rejection_does_not_wedge_persistence(settings, ipc):
    previous = settings.config.MESSAGE_BOX_RATIO
    response = ipc.controller.setMessageBoxRatio(json.loads("1e999"))
    assert response["status"] == 400
    assert response["result"]["error_code"] == "VALIDATION_CONFIG_VALUE_INVALID"
    assert response["result"]["data"] == previous
    strict_json(json.dumps(response, allow_nan=False))
    settings.config.UI_LANGUAGE = "ja"
    settings.config._timer.fire()
    assert strict_json(settings.path.read_text())["UI_LANGUAGE"] == "ja"
    settings.config.on_save_failed.assert_not_called()


@pytest.mark.parametrize("size", ["Small", "Large"])
def test_nonfinite_overlay_ipc_returns_validation_error_without_applying(settings, ipc, size):
    key = f"OVERLAY_{size.upper()}_LOG_SETTINGS"
    previous = getattr(settings.config, key)
    settings.config.saveConfig = Mock()
    response = getattr(ipc.controller, f"setOverlay{size}LogSettings")(dict(previous, opacity=float("inf")))
    assert response["status"] == 400
    assert response["result"]["error_code"] == "VALIDATION_CONFIG_VALUE_INVALID"
    assert response["result"]["data"] == previous
    strict_json(json.dumps(response, allow_nan=False))
    assert getattr(settings.config, key) == previous
    getattr(ipc.model, f"updateOverlay{size}LogSettings").assert_not_called()
    settings.config.saveConfig.assert_not_called()


@pytest.mark.parametrize("key,upper", ASR_INTEGERS)
@pytest.mark.parametrize("value", [None, -1, True, 1.5, "3"])
def test_invalid_asr_scalars_repair_on_load_and_reject_setter(settings, key, upper, value):
    config = settings.config
    previous = getattr(config, key)
    settings.path.write_text(json.dumps({key: value}), encoding="utf-8")
    config.load_config()
    assert getattr(config, key) == previous
    assert strict_json(settings.path.read_text())[key] == previous
    config.saveConfig = Mock()
    with pytest.raises(settings.ns["ConfigValidationError"]):
        setattr(config, key, value)
    config.saveConfig.assert_not_called()


@pytest.mark.parametrize("key,upper", [row for row in ASR_INTEGERS if row[1] is not None])
def test_asr_upper_bounds_match_ui(settings, key, upper):
    previous = getattr(settings.config, key)
    settings.path.write_text(json.dumps({key: upper + 1}), encoding="utf-8")
    settings.config.load_config()
    assert getattr(settings.config, key) == previous
    with pytest.raises(settings.ns["ConfigValidationError"]):
        setattr(settings.config, key, upper + 1)
    if key.endswith("RECORD_TIMEOUT"):
        setattr(settings.config, key.replace("RECORD", "PHRASE"), upper)
    setattr(settings.config, key, upper)
    assert getattr(settings.config, key) == upper


@pytest.mark.parametrize("source", ["MIC", "SPEAKER"])
@pytest.mark.parametrize("record,phrase", [(0, 0), (1, 2), (10, 20), (30, 30)])
@pytest.mark.parametrize("reverse", [False, True])
def test_valid_timeout_pair_loads_in_any_order(settings, source, record, phrase, reverse):
    values = [(f"{source}_RECORD_TIMEOUT", record), (f"{source}_PHRASE_TIMEOUT", phrase)]
    settings.path.write_text(json.dumps(dict(reversed(values) if reverse else values)), encoding="utf-8")
    settings.config.load_config()
    for key, value in values:
        assert getattr(settings.config, key) == value


@pytest.mark.parametrize("source", ["MIC", "SPEAKER"])
@pytest.mark.parametrize("record,phrase", [(20, 10), (None, 0), (30, None)])
def test_invalid_timeout_pair_falls_back_consistently(settings, source, record, phrase):
    settings.path.write_text(json.dumps({f"{source}_RECORD_TIMEOUT": record,
                                        f"{source}_PHRASE_TIMEOUT": phrase}), encoding="utf-8")
    settings.config.load_config()
    assert getattr(settings.config, f"{source}_RECORD_TIMEOUT") == 3
    assert getattr(settings.config, f"{source}_PHRASE_TIMEOUT") == 3


@pytest.mark.parametrize("source", ["MIC", "SPEAKER"])
def test_runtime_timeout_pair_rejects_inconsistent_updates(settings, source):
    settings.config.saveConfig = Mock()
    for kind, value in (("RECORD", 4), ("PHRASE", 2)):
        key = f"{source}_{kind}_TIMEOUT"
        with pytest.raises(settings.ns["ConfigValidationError"]):
            setattr(settings.config, key, value)
        assert getattr(settings.config, key) == 3
    settings.config.saveConfig.assert_not_called()


@pytest.mark.parametrize("key,upper", [row for row in ASR_INTEGERS if not row[0].endswith("TIMEOUT")])
def test_asr_zero_values_remain_valid(settings, key, upper):
    setattr(settings.config, key, 0)
    assert getattr(settings.config, key) == 0


@pytest.mark.parametrize("source", ["Mic", "Speaker"])
@pytest.mark.parametrize("suffix,upper", [("Threshold", 2000), ("RecordTimeout", 30),
                                          ("PhraseTimeout", 30), ("MaxPhrases", 60)])
def test_asr_ipc_keeps_existing_validation_responses(settings, ipc, source, suffix, upper):
    snake = {"Threshold": "THRESHOLD", "RecordTimeout": "RECORD_TIMEOUT",
             "PhraseTimeout": "PHRASE_TIMEOUT", "MaxPhrases": "MAX_PHRASES"}[suffix]
    key = f"{source.upper()}_{snake}"
    previous = getattr(settings.config, key)
    settings.config.saveConfig = Mock()
    for value in (None, -1, upper + 1):
        response = getattr(ipc.controller, f"set{source}{suffix}")(value)
        assert response["status"] == 400
        assert response["result"]["error_code"] == f"VALIDATION_{key}"
        assert response["result"]["data"] == previous
    settings.config.saveConfig.assert_not_called()


def test_required_managed_properties_reject_null(settings):
    config = settings.config
    keys = [key for key, descriptor in type(config).__dict__.items()
            if isinstance(descriptor, settings.ns["ManagedProperty"])
            and not descriptor.readonly and descriptor.serialize and key not in NULLABLE]
    defaults = {key: getattr(config, key) for key in keys}
    settings.path.write_text(json.dumps(dict.fromkeys(keys)), encoding="utf-8")
    config.load_config()
    for key, previous in defaults.items():
        # Saved invalid custom URLs intentionally disable discovery.
        if key in settings.ns["CUSTOM_URL_KEYS"]:
            assert getattr(config, key) == ""
        elif key == "SELECTED_RELEASE_CHANNEL":
            assert getattr(config, key) == config._channelForVersion(config.VERSION)
        else:
            assert getattr(config, key) == previous
        with pytest.raises(settings.ns["ConfigValidationError"]):
            setattr(config, key, None)
    strict_json(settings.path.read_text())


def test_nullable_model_and_engine_selections_still_round_trip(settings):
    for key in NULLABLE:
        setattr(settings.config, key, None)
    settings.config.saveConfigToFile()
    settings.config.load_config()
    saved = strict_json(settings.path.read_text())
    for key in NULLABLE:
        assert getattr(settings.config, key) is None
        assert saved[key] is None
