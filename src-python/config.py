from models.network_policy import CUSTOM_URL_KEYS, valid_saved_api_url
from models.obs.settings import is_valid_numeric_setting
import sys
import copy
import errno
import math
import contextlib
import stat
import exclusive_tempfile
from os import path as os_path, makedirs as os_makedirs, replace as os_replace, fsync as os_fsync, remove as os_remove
from json import load as json_load
from json import dump as json_dump
from secrets import token_urlsafe as secrets_token_urlsafe
import threading
from os import environ
import os
from models.tts.settings import VoiceSettings, normalize_settings
from models.voice_conversion.settings import DirectSettings, normalize_settings as normalize_direct_settings
from models.transcription.realtime_settings import normalize_settings as normalize_realtime_settings
from models.speech_server.settings import normalize_settings as normalize_speech_server_settings
from typing import Optional, Dict, Any, Callable

# UI languages that 0.1.0 offered and 0.2.0 dropped. Translation to and from them is unchanged.
RETIRED_UI_LANGUAGES = frozenset(("ko", "zh-Hant", "zh-Hans"))

# Guard optional, potentially heavy or platform-specific imports so importing
# config.py doesn't raise in environments missing those packages.
try:
    from device_manager import device_manager
except Exception:  # pragma: no cover - optional runtime
    device_manager = None  # type: ignore

try:
    from models.translation.translation_languages import translation_lang, loadTranslationLanguages
except Exception:  # pragma: no cover - optional runtime
    translation_lang = {}  # type: ignore
    def loadTranslationLanguages(path: str, force: bool = False) -> Dict[str, Any]:
        return {}

try:
    from models.translation.translation_utils import ctranslate2_weights, DEFAULT_CTRANSLATE2_WEIGHT_TYPE
except Exception:  # pragma: no cover - optional runtime
    ctranslate2_weights = {}  # type: ignore
    DEFAULT_CTRANSLATE2_WEIGHT_TYPE = "m2m100_418M-ct2-int8"

try:
    from models.transcription.transcription_languages import transcription_lang
except Exception:  # pragma: no cover - optional runtime
    transcription_lang = {}  # type: ignore

try:
    from models.transcription.transcription_whisper import _MODELS as whisper_models
except Exception:  # pragma: no cover - optional runtime
    whisper_models = {}  # type: ignore

try:
    from models.ocr.ocr_languages import SELECTABLE_LANGUAGES as ocr_selectable_languages
except Exception:  # pragma: no cover - optional runtime
    ocr_selectable_languages = ()  # type: ignore

from utils import errorLogging, printLog, validateDictStructure, getComputeDeviceList, isValidPort, isValidWebSocketHost

# NOTE: MIC_VAD_FILTER/SPEAKER_VAD_FILTER/MIC_VAD_PARAMETERS/SPEAKER_VAD_PARAMETERS と
# 対応する migration ヘルパは ADR-0004 でストリーミング/VAD 独自実装を撤退した際に
# 削除された。フレーズ境界検出は speech_recognition.listen_in_background の
# energy_threshold + phrase_time_limit に完全委任している。


json_serializable_vars = {}
def json_serializable(var_name):
    def decorator(func):
        json_serializable_vars[var_name] = func
        return func
    return decorator

# Auto-register descriptors for serialization
def _auto_register_descriptors():
    """Automatically register ManagedProperty and ValidatedProperty descriptors
    for JSON serialization, reducing boilerplate _json_XXX methods.
    """
    for name, obj in Config.__dict__.items():
        if isinstance(obj, (ManagedProperty, ValidatedProperty)):
            # Only register if serialize=True and not already manually registered
            if obj.serialize and name not in json_serializable_vars:
                # Create closure to capture current name
                def make_serializer(attr_name):
                    @json_serializable(attr_name)
                    def _auto_serialize(self):
                        return getattr(self, attr_name)
                    return _auto_serialize
                make_serializer(name)


# Wrapper classes for mutable types that auto-save on modification
class ManagedDict(dict):
    """Dict wrapper that saves changes back to config."""
    def __init__(self, instance, property_name, immediate_save):
        self._instance = instance
        self._property_name = property_name
        self._immediate_save = immediate_save
        self._internal_name = f"_{property_name}"
        # Initialize from internal storage
        super().__init__(getattr(instance, self._internal_name))

    def _get_internal(self):
        """Get reference to internal storage."""
        return getattr(self._instance, self._internal_name)

    def _save(self):
        """Save current state back to config and sync internal storage."""
        try:
            # Update internal storage directly
            internal_dict = self._get_internal()
            internal_dict.clear()
            internal_dict.update(dict.items(self))
            # Trigger config save only if the corresponding property is serializable
            descriptor = getattr(type(self._instance), self._property_name, None)
            if getattr(descriptor, "serialize", True):
                self._instance.saveConfig(self._property_name, dict(self), immediate_save=self._immediate_save)
        except Exception:
            errorLogging()

    def __getitem__(self, key):
        # Always read from internal storage to get latest value
        return self._get_internal()[key]

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

    def __contains__(self, key):
        return key in self._get_internal()

    def get(self, key, default=None):
        return self._get_internal().get(key, default)

    def keys(self):
        return self._get_internal().keys()

    def values(self):
        return self._get_internal().values()

    def items(self):
        return self._get_internal().items()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._save()

    def pop(self, *args):
        result = super().pop(*args)
        self._save()
        return result

    def popitem(self):
        result = super().popitem()
        self._save()
        return result

    def clear(self):
        super().clear()
        self._save()

    def setdefault(self, key, default=None):
        result = super().setdefault(key, default)
        self._save()
        return result

    # dict のプレーンな `for k in d`/`len(d)`/`d == {...}`/`repr(d)` は
    # dict の C レベル内部ストレージを直接見るため、上のメソッド群と違い
    # `_get_internal()` を経由しない。プロパティを直接 (`config.X = {...}`)
    # 一括再代入した後、既にキャッシュ済みの wrapper がこの一括再代入前の
    # 内容のまま「見た目だけ」古くなる (実際の値は正しく保存されている)
    # のを防ぐため、ここも明示的に委譲する。
    def __iter__(self):
        return iter(self._get_internal())

    def __len__(self):
        return len(self._get_internal())

    def __eq__(self, other):
        return self._get_internal() == other

    def __ne__(self, other):
        return self._get_internal() != other

    def __repr__(self):
        return repr(self._get_internal())

    def __str__(self):
        return str(self._get_internal())

    __hash__ = None


class ManagedList(list):
    """List wrapper that saves changes back to config."""
    def __init__(self, instance, property_name, immediate_save):
        self._instance = instance
        self._property_name = property_name
        self._immediate_save = immediate_save
        self._internal_name = f"_{property_name}"
        # Initialize from internal storage
        super().__init__(getattr(instance, self._internal_name))

    def _get_internal(self):
        """Get reference to internal storage."""
        return getattr(self._instance, self._internal_name)

    def _save(self):
        """Save current state back to config and sync internal storage."""
        try:
            # Update internal storage directly
            internal_list = self._get_internal()
            internal_list.clear()
            internal_list.extend(list.__iter__(self))
            # Trigger config save only if the corresponding property is serializable
            descriptor = getattr(type(self._instance), self._property_name, None)
            if getattr(descriptor, "serialize", True):
                self._instance.saveConfig(self._property_name, list(self), immediate_save=self._immediate_save)
        except Exception:
            errorLogging()

    def __getitem__(self, index):
        # Always read from internal storage to get latest value
        return self._get_internal()[index]

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        self._save()

    def __delitem__(self, index):
        super().__delitem__(index)
        self._save()

    def __len__(self):
        return len(self._get_internal())

    def __contains__(self, value):
        return value in self._get_internal()

    def __iter__(self):
        return iter(self._get_internal())

    def append(self, value):
        super().append(value)
        self._save()

    def extend(self, iterable):
        super().extend(iterable)
        self._save()

    def insert(self, index, value):
        super().insert(index, value)
        self._save()

    # `list == [...]`/`repr(list)`/`str(list)` は list の C レベル内部
    # ストレージを直接見るため (__iter__/__len__/__getitem__ とは違い)
    # `_get_internal()` を経由しない。ManagedDict.__eq__ 等と同じ理由で
    # 明示的に委譲する。
    def __eq__(self, other):
        return self._get_internal() == other

    def __ne__(self, other):
        return self._get_internal() != other

    def __repr__(self):
        return repr(self._get_internal())

    def __str__(self):
        return str(self._get_internal())

    __hash__ = None

    def remove(self, value):
        super().remove(value)
        self._save()

    def pop(self, index=-1):
        result = super().pop(index)
        self._save()
        return result

    def clear(self):
        super().clear()
        self._save()

    def sort(self, *args, **kwargs):
        super().sort(*args, **kwargs)
        self._save()

    def reverse(self):
        super().reverse()
        self._save()


# VR UIのランチャーの初期値 (位置は手首の基準からの差。「ランチャーを初期に戻す」でもこの値に戻す)
DEFAULT_OVERLAY_VR_LAUNCHER_SETTINGS = {
    # 実機で手首に合わせて置いた位置・向き・大きさ (2026-10-14)
    "x_pos": 0.0641,
    "y_pos": -0.0416,
    "z_pos": -0.0063,
    "x_rotation": 9.3648,
    "y_rotation": -22.0338,
    "z_rotation": -17.1646,
    "display_duration": 5,
    "fadeout_duration": 0,  # 常に表示
    "opacity": 1.0,
    # 帯が 952px 幅だとしたときの横幅(m) (LAUNCHER_SAVED_WIDTH_PX)。実際の 880px の帯は 0.1834m になる。
    # 左端のマークがあった頃と同じ意味なので、保存済みの値は書き換えなくても同じ大きさで出る
    "ui_scaling": 0.1984,
    "tracker": "LeftHand",
}

class ConfigValidationError(Exception):
    """`ManagedProperty`/`ValidatedProperty` が値を拒否した際に送出する
    (フェーズ3項目24)。

    以前はディスクリプタが不正な値をサイレントに無視していたため、
    `/set/data/*` エンドポイントは「値が拒否されても200で成功を返す」
    という誤った契約になっていた。呼び出し元 (主に controller.py の
    `_configValidationErrorResponse` デコレータ) がこれを捕まえて
    `VRCTError` の適切なエラーレスポンスへ変換する。

    `ValidatedProperty` はバリデータが**全体を**拒否した場合 (`None` を
    返した場合) のみ送出する。多くのバリデータ (`HOTKEYS` や
    `SELECTED_TRANSLATION_ENGINES` 等) は「キー単位で不正な項目だけ
    旧値にフォールバックする」設計を意図的に持っており
    (`test_config_validated_property.py` で検証済み)、その場合は
    `None` を返さず正常終了するため、この例外は送出されない
    (=部分的なフォールバックは今まで通り黙って起こる、これは仕様)。
    """
    def __init__(self, attr_name: str, value):
        self.attr_name = attr_name
        self.value = value
        super().__init__(f"Invalid value for {attr_name}: {value!r}")


# Descriptor for simple managed config properties to reduce repetitive getters/setters.
# It performs optional type validation, optional allowed-values check, and calls
# instance.saveConfig(...) on successful set.
class ManagedProperty:
    def __init__(self, name: str, type_: type = None, allowed=None, immediate_save: bool = False, serialize: bool = True, readonly: bool = False, mutable_tracking: bool = False, allow_none: bool = False):
        self.name = name
        self.type_ = type_
        self.allowed = allowed
        self.immediate_save = immediate_save
        self.serialize = serialize
        self.readonly = readonly
        self.mutable_tracking = mutable_tracking
        self.allow_none = allow_none
        self.private_name = f"_{name}"
        self.wrapper_cache_name = f"_wrapper_{name}"

    def __get__(self, instance, owner):
        if instance is None:
            return self
        stored = getattr(instance, self.private_name)

        # If mutable_tracking is enabled, return cached wrapper or create new one
        if self.mutable_tracking and isinstance(stored, dict):
            wrapper = getattr(instance, self.wrapper_cache_name, None)
            if wrapper is None or not isinstance(wrapper, ManagedDict):
                wrapper = ManagedDict(instance, self.name, self.immediate_save)
                setattr(instance, self.wrapper_cache_name, wrapper)
            # Wrapper automatically syncs with internal storage on access
            return wrapper
        elif self.mutable_tracking and isinstance(stored, list):
            wrapper = getattr(instance, self.wrapper_cache_name, None)
            if wrapper is None or not isinstance(wrapper, ManagedList):
                wrapper = ManagedList(instance, self.name, self.immediate_save)
                setattr(instance, self.wrapper_cache_name, wrapper)
            # Wrapper automatically syncs with internal storage on access
            return wrapper

        # Return deep copy for mutable types to prevent external modification
        if isinstance(stored, (dict, list)):
            return copy.deepcopy(stored)
        return stored

    def __set__(self, instance, value):
        # Prevent modification of read-only properties
        if self.readonly:
            raise AttributeError(f"Cannot set read-only property '{self.name}'")

        if value is None and not self.allow_none:
            raise ConfigValidationError(self.name, value)

        # Nullable selections opt in; booleans are not numeric settings.
        if self.type_ is not None and value is not None and not isinstance(value, self.type_):
            raise ConfigValidationError(self.name, value)
        if isinstance(value, bool) and self.type_ in (int, float, (int, float)):
            raise ConfigValidationError(self.name, value)
        if isinstance(value, float) and not math.isfinite(value):
            raise ConfigValidationError(self.name, value)

        # Allowed-values check: can be an iterable or a callable
        if self.allowed is not None:
            if callable(self.allowed):
                try:
                    ok = self.allowed(value, instance)
                except Exception:
                    ok = False
                if not ok:
                    raise ConfigValidationError(self.name, value)
            else:
                if value not in self.allowed:
                    raise ConfigValidationError(self.name, value)

        # Deep copy mutable types to prevent external reference issues
        if isinstance(value, (dict, list)):
            value = copy.deepcopy(value)

        setattr(instance, self.private_name, value)

        # mutable_tracking の場合、既にキャッシュ済みの ManagedDict/ManagedList
        # wrapper があれば、その「自分自身の (list/dict 基底クラスの) 内部
        # ストレージ」は今回の一括再代入で更新されないまま残ってしまう。
        # __getitem__ 等 (_get_internal() 経由) は生き残った wrapper でも
        # 正しく新しい値を返すが、その後 wrapper 経由で1件でも変更
        # (`config.X[key] = value` 等) が起きると、wrapper._save() が
        # 「wrapper 自身の (古い) 基底ストレージ」を internal storage へ
        # 書き戻してしまい、今回の一括再代入の内容を丸ごと消してしまう
        # (単なる表示上の古さではなく実データの巻き戻り)。
        # 古い wrapper を破棄し、次回アクセス時に今回の新しい値から
        # 作り直させることでこれを防ぐ。
        if self.mutable_tracking:
            try:
                delattr(instance, self.wrapper_cache_name)
            except AttributeError:
                pass

        # Persist change
        try:
            # Keep the pending saved values available to dependent validators.
            if self.serialize and not getattr(instance, "_loading_saved_config", False):
                instance.saveConfig(self.name, value, immediate_save=self.immediate_save)
        except Exception:
            # Keep setter robust during import-time initialization
            pass

class ValidatedProperty:
    """Descriptor for complex validated properties.

    validator(value, instance) -> normalized_value | None
    If it returns None (or raises), `ConfigValidationError` is raised and the
    value is not stored (フェーズ3項目24; 以前はサイレントに無視していた)。
    """
    def __init__(self, name: str, validator, immediate_save: bool = False, serialize: bool = True):
        self.name = name
        self.validator = validator
        self.immediate_save = immediate_save
        self.serialize = serialize
        self.private_name = f"_{name}"

    def __get__(self, instance, owner):
        if instance is None:
            return self
        stored = getattr(instance, self.private_name)
        # Return a deep copy for mutable types, mirroring ManagedProperty.__get__.
        # Returning the raw reference let external code mutate config's internal
        # state directly via the common `d = config.X; d[k] = v; config.X = d`
        # idiom, before the setter (and its validator) ever ran. That silently
        # defeated validators whose "fall back to the previous value on an
        # invalid entry" logic reads `inst.X` as the "old" value: by the time
        # __set__ ran, `inst.X` and the incoming `value` were already the same
        # (already-mutated) object, so the fallback returned the new invalid
        # value instead of the real previous one.
        if isinstance(stored, (dict, list)):
            return copy.deepcopy(stored)
        return stored

    def __set__(self, instance, value):
        # NOTE(フェーズ3項目24): 送出するのはバリデータが値を「全体として」
        # 拒否した場合 (None を返した/例外を送出した場合) のみ。多くの
        # バリデータは「キー単位で不正な項目だけ旧値にフォールバックする」
        # 設計を意図的に持っており (test_config_validated_property.py
        # 参照)、その場合は non-None を返して正常終了するため送出されない
        # (=部分的なフォールバックはこれまで通り黙って起こる、仕様通り)。
        try:
            normalized = self.validator(value, instance)
        except Exception as e:
            raise ConfigValidationError(self.name, value) from e
        if normalized is None:
            raise ConfigValidationError(self.name, value)
        # Deep copy mutable types before storing, mirroring ManagedProperty.__set__,
        # so a caller that keeps a reference to the object it passed in (or that a
        # validator returned verbatim) can't mutate config's internal state later.
        if isinstance(normalized, (dict, list)):
            normalized = copy.deepcopy(normalized)
        setattr(instance, self.private_name, normalized)
        try:
            if self.serialize and not getattr(instance, "_loading_saved_config", False):
                instance.saveConfig(self.name, normalized, immediate_save=self.immediate_save)
        except Exception:
            pass


# ============================================================================
# Validator Functions for ValidatedProperty
# ============================================================================

# Smallest side of the OCR region (relative). Matches models/ocr/ocr_detection.py.
_OCR_REGION_MIN_SIDE = 0.02


def _ocr_capture_region_validator(val, inst):
    """{"x", "y", "width", "height"} in window-relative units, inside the window."""
    if not isinstance(val, dict) or set(val) != {"x", "y", "width", "height"}:
        return False
    if any(isinstance(val[k], bool) or not isinstance(val[k], (int, float)) for k in val):
        return False
    x, y, w, h = (float(val[k]) for k in ("x", "y", "width", "height"))
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        return False
    eps = 1e-6
    return (0.0 <= x and 0.0 <= y and w >= _OCR_REGION_MIN_SIDE - eps and h >= _OCR_REGION_MIN_SIDE - eps
            and x + w <= 1.0 + eps and y + h <= 1.0 + eps)


def _ocr_portal_restore_token_validator(val, inst):
    """Opaque text from the desktop: short, on one line. The portal decides whether it is still valid."""
    return len(val) <= 512 and not any(ord(char) < 32 or ord(char) == 127 for char in val)


def _main_window_geometry_validator(val, inst):
    if not (isinstance(val, dict) and set(val.keys()) == set(inst.MAIN_WINDOW_GEOMETRY.keys())):
        return None
    new = {}
    for key, value in val.items():
        if isinstance(value, int):
            new[key] = value
        else:
            new[key] = inst.MAIN_WINDOW_GEOMETRY[key]
    return new

def _selected_compute_type_validator(val, inst, device_attr):
    if not isinstance(val, str):
        return None
    device = getattr(inst, device_attr)
    if getattr(inst, "_loading_saved_config", False):
        # The saved type can precede its device in config.json. Resolve against
        # current capabilities without depending on the order of the setters.
        saved_device = inst._config_data.get(device_attr, device)
        device = _compute_device_validator(saved_device, inst) or device
    if val in device.get("compute_types", []):
        return val
    return None


def _selected_transcription_compute_type_validator(val, inst):
    return _selected_compute_type_validator(val, inst, 'SELECTED_TRANSCRIPTION_COMPUTE_DEVICE')


def _asr_timeout_allowed(value, inst, source, kind):
    if not 0 <= value <= 30:
        return False
    other_kind = 'PHRASE' if kind == 'RECORD' else 'RECORD'
    other_key = f'{source}_{other_kind}_TIMEOUT'
    other = getattr(inst, other_key)
    if getattr(inst, "_loading_saved_config", False):
        saved = inst._config_data.get(other_key, other)
        if type(saved) is int and 0 <= saved <= 30:
            other = saved
    return value <= other if kind == 'RECORD' else value >= other


def _overlay_small_validator(val, inst):
    if not (isinstance(val, dict) and set(val.keys()) == set(inst.OVERLAY_SMALL_LOG_SETTINGS.keys())):
        return None
    base = inst.OVERLAY_SMALL_LOG_SETTINGS
    new = dict(base)
    for key, v in val.items():
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if key == 'tracker' and isinstance(v, str) and v in ['HMD', 'LeftHand', 'RightHand']:
            new[key] = v
        elif key in ['x_pos','y_pos','z_pos','x_rotation','y_rotation','z_rotation'] and isinstance(v,(int,float)):
            new[key] = float(v)
        elif key in ['display_duration','fadeout_duration'] and isinstance(v,int):
            new[key] = v
        elif key in ['opacity','ui_scaling'] and isinstance(v,(int,float)):
            new[key] = float(v)
    return new

def _overlay_desktop_validator(val, inst):
    """The desktop caption overlay's look. A value out of range keeps the current one."""
    base = inst.OVERLAY_DESKTOP_SETTINGS
    if not (isinstance(val, dict) and set(val.keys()) == set(base.keys())):
        return None
    new = dict(base)
    for key, v in val.items():
        if isinstance(v, bool) or (isinstance(v, float) and not math.isfinite(v)):
            return None
        if key == 'position' and v in ('bottom', 'top'):
            new[key] = v
        elif key == 'font_size' and isinstance(v, int) and 16 <= v <= 72:
            new[key] = v
        elif key == 'display_duration' and isinstance(v, int) and 1 <= v <= 60:
            new[key] = v
        elif key == 'opacity' and isinstance(v, (int, float)) and 0.0 <= v <= 1.0:
            new[key] = float(v)
    return new

def _io_flow_overlay_validator(val, inst):
    """The flow overlay: the desktop strip on or off, and how many recent inputs it shows (1 to 3)."""
    base = inst.IO_FLOW_OVERLAY_SETTINGS
    if not (isinstance(val, dict) and set(val.keys()) == set(base.keys())):
        return None
    if type(val["desktop"]) is not bool or type(val["count"]) is not int or not 1 <= val["count"] <= 3:
        return None
    return {"desktop": val["desktop"], "count": val["count"]}

def _make_overlay_vr_window_validator(name):
    """VR UIのウィンドウ (ログ・ランチャー) の位置設定用。VR内で掴んで動かした結果だけが保存される。"""
    def validator(val, inst):
        return _validate_overlay_vr_window(val, getattr(inst, name))
    return validator

def _validate_overlay_vr_window(val, current):
    # 足りないキーは今の値で補う (項目を増やしても、以前に保存した位置を捨てないため)。知らないキーは受け付けない
    if not (isinstance(val, dict) and set(val.keys()) <= set(current.keys())):
        return None
    new = dict(current)
    for key, v in val.items():
        if isinstance(v, float) and not math.isfinite(v):
            return None
        # Playspace: SteamVRの空間に固定 (VR UIのウィンドウだけが選べる)
        if key == 'tracker' and isinstance(v, str) and v in ['HMD', 'LeftHand', 'RightHand', 'Playspace']:
            new[key] = v
        elif key in ['x_pos','y_pos','z_pos','x_rotation','y_rotation','z_rotation','opacity','ui_scaling'] and isinstance(v,(int,float)):
            new[key] = float(v)
        elif key in ['display_duration','fadeout_duration','width','height'] and isinstance(v,int) and not isinstance(v,bool):
            new[key] = v
    return new

def _overlay_large_validator(val, inst):
    if not (isinstance(val, dict) and set(val.keys()) == set(inst.OVERLAY_LARGE_LOG_SETTINGS.keys())):
        return None
    base = inst.OVERLAY_LARGE_LOG_SETTINGS
    new = dict(base)
    for key, v in val.items():
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if key == 'tracker' and isinstance(v, str) and v in ['HMD', 'LeftHand', 'RightHand']:
            new[key] = v
        elif key in ['x_pos','y_pos','z_pos','x_rotation','y_rotation','z_rotation'] and isinstance(v,(int,float)):
            new[key] = float(v)
        elif key in ['display_duration','fadeout_duration'] and isinstance(v,int):
            new[key] = v
        elif key in ['opacity','ui_scaling'] and isinstance(v,(int,float)):
            new[key] = float(v)
    return new

def _format_validator_send(val, inst):
    valid_parts = {
        "message": {"prefix": str, "suffix": str},
        "separator": str,
        "translation": {"prefix": str, "separator": str, "suffix": str},
        "translation_first": bool
    }
    if not isinstance(val, dict):
        return None
    return val if validateDictStructure(val, valid_parts) else None

def _format_validator_received(val, inst):
    valid_parts = {
        "message": {"prefix": str, "suffix": str},
        "separator": str,
        "translation": {"prefix": str, "separator": str, "suffix": str},
        "translation_first": bool
    }
    if not isinstance(val, dict):
        return None
    return val if validateDictStructure(val, valid_parts) else None

def _mic_word_filter_validator(val, inst):
    if not isinstance(val, list):
        return None
    seen = set()
    result = []
    for item in val:
        if isinstance(item, str) and item not in seen:
            seen.add(item)
            result.append(item)
    return result

def _selected_translation_engines_validator(val, inst):
    if not isinstance(val, dict):
        return None
    old = inst.SELECTED_TRANSLATION_ENGINES
    tabs = inst.SELECTABLE_TAB_NO_LIST
    loading = getattr(inst, "_loading_saved_config", False)
    if not loading and (set(val) != set(tabs) or
                        any(not isinstance(v, str) for v in val.values())):
        return None
    return {
        tab: val[tab] if isinstance(val.get(tab), str) and
        val[tab] in inst.SELECTABLE_TRANSLATION_ENGINE_LIST else old[tab]
        for tab in tabs
    }


def _selected_languages_validator(val, inst, attr_name, slots):
    if not isinstance(val, dict):
        return None
    old = getattr(inst, attr_name)
    tabs = inst.SELECTABLE_TAB_NO_LIST
    loading = getattr(inst, "_loading_saved_config", False)
    fields = {"language", "country", "enable"}
    # Runtime writes replace a complete map. Reject missing/unknown structure
    # before storing anything; startup repairs damaged parts from the defaults.
    if not loading:
        if set(val) != set(tabs):
            return None
        for tab in tabs:
            if not isinstance(val[tab], dict) or set(val[tab]) != set(slots):
                return None
            if any(not isinstance(entry, dict) or set(entry) != fields
                   for entry in val[tab].values()):
                return None
    new = copy.deepcopy(old)
    for tab in tabs:
        entries = val.get(tab)
        if not isinstance(entries, dict):
            continue
        for slot in slots:
            entry = entries.get(slot)
            if not isinstance(entry, dict) or set(entry) != fields:
                continue
            language, country, enable = entry["language"], entry["country"], entry["enable"]
            if (isinstance(language, str) and isinstance(country, str) and
                    language in transcription_lang and
                    country in transcription_lang[language] and isinstance(enable, bool)):
                new[tab][slot] = dict(entry)
    return new


def _selected_your_languages_validator(val, inst):
    return _selected_languages_validator(val, inst, "SELECTED_YOUR_LANGUAGES", ("1",))


def _selected_target_languages_validator(val, inst):
    return _selected_languages_validator(
        val, inst, "SELECTED_TARGET_LANGUAGES", inst.SELECTED_TAB_TARGET_LANGUAGES_NO_LIST
    )


def _selected_translation_compute_type_validator(val, inst):
    return _selected_compute_type_validator(val, inst, 'SELECTED_TRANSLATION_COMPUTE_DEVICE')

def _keepSavedDeviceUntilListed(inst) -> bool:
    """config.json を読む時点では、デバイスの一覧がまだ取れていない。

    device_manager は起動時に OS の音声 API を触らず、一覧は監視スレッドの最初の
    更新で埋まる。それまでの一覧は `NoHost`/`NoDevice` だけなので、保存した選択を
    ここで検証すると毎回拒否され、手動で選んだマイクやスピーカーが起動のたびに
    既定のデバイスへ戻っていた。読み込みの間に一覧が空なら保存値をそのまま受け取り、
    一覧が取れたあと controller の `_synchronize*SelectionAfterDeviceUpdate()` が
    存在を確かめる (無ければ既定へ戻す)。
    """
    if not getattr(inst, "_loading_saved_config", False):
        return False
    try:
        return list(device_manager.getMicDevices().keys()) == ["NoHost"] \
            and [d.get("name") for d in device_manager.getSpeakerDevices()] == ["NoDevice"]
    except Exception:
        return False

def _mic_host_validator(val, inst):
    if device_manager is None:
        return None
    if not isinstance(val, str):
        return None
    # デバイスが一時的に存在しない状態を表す永続化用 sentinel。
    # 実デバイス一覧に含まれない場合でも、抜去後の選択状態を安全に
    # `NoHost` へ戻せる必要がある。
    if val == "NoHost":
        return val
    hosts = list(device_manager.getMicDevices().keys())
    if val in hosts or _keepSavedDeviceUntilListed(inst):
        return val
    return None

def _mic_device_validator(val, inst):
    if device_manager is None:
        return None
    if not isinstance(val, str):
        return None
    # `NoDevice` は「選択中のデバイスなし」を表す sentinel。実デバイス
    # が残っている一覧にも安全に設定できるよう、一覧検証より先に許可する。
    if val == "NoDevice":
        return val
    try:
        devices = device_manager.getMicDevices().get(inst.SELECTED_MIC_HOST, [])
        names = [d.get('name') for d in devices]
        if val in names or _keepSavedDeviceUntilListed(inst):
            return val
        return None
    except Exception:
        return None

def _speaker_device_validator(val, inst):
    if device_manager is None:
        return None
    if not isinstance(val, str):
        return None
    if val == "NoDevice":
        return val
    try:
        names = [d.get('name') for d in device_manager.getSpeakerDevices()]
        if val in names or _keepSavedDeviceUntilListed(inst):
            return val
        return None
    except Exception:
        return None

def _compute_device_validator(val, inst):
    if not isinstance(val, dict):
        return None
    for dev in inst.SELECTABLE_COMPUTE_DEVICE_LIST:
        if all(key in val and type(val[key]) is type(dev[key]) and val[key] == dev[key]
               for key in ('device', 'device_index', 'device_name')):
            return copy.deepcopy(dev)
    return None

def _allowed_in_populated(list_attr_name: str):
    def _inner(value, inst):
        try:
            lst = getattr(inst, list_attr_name)
        except Exception:
            return True  # インスタンス状態取得失敗時も弾かない
        if not lst:  # 空/未初期化
            return True
        if value is None:
            return True
        return value in lst
    return _inner


class Config:
    """Application configuration singleton.

    Responsibilities:
    - expose read-only and read-write configuration via properties
    - persist selected values to JSON with debounce
    Initialization must finish before the singleton is published. Load failures
    keep the original settings file and block persistence until a successful load.
    """

    _instance = None
    _config_data: Dict[str, Any] = {}
    _timer: Optional[threading.Timer] = None
    _debounce_time: int = 2
    _file_lock: threading.Lock = threading.Lock()
    # Shared by translation and transcription credential commits. Provider
    # requests must finish before taking this lock.
    credential_lock = threading.RLock()

    # In-memory privacy boundary, independent of saved config and IPC. Track
    # committed values (after descriptor validation), including A -> B -> A
    # changes with no intervening messages. Inactive destination edits also
    # invalidate history conservatively. Never retain credentials in history.
    translation_history_lock = threading.RLock()
    translation_history_generation = 0
    _TRANSLATION_HISTORY_SETTINGS = frozenset({
        "_ENABLE_TRANSLATION", "_SELECTED_TAB_NO", "_SELECTED_TRANSLATION_ENGINES",
        "_CTRANSLATE2_WEIGHT_TYPE", "_AUTH_KEYS",
        "_LMSTUDIO_URL", "_OPENAI_COMPATIBLE_URL",
        "_SELECTED_PLAMO_MODEL", "_SELECTED_GEMINI_MODEL", "_SELECTED_OPENAI_MODEL",
        "_SELECTED_GROQ_MODEL", "_SELECTED_OPENROUTER_MODEL", "_SELECTED_LMSTUDIO_MODEL",
        "_SELECTED_OPENAI_COMPATIBLE_MODEL", "_SELECTED_OLLAMA_MODEL",
    })

    def __setattr__(self, name, value):
        if name in self._TRANSLATION_HISTORY_SETTINGS:
            with self.translation_history_lock:
                if getattr(self, name, None) != value:
                    self.translation_history_generation += 1
                object.__setattr__(self, name, value)
        else:
            object.__setattr__(self, name, value)

    def updateCredential(self, map_name: str, engine_key: str, value: Optional[str]) -> None:
        """Merge one credential without overwriting another provider's update.

        Callers may hold credential_lock to publish prepared client/model state
        in the same commit. This does not change the persistence policy.
        """
        if map_name not in ("AUTH_KEYS", "TRANSCRIPTION_AUTH_KEYS"):
            raise ValueError("Unknown credential map")
        if value is not None and not isinstance(value, str):
            raise ValueError("Invalid credential value")
        with self.credential_lock:
            keys = getattr(self, map_name)
            if engine_key not in keys:
                raise ValueError("Unknown credential provider")
            keys[engine_key] = value
            setattr(self, map_name, keys)

    # 保存の失敗を知らせる先。controller が起動時に設定する。
    # on_save_failed(reason, path) と on_save_recovered() を呼ぶ
    on_save_failed: Optional[Callable[[str, str], None]] = None
    on_save_recovered: Optional[Callable[[], None]] = None
    _save_failed: bool = False
    _save_failure_reason: Optional[str] = None
    _save_retry_timer: Optional[threading.Timer] = None
    _save_retry_sec: int = 30

    # Fork packages are updated by their distribution channel. Re-enable only
    # after verifying fork installers; never replace an AUR-managed install.
    BUILTIN_UPDATER_ENABLED = False

    # VERSION に含まれていれば beta チャンネル扱いとする接尾辞。NSIS
    # インストーラの .onInit (template.nsi) が ${VERSION} に対して行って
    # いる "-beta"/"-rc" 判定と同じルール。load_config() が起動のたびに
    # SELECTED_RELEASE_CHANNEL をこの基準へ再同期する際に使う。
    _RELEASE_CHANNEL_BETA_MARKERS = ("-beta", "-rc")

    @staticmethod
    def _channelForVersion(version: str) -> str:
        """バージョン文字列(例: "3.5.1-beta.1")からリリースチャンネルを
        機械的に判定する。NSISインストーラの.onInit(template.nsi)が
        ${VERSION}に対して行う判定と同じルール。"""
        return (
            "beta" if any(marker in version for marker in Config._RELEASE_CHANNEL_BETA_MARKERS)
            else "stable"
        )

    # Groq/OpenAI 公式の音声書き起こしAPIのエンドポイントは固定 (ユーザー
    # 編集不可)。カスタムサーバーのみ TRANSCRIPTION_CUSTOM_URL で
    # ユーザーが指定する (issue #100 のローカル/LANサーバー向け)。
    GROQ_WHISPER_BASE_URL = "https://api.groq.com/openai/v1"
    OPENAI_WHISPER_BASE_URL = "https://api.openai.com/v1"

    def setupDownloadUrl(self, target_version: Optional[str] = None, tag: Optional[str] = None) -> str:
        """Reserved fork installer URL; built-in updates are disabled."""
        revision = tag or (f"v{target_version}" if target_version else None)
        base = "https://github.com/kein5/VRCT-VOX/releases"
        route = f"download/{revision}" if revision else "latest/download"
        return f"{base}/{route}/VRCT-VOX_setup.exe"

    def __new__(cls):
        if cls._instance is None:
            instance = super(Config, cls).__new__(cls)
            try:
                instance.init_config()
            except Exception:
                errorLogging()
                raise
            instance.load_config()
            cls._instance = instance
        return cls._instance

    def setSelectedLanguages(self, your, target) -> None:
        """Validate both maps before committing the pair or scheduling a save.

        The controller holds its settings lock; the file lock also prevents a
        persistence snapshot from observing only half of the swap.
        """
        with self._file_lock:
            normalized = []
            for name, value in (("SELECTED_YOUR_LANGUAGES", your),
                                ("SELECTED_TARGET_LANGUAGES", target)):
                candidate = getattr(type(self), name).validator(value, self)
                if candidate is None:
                    raise ConfigValidationError(name, value)
                normalized.append(copy.deepcopy(candidate))
            self._SELECTED_YOUR_LANGUAGES, self._SELECTED_TARGET_LANGUAGES = normalized
        self.saveConfig("SELECTED_YOUR_LANGUAGES", normalized[0])

    @contextlib.contextmanager
    def _configFileLock(self):
        # Keep this inode in place: unlinking a lock file can split its owners.
        fd = os.open(f"{self.PATH_CONFIG}.lock",
                     os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(errno.EINVAL, "Config lock is not a regular file")
            if os.name == "nt":
                import msvcrt
                # Byte-range locks may extend past EOF; do not alter the file.
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def saveConfigToFile(self, *, _retry_timer=None) -> None:
        # A persisted snapshot must not split a URL/key commit.
        with self.credential_lock, self._file_lock:
            if _retry_timer is not None:
                # A cancelled callback can already be waiting for this lock.
                if self._save_retry_timer is not _retry_timer:
                    return
                self._save_retry_timer = None
            if not self._initialized or not self._config_loaded:
                return
            # Snapshot and write share one serialization boundary. An older
            # debounced callback must never overwrite a newer immediate save.
            tmp_path = None
            try:
                with self._configFileLock():
                    # A failed getter invalidates the entire snapshot.
                    filtered = {name: getter(self) for name, getter in json_serializable_vars.items()}
                    self._config_data = filtered
                    # Exclusive creation prevents temp collisions and symlink
                    # traversal; mkstemp also restricts POSIX permissions to 0600.
                    fd, tmp_path = exclusive_tempfile.mkstemp(
                        prefix=os_path.basename(self.PATH_CONFIG) + ".", suffix=".tmp",
                        dir=os_path.dirname(self.PATH_CONFIG))
                    try:
                        fp = os.fdopen(fd, "w", encoding="utf-8")
                    except Exception:
                        os.close(fd)
                        raise
                    with fp:
                        json_dump(filtered, fp, indent=4, ensure_ascii=False, allow_nan=False)
                        fp.flush()
                        os_fsync(fp.fileno())
                    os_replace(tmp_path, self.PATH_CONFIG)
                    tmp_path = None
            except Exception as e:
                self._saveFailedLocked(e)
                return
            finally:
                if tmp_path is not None:
                    try:
                        os_remove(tmp_path)
                    except OSError:
                        pass
            recovered = self._save_failed
            self._save_failed = False
            if isinstance(self._save_retry_timer, threading.Timer):
                self._save_retry_timer.cancel()
                self._save_retry_timer = None
        if recovered and self.on_save_recovered is not None:
            self.on_save_recovered()

    @staticmethod
    def _saveFailureReason(error: Exception) -> str:
        if getattr(error, "errno", None) == errno.ENOSPC:
            return "disk_full"
        if getattr(error, "errno", None) in (errno.EACCES, errno.EPERM):
            return "permission_denied"
        if getattr(error, "errno", None) == errno.EROFS:
            return "read_only"
        return "write_failed"

    def _saveFailedLocked(self, error: Exception, *, retry: bool = True) -> None:
        """書き込みに失敗した。値はメモリーに残っているので、知らせて、あとで書き直す。

        以前は例外を setter が捨て、変更は保存されないまま成功を返していた (再起動で消える)。
        容量を空けるなどして直れば次の書き直しで保存でき、そのときも知らせる。
        """
        errorLogging()
        first = not self._save_failed
        self._save_failed = True
        if retry and self._save_retry_timer is None:
            timer = threading.Timer(
                self._save_retry_sec, lambda: self.saveConfigToFile(_retry_timer=timer)
            )
            self._save_retry_timer = timer
            timer.daemon = True
            timer.start()
        self._save_failure_reason = self._saveFailureReason(error) if retry else "load_failed"
        # 失敗が続く間は、最初の1回だけ知らせる
        if first and self.on_save_failed is not None:
            threading.Thread(target=self.on_save_failed, args=(self._save_failure_reason, self.PATH_CONFIG),
                             daemon=True).start()

    def setSaveCallbacks(self, on_failed: Callable[[str, str], None], on_recovered: Callable[[], None]) -> None:
        """保存の失敗と回復を知らせる先を設定する。設定する前の失敗も、ここで知らせる。"""
        with self._file_lock:
            self.on_save_failed, self.on_save_recovered = on_failed, on_recovered
            pending = self._save_failure_reason if self._save_failed else None
        if pending is not None:
            on_failed(pending, self.PATH_CONFIG)

    def saveConfig(self, key: str, value: Any, immediate_save: bool = False) -> None:
        # 実際に永続化される値は saveConfigToFile() が毎回
        # json_serializable_vars から丸ごと再構成するため、ここで
        # self._config_data を直接書き換えても次の保存で必ず上書き
        # される (以前あった self._config_data[key] = value は
        # 何も読まれない dead code だったため削除)。
        with self._file_lock:
            if not self._initialized or not self._config_loaded:
                return
            if isinstance(self._timer, threading.Timer) and self._timer.is_alive():
                self._timer.cancel()

            if immediate_save:
                pass
            else:
                self._timer = threading.Timer(self._debounce_time, self.saveConfigToFile)
                self._timer.daemon = True
                self._timer.start()

        if immediate_save:
            self.saveConfigToFile()

    # Read Only
    VERSION = ManagedProperty('VERSION', readonly=True, serialize=False)
    PATH_LOCAL = ManagedProperty('PATH_LOCAL', readonly=True, serialize=False)
    PATH_DATA = ManagedProperty('PATH_DATA', readonly=True, serialize=False)
    PATH_CONFIG = ManagedProperty('PATH_CONFIG', readonly=True, serialize=False)
    PATH_LOGS = ManagedProperty('PATH_LOGS', readonly=True, serialize=False)
    GITHUB_URL = ManagedProperty('GITHUB_URL', readonly=True, serialize=False)
    GITHUB_RELEASES_LIST_URL = ManagedProperty('GITHUB_RELEASES_LIST_URL', readonly=True, serialize=False)
    MIN_SUPPORTED_VERSION = ManagedProperty('MIN_SUPPORTED_VERSION', readonly=True, serialize=False)
    SELECTABLE_RELEASE_CHANNEL_LIST = ManagedProperty('SELECTABLE_RELEASE_CHANNEL_LIST', readonly=True, serialize=False)
    MAX_MIC_THRESHOLD = ManagedProperty('MAX_MIC_THRESHOLD', readonly=True, serialize=False)
    MAX_SPEAKER_THRESHOLD = ManagedProperty('MAX_SPEAKER_THRESHOLD', readonly=True, serialize=False)
    WATCHDOG_TIMEOUT = ManagedProperty('WATCHDOG_TIMEOUT', readonly=True, serialize=False)
    WATCHDOG_INTERVAL = ManagedProperty('WATCHDOG_INTERVAL', readonly=True, serialize=False)
    SELECTABLE_TAB_NO_LIST = ManagedProperty('SELECTABLE_TAB_NO_LIST', readonly=True, serialize=False)
    SELECTED_TAB_TARGET_LANGUAGES_NO_LIST = ManagedProperty('SELECTED_TAB_TARGET_LANGUAGES_NO_LIST', readonly=True, serialize=False)
    SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_LIST = ManagedProperty('SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_LIST', readonly=True, serialize=False)
    SELECTABLE_WHISPER_WEIGHT_TYPE_LIST = ManagedProperty('SELECTABLE_WHISPER_WEIGHT_TYPE_LIST', readonly=True, serialize=False)
    SELECTABLE_TRANSLATION_ENGINE_LIST = ManagedProperty('SELECTABLE_TRANSLATION_ENGINE_LIST', readonly=True, serialize=False)
    SELECTABLE_TRANSCRIPTION_ENGINE_LIST = ManagedProperty('SELECTABLE_TRANSCRIPTION_ENGINE_LIST', readonly=True, serialize=False)
    SELECTABLE_UI_LANGUAGE_LIST = ManagedProperty('SELECTABLE_UI_LANGUAGE_LIST', readonly=True, serialize=False)
    SELECTABLE_OCR_SOURCE_LANGUAGE_LIST = ManagedProperty('SELECTABLE_OCR_SOURCE_LANGUAGE_LIST', readonly=True, serialize=False)
    COMPUTE_MODE = ManagedProperty('COMPUTE_MODE', readonly=True, serialize=False)
    SELECTABLE_COMPUTE_DEVICE_LIST = ManagedProperty('SELECTABLE_COMPUTE_DEVICE_LIST', readonly=True, serialize=False)
    SEND_MESSAGE_BUTTON_TYPE_LIST = ManagedProperty('SEND_MESSAGE_BUTTON_TYPE_LIST', readonly=True, serialize=False)

    # Read Write
    # --- Simple boolean flags (managed by descriptor) ---
    ENABLE_TRANSLATION = ManagedProperty('ENABLE_TRANSLATION', type_=bool, serialize=False)
    ENABLE_TRANSCRIPTION_SEND = ManagedProperty('ENABLE_TRANSCRIPTION_SEND', type_=bool, serialize=False)
    ENABLE_TRANSCRIPTION_RECEIVE = ManagedProperty('ENABLE_TRANSCRIPTION_RECEIVE', type_=bool, serialize=False)
    ENABLE_OCR_CAPTURE = ManagedProperty('ENABLE_OCR_CAPTURE', type_=bool, serialize=False)
    # Saved: the window opens on top again after a restart (the UI applies it).
    ENABLE_FOREGROUND = ManagedProperty('ENABLE_FOREGROUND', type_=bool)
    ENABLE_CHECK_ENERGY_SEND = ManagedProperty('ENABLE_CHECK_ENERGY_SEND', type_=bool, serialize=False)
    ENABLE_CHECK_ENERGY_RECEIVE = ManagedProperty('ENABLE_CHECK_ENERGY_RECEIVE', type_=bool, serialize=False)

    # --- Selectable dict/list properties (managed by descriptor, not serialized) ---
    # These are dynamically generated in init_config() based on installed packages/APIs
    SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT = ManagedProperty('SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT', type_=dict, serialize=False, mutable_tracking=True)
    SELECTABLE_WHISPER_WEIGHT_TYPE_DICT = ManagedProperty('SELECTABLE_WHISPER_WEIGHT_TYPE_DICT', type_=dict, serialize=False, mutable_tracking=True)
    SELECTABLE_TRANSLATION_ENGINE_STATUS = ManagedProperty('SELECTABLE_TRANSLATION_ENGINE_STATUS', type_=dict, serialize=False, mutable_tracking=True)
    SELECTABLE_TRANSCRIPTION_ENGINE_STATUS = ManagedProperty('SELECTABLE_TRANSCRIPTION_ENGINE_STATUS', type_=dict, serialize=False, mutable_tracking=True)
    SELECTABLE_PLAMO_MODEL_LIST = ManagedProperty('SELECTABLE_PLAMO_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_GEMINI_MODEL_LIST = ManagedProperty('SELECTABLE_GEMINI_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_OPENAI_MODEL_LIST = ManagedProperty('SELECTABLE_OPENAI_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_GROQ_MODEL_LIST = ManagedProperty('SELECTABLE_GROQ_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_OPENROUTER_MODEL_LIST = ManagedProperty('SELECTABLE_OPENROUTER_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_LMSTUDIO_MODEL_LIST = ManagedProperty('SELECTABLE_LMSTUDIO_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST = ManagedProperty('SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_OLLAMA_MODEL_LIST = ManagedProperty('SELECTABLE_OLLAMA_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_GROQ_WHISPER_MODEL_LIST = ManagedProperty('SELECTABLE_GROQ_WHISPER_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_OPENAI_WHISPER_MODEL_LIST = ManagedProperty('SELECTABLE_OPENAI_WHISPER_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_CUSTOM_WHISPER_MODEL_LIST = ManagedProperty('SELECTABLE_CUSTOM_WHISPER_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    SELECTABLE_DEEPGRAM_MODEL_LIST = ManagedProperty('SELECTABLE_DEEPGRAM_MODEL_LIST', type_=list, serialize=False, mutable_tracking=True)
    # モデル名 -> 対応言語コード一覧 ({"nova-3": ["en", "ja", ...], ...})。
    # DeepgramProvider は常に detect_language=true で呼ぶため文字起こし
    # 処理自体はこの値を参照しないが、UI側で「選択したモデルがどの言語に
    # 対応しているか」を表示できるようにするためのメタデータ。
    DEEPGRAM_MODEL_LANGUAGES = ManagedProperty('DEEPGRAM_MODEL_LANGUAGES', type_=dict, serialize=False, mutable_tracking=True)

    # --- Save Json Data (ManagedProperty-based) ---
    # More simple boolean flags replaced with ManagedProperty
    CONVERT_MESSAGE_TO_ROMAJI = ManagedProperty('CONVERT_MESSAGE_TO_ROMAJI', type_=bool)
    CONVERT_MESSAGE_TO_HIRAGANA = ManagedProperty('CONVERT_MESSAGE_TO_HIRAGANA', type_=bool)
    MAIN_WINDOW_SIDEBAR_COMPACT_MODE = ManagedProperty('MAIN_WINDOW_SIDEBAR_COMPACT_MODE', type_=bool)

    ## Config Window
    TRANSPARENCY = ManagedProperty('TRANSPARENCY', type_=int)
    UI_SCALING = ManagedProperty('UI_SCALING', type_=int)
    TEXTBOX_UI_SCALING = ManagedProperty('TEXTBOX_UI_SCALING', type_=int)
    MESSAGE_BOX_RATIO = ManagedProperty('MESSAGE_BOX_RATIO', type_=(int, float), immediate_save=True)
    SEND_MESSAGE_BUTTON_TYPE = ManagedProperty('SEND_MESSAGE_BUTTON_TYPE', type_=str, allowed=lambda v, inst: v in inst.SEND_MESSAGE_BUTTON_TYPE_LIST)
    SHOW_RESEND_BUTTON = ManagedProperty('SHOW_RESEND_BUTTON', type_=bool)
    FONT_FAMILY = ManagedProperty('FONT_FAMILY', type_=str)
    UI_LANGUAGE = ManagedProperty('UI_LANGUAGE', type_=str, allowed=lambda v, inst: v in inst.SELECTABLE_UI_LANGUAGE_LIST)
    MAIN_WINDOW_GEOMETRY = ValidatedProperty('MAIN_WINDOW_GEOMETRY', _main_window_geometry_validator, immediate_save=True)

    # --- Mic-related simple properties ---
    MIC_THRESHOLD = ManagedProperty('MIC_THRESHOLD', type_=int, allowed=lambda v, inst: 0 <= v <= inst.MAX_MIC_THRESHOLD)
    MIC_AUTOMATIC_THRESHOLD = ManagedProperty('MIC_AUTOMATIC_THRESHOLD', type_=bool)
    MIC_RECORD_TIMEOUT = ManagedProperty('MIC_RECORD_TIMEOUT', type_=int, allowed=lambda v, inst: _asr_timeout_allowed(v, inst, 'MIC', 'RECORD'))
    MIC_PHRASE_TIMEOUT = ManagedProperty('MIC_PHRASE_TIMEOUT', type_=int, allowed=lambda v, inst: _asr_timeout_allowed(v, inst, 'MIC', 'PHRASE'))
    MIC_MAX_PHRASES = ManagedProperty('MIC_MAX_PHRASES', type_=int, allowed=lambda v, inst: 0 <= v <= 30)
    MIC_AVG_LOGPROB = ManagedProperty('MIC_AVG_LOGPROB', type_=(int, float), allowed=lambda v, inst: not isinstance(v, bool) and math.isfinite(v) and -2 <= v <= 0)
    MIC_NO_SPEECH_PROB = ManagedProperty('MIC_NO_SPEECH_PROB', type_=(int, float), allowed=lambda v, inst: not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1)
    MIC_NO_REPEAT_NGRAM_SIZE = ManagedProperty('MIC_NO_REPEAT_NGRAM_SIZE', type_=int, allowed=lambda v, inst: v >= 0)
    HOTKEYS = ValidatedProperty('HOTKEYS',
        validator=lambda val, inst: (
            {**inst.HOTKEYS, **{k: (v if (isinstance(v, list) or v is None) else inst.HOTKEYS.get(k))
            for k, v in val.items()}} if isinstance(val, dict) and set(val.keys()) <= set(inst.HOTKEYS.keys()) else None
        ),
        immediate_save=True
    )

    # --- Speaker-related simple properties ---
    SPEAKER_THRESHOLD = ManagedProperty('SPEAKER_THRESHOLD', type_=int, allowed=lambda v, inst: 0 <= v <= inst.MAX_SPEAKER_THRESHOLD)
    SPEAKER_AUTOMATIC_THRESHOLD = ManagedProperty('SPEAKER_AUTOMATIC_THRESHOLD', type_=bool)
    SPEAKER_RECORD_TIMEOUT = ManagedProperty('SPEAKER_RECORD_TIMEOUT', type_=int, allowed=lambda v, inst: _asr_timeout_allowed(v, inst, 'SPEAKER', 'RECORD'))
    SPEAKER_PHRASE_TIMEOUT = ManagedProperty('SPEAKER_PHRASE_TIMEOUT', type_=int, allowed=lambda v, inst: _asr_timeout_allowed(v, inst, 'SPEAKER', 'PHRASE'))
    SPEAKER_MAX_PHRASES = ManagedProperty('SPEAKER_MAX_PHRASES', type_=int, allowed=lambda v, inst: 0 <= v <= 60)
    SPEAKER_AVG_LOGPROB = ManagedProperty('SPEAKER_AVG_LOGPROB', type_=(int, float), allowed=lambda v, inst: not isinstance(v, bool) and math.isfinite(v) and -2 <= v <= 0)
    SPEAKER_NO_SPEECH_PROB = ManagedProperty('SPEAKER_NO_SPEECH_PROB', type_=(int, float), allowed=lambda v, inst: not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1)
    SPEAKER_NO_REPEAT_NGRAM_SIZE = ManagedProperty('SPEAKER_NO_REPEAT_NGRAM_SIZE', type_=int, allowed=lambda v, inst: v >= 0)

    # -- VAD (Silero) によるマイク/スピーカーの発話区間検出 ---
    # 既定は False (従来通りのエネルギー閾値方式)。過去に2度、この領域
    # (WASAPI/PyAudio) で挑戦して未完了/リバートに終わっている経緯が
    # あるため、オプトインとして導入する (フェーズ3、2026-09-06)。
    # マイク/スピーカーは音声特性(ノイズ、話者数、無音区間の傾向)が
    # 異なるため、他の MIC_*/SPEAKER_* 設定と同様に個別に切り替え可能と
    # する (2026-09-07、単一の ENABLE_VAD から分割)。
    MIC_ENABLE_VAD = ManagedProperty('MIC_ENABLE_VAD', type_=bool)
    SPEAKER_ENABLE_VAD = ManagedProperty('SPEAKER_ENABLE_VAD', type_=bool)

    # --- Auth and API settings ---
    # 旧 config.json との後方互換のため、不足キーは既定値（None）で補完し、余剰キーは無視する。
    AUTH_KEYS = ValidatedProperty('AUTH_KEYS',
        validator=lambda val, inst: (
            {
                k: (val[k] if (k in val and isinstance(val[k], (str, type(None)))) else inst.AUTH_KEYS.get(k))
                for k in inst.AUTH_KEYS.keys()
            }
            if isinstance(val, dict) else None
        )
    )
    LMSTUDIO_URL = ManagedProperty('LMSTUDIO_URL', type_=str, allowed=lambda value, inst: valid_saved_api_url(value))
    OPENAI_COMPATIBLE_URL = ManagedProperty('OPENAI_COMPATIBLE_URL', type_=str, allowed=lambda value, inst: valid_saved_api_url(value))

    # --- 文字起こし用 API キー・URL (翻訳用の AUTH_KEYS/OPENAI_COMPATIBLE_URL とは
    # 意図的に別管理にしている。レート制限/クォータの共有を避け、翻訳と
    # 文字起こしで別々のキー・エンドポイントを使いたいケースに対応するため。
    TRANSCRIPTION_AUTH_KEYS = ValidatedProperty('TRANSCRIPTION_AUTH_KEYS',
        validator=lambda val, inst: (
            {
                k: (val[k] if (k in val and isinstance(val[k], (str, type(None)))) else inst.TRANSCRIPTION_AUTH_KEYS.get(k))
                for k in inst.TRANSCRIPTION_AUTH_KEYS.keys()
            }
            if isinstance(val, dict) else None
        )
    )
    TRANSCRIPTION_CUSTOM_URL = ManagedProperty('TRANSCRIPTION_CUSTOM_URL', type_=str, allowed=lambda value, inst: valid_saved_api_url(value))

    # --- Transcription settings ---
    SELECTED_TRANSCRIPTION_COMPUTE_TYPE = ValidatedProperty('SELECTED_TRANSCRIPTION_COMPUTE_TYPE', _selected_transcription_compute_type_validator)

    # --- Overlay settings ---
    OVERLAY_SMALL_LOG_SETTINGS = ValidatedProperty('OVERLAY_SMALL_LOG_SETTINGS', _overlay_small_validator)
    OVERLAY_LARGE_LOG_SETTINGS = ValidatedProperty('OVERLAY_LARGE_LOG_SETTINGS', _overlay_large_validator)
    # Captions over the desktop, for VRChat without a headset. The UI draws them in its own window.
    OVERLAY_DESKTOP_SETTINGS = ValidatedProperty('OVERLAY_DESKTOP_SETTINGS', _overlay_desktop_validator)
    IO_FLOW_OVERLAY_SETTINGS = ValidatedProperty('IO_FLOW_OVERLAY_SETTINGS', _io_flow_overlay_validator)
    # VRパネルの位置。UIからは設定せず、VR内で掴んで動かした位置だけが保存される。
    OVERLAY_VR_PANEL_SETTINGS = ValidatedProperty('OVERLAY_VR_PANEL_SETTINGS', _make_overlay_vr_window_validator('OVERLAY_VR_PANEL_SETTINGS'))
    # VR UIのランチャー (手首の帯) の位置。OVERLAY_VR_PANEL_SETTINGS はログウィンドウの位置。
    OVERLAY_VR_LAUNCHER_SETTINGS = ValidatedProperty('OVERLAY_VR_LAUNCHER_SETTINGS', _make_overlay_vr_window_validator('OVERLAY_VR_LAUNCHER_SETTINGS'))

    # --- Message format settings ---
    SEND_MESSAGE_FORMAT_PARTS = ValidatedProperty('SEND_MESSAGE_FORMAT_PARTS', _format_validator_send)
    RECEIVED_MESSAGE_FORMAT_PARTS = ValidatedProperty('RECEIVED_MESSAGE_FORMAT_PARTS', _format_validator_received)

    # Convert remaining simple properties to ManagedProperty to reduce repetition
    VOICE_SETTINGS = ValidatedProperty('VOICE_SETTINGS', normalize_settings)
    DIRECT_VOICE_SETTINGS = ValidatedProperty('DIRECT_VOICE_SETTINGS', normalize_direct_settings)
    REALTIME_ASR_SETTINGS = ValidatedProperty('REALTIME_ASR_SETTINGS', lambda value, instance: normalize_realtime_settings(value))
    SPEECH_SERVER_SETTINGS = ValidatedProperty('SPEECH_SERVER_SETTINGS', lambda value, instance: normalize_speech_server_settings(value))
    WEBSOCKET_SERVER = ManagedProperty('WEBSOCKET_SERVER', type_=bool)
    OSC_IP_ADDRESS = ManagedProperty('OSC_IP_ADDRESS', type_=str)
    OSC_PORT = ManagedProperty('OSC_PORT', type_=int, allowed=lambda v, inst: isValidPort(v))
    AUTO_CLEAR_MESSAGE_BOX = ManagedProperty('AUTO_CLEAR_MESSAGE_BOX', type_=bool)
    SEND_ONLY_TRANSLATED_MESSAGES = ManagedProperty('SEND_ONLY_TRANSLATED_MESSAGES', type_=bool)
    OVERLAY_SMALL_LOG = ManagedProperty('OVERLAY_SMALL_LOG', type_=bool)
    OVERLAY_LARGE_LOG = ManagedProperty('OVERLAY_LARGE_LOG', type_=bool)
    OVERLAY_DESKTOP = ManagedProperty('OVERLAY_DESKTOP', type_=bool)
    # VR UI (手首のランチャーとログ・言語・VR設定のウィンドウ)。字幕のオーバーレイとは別にON/OFFする
    OVERLAY_VR_PANEL = ManagedProperty('OVERLAY_VR_PANEL', type_=bool)
    # VR UIのログウィンドウを掴めなくする (操作バーのロック)
    OVERLAY_VR_PANEL_LOCKED = ManagedProperty('OVERLAY_VR_PANEL_LOCKED', type_=bool)
    # VR UIのログの文字の大きさ (px、訳文はこの約1.4倍)。デスクトップのログの文字サイズとは別
    OVERLAY_VR_PANEL_FONT_SIZE = ManagedProperty('OVERLAY_VR_PANEL_FONT_SIZE', type_=int)
    # VR UIのランチャーを手首を見たときだけ出すか (出す角度は45°で固定)。付ける手は OVERLAY_VR_LAUNCHER_SETTINGS の tracker
    OVERLAY_VR_LAUNCHER_AUTO_HIDE = ManagedProperty('OVERLAY_VR_LAUNCHER_AUTO_HIDE', type_=bool)
    # VR UIのボタンを指したときの吹き出し (操作名と状態)。慣れたら消せる
    OVERLAY_VR_TOOLTIP = ManagedProperty('OVERLAY_VR_TOOLTIP', type_=bool)
    OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES = ManagedProperty('OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES', type_=bool)
    SEND_MESSAGE_TO_VRC = ManagedProperty('SEND_MESSAGE_TO_VRC', type_=bool)
    SEND_RECEIVED_MESSAGE_TO_VRC = ManagedProperty('SEND_RECEIVED_MESSAGE_TO_VRC', type_=bool)
    LOGGER_FEATURE = ManagedProperty('LOGGER_FEATURE', type_=bool)
    VRC_MIC_MUTE_SYNC = ManagedProperty('VRC_MIC_MUTE_SYNC', type_=bool)
    NOTIFICATION_VRC_SFX = ManagedProperty('NOTIFICATION_VRC_SFX', type_=bool)
    # 0.0.0.0/:: (ワイルドカードアドレス) を拒否する。setWebSocketHost() の
    # 入力検証だけでは、config.json に (過去バージョンや手動編集で)
    # 0.0.0.0 が既に保存されているケースを防げない。load_config() の
    # setattr() はディスクリプタ経由なのでこの allowed もそこで効き、
    # 全インターフェースへのbindを防ぐ。OBSと事前確認に合わせてIPv4に限る。
    WEBSOCKET_HOST = ManagedProperty(
        'WEBSOCKET_HOST', type_=str,
        allowed=lambda v, inst: isValidWebSocketHost(v),
    )
    WEBSOCKET_PORT = ManagedProperty('WEBSOCKET_PORT', type_=int, allowed=lambda v, inst: isValidPort(v))
    # WebSocket サーバーへの接続トークン。127.0.0.1 バインドや Origin
    # ヘッダーだけでは「同じ PC 上で開いた任意の Web ページの JS が直接
    # ws://127.0.0.1:PORT に接続してマイク/スピーカーの文字起こしを
    # 盗聴する」ことを防げない (WebSocket は同一オリジンポリシーの対象外)
    # ため、これを知らないクライアントを拒否する唯一の実効的な防御として
    # 使う。初回起動時に 1 回だけ生成し、以降は config.json に永続化する
    # (プロセス起動ごとに変えると、OBS Browser Source や外部連携ツール
    # (例: VRCT-TTS) が再起動のたびに接続できなくなってしまうため)。
    WEBSOCKET_AUTH_TOKEN = ManagedProperty(
        'WEBSOCKET_AUTH_TOKEN', type_=str,
        allowed=lambda v, inst: isinstance(v, str) and bool(v.strip()),
    )

    # --- OBS Browser Source (overlay for OBS) ---
    OBS_BROWSER_SOURCE = ManagedProperty('OBS_BROWSER_SOURCE', type_=bool)
    OBS_BROWSER_SOURCE_PORT = ManagedProperty('OBS_BROWSER_SOURCE_PORT', type_=int, allowed=lambda v, inst: isValidPort(v))
    OBS_BROWSER_SOURCE_MAX_MESSAGES = ManagedProperty('OBS_BROWSER_SOURCE_MAX_MESSAGES', type_=int, allowed=lambda v, inst: is_valid_numeric_setting('MAX_MESSAGES', v))
    OBS_BROWSER_SOURCE_DISPLAY_DURATION = ManagedProperty('OBS_BROWSER_SOURCE_DISPLAY_DURATION', type_=int, allowed=lambda v, inst: is_valid_numeric_setting('DISPLAY_DURATION', v))
    OBS_BROWSER_SOURCE_FADEOUT_DURATION = ManagedProperty('OBS_BROWSER_SOURCE_FADEOUT_DURATION', type_=int, allowed=lambda v, inst: is_valid_numeric_setting('FADEOUT_DURATION', v))
    OBS_BROWSER_SOURCE_FONT_SIZE = ManagedProperty('OBS_BROWSER_SOURCE_FONT_SIZE', type_=int, allowed=lambda v, inst: is_valid_numeric_setting('FONT_SIZE', v))
    OBS_BROWSER_SOURCE_FONT_COLOR = ManagedProperty('OBS_BROWSER_SOURCE_FONT_COLOR', type_=str)
    OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS = ManagedProperty('OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS', type_=int, allowed=lambda v, inst: is_valid_numeric_setting('FONT_OUTLINE_THICKNESS', v))
    OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR = ManagedProperty('OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR', type_=str)

    # --- Telemetry Settings ---
    # Usage events go to VRCT-VOX's own receiver unless the user turns this off
    # (models/telemetry). Nothing is sent before the notice below has been shown.
    ENABLE_TELEMETRY = ManagedProperty('ENABLE_TELEMETRY', type_=bool)
    # The version of the telemetry notice the user has seen; 0 for none. A settings file
    # from before the notice existed carries ENABLE_TELEMETRY false without anyone having
    # chosen it, so the choice counts only from the notice on.
    TELEMETRY_NOTICE = ManagedProperty('TELEMETRY_NOTICE', type_=int, allowed=lambda v, inst: 0 <= v <= 1000,
                                       immediate_save=True)
    AUTO_DOWNLOAD_MODELS = ManagedProperty('AUTO_DOWNLOAD_MODELS', type_=bool)
    LEGACY_MODEL_DOWNLOAD_CONSENTS = ManagedProperty(
        'LEGACY_MODEL_DOWNLOAD_CONSENTS', type_=dict, immediate_save=True,
        allowed=lambda v, inst: all(isinstance(k, str) and isinstance(value, str) for k, value in v.items()))

    # --- Selection properties with validation (ManagedProperty) ---
    SELECTED_TAB_NO = ManagedProperty('SELECTED_TAB_NO', type_=str, allowed=lambda v, inst: v in inst.SELECTABLE_TAB_NO_LIST)
    SELECTED_TRANSCRIPTION_ENGINE = ManagedProperty('SELECTED_TRANSCRIPTION_ENGINE', type_=str, allowed=lambda v, inst: v is None or v in inst.SELECTABLE_TRANSCRIPTION_ENGINE_LIST, allow_none=True)
    SELECTED_RELEASE_CHANNEL = ManagedProperty('SELECTED_RELEASE_CHANNEL', type_=str, allowed=lambda v, inst: v in inst.SELECTABLE_RELEASE_CHANNEL_LIST)
    CTRANSLATE2_WEIGHT_TYPE = ManagedProperty('CTRANSLATE2_WEIGHT_TYPE', type_=str, allowed=lambda v, inst: v in inst.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_LIST)
    # True once the user has seen the non-commercial license notice for the
    # selected CTranslate2 weight, either because they confirmed it when
    # choosing an NLLB weight or because Controller.init() showed the one-time
    # notice for an NLLB weight saved by an older version (where NLLB was the
    # default, so the saved value is usually not a deliberate choice).
    CTRANSLATE2_LICENSE_NOTICE_SHOWN = ManagedProperty('CTRANSLATE2_LICENSE_NOTICE_SHOWN', type_=bool)
    WHISPER_WEIGHT_TYPE = ManagedProperty('WHISPER_WEIGHT_TYPE', type_=str, allowed=lambda v, inst: v in inst.SELECTABLE_WHISPER_WEIGHT_TYPE_LIST)
    SELECTED_PLAMO_MODEL = ManagedProperty('SELECTED_PLAMO_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_PLAMO_MODEL_LIST'), allow_none=True)
    SELECTED_GEMINI_MODEL = ManagedProperty('SELECTED_GEMINI_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_GEMINI_MODEL_LIST'), allow_none=True)
    SELECTED_OPENAI_MODEL = ManagedProperty('SELECTED_OPENAI_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_OPENAI_MODEL_LIST'), allow_none=True)
    SELECTED_GROQ_MODEL = ManagedProperty('SELECTED_GROQ_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_GROQ_MODEL_LIST'), allow_none=True)
    SELECTED_OPENROUTER_MODEL = ManagedProperty('SELECTED_OPENROUTER_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_OPENROUTER_MODEL_LIST'), allow_none=True)
    SELECTED_LMSTUDIO_MODEL = ManagedProperty('SELECTED_LMSTUDIO_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_LMSTUDIO_MODEL_LIST'), allow_none=True)
    SELECTED_OPENAI_COMPATIBLE_MODEL = ManagedProperty('SELECTED_OPENAI_COMPATIBLE_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST'), allow_none=True)
    SELECTED_OLLAMA_MODEL = ManagedProperty('SELECTED_OLLAMA_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_OLLAMA_MODEL_LIST'), allow_none=True)
    SELECTED_GROQ_WHISPER_MODEL = ManagedProperty('SELECTED_GROQ_WHISPER_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_GROQ_WHISPER_MODEL_LIST'), allow_none=True)
    SELECTED_OPENAI_WHISPER_MODEL = ManagedProperty('SELECTED_OPENAI_WHISPER_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_OPENAI_WHISPER_MODEL_LIST'), allow_none=True)
    SELECTED_CUSTOM_WHISPER_MODEL = ManagedProperty('SELECTED_CUSTOM_WHISPER_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_CUSTOM_WHISPER_MODEL_LIST'), allow_none=True)
    SELECTED_DEEPGRAM_MODEL = ManagedProperty('SELECTED_DEEPGRAM_MODEL', type_=str, allowed=_allowed_in_populated('SELECTABLE_DEEPGRAM_MODEL_LIST'), allow_none=True)

    # --- Translation and language settings ---
    MIC_WORD_FILTER = ValidatedProperty('MIC_WORD_FILTER', _mic_word_filter_validator)
    SELECTED_TRANSLATION_ENGINES = ValidatedProperty('SELECTED_TRANSLATION_ENGINES', _selected_translation_engines_validator)
    SELECTED_YOUR_LANGUAGES = ValidatedProperty('SELECTED_YOUR_LANGUAGES', _selected_your_languages_validator)
    SELECTED_TARGET_LANGUAGES = ValidatedProperty('SELECTED_TARGET_LANGUAGES', _selected_target_languages_validator)
    SELECTED_TRANSLATION_COMPUTE_TYPE = ValidatedProperty('SELECTED_TRANSLATION_COMPUTE_TYPE', _selected_translation_compute_type_validator)

    # --- Device settings ---
    AUTO_MIC_SELECT = ManagedProperty('AUTO_MIC_SELECT', type_=bool)
    AUTO_SPEAKER_SELECT = ManagedProperty('AUTO_SPEAKER_SELECT', type_=bool)
    SELECTED_MIC_HOST = ValidatedProperty('SELECTED_MIC_HOST', _mic_host_validator)
    SELECTED_MIC_DEVICE = ValidatedProperty('SELECTED_MIC_DEVICE', _mic_device_validator)
    SELECTED_MIC_DEVICE_ID = ValidatedProperty('SELECTED_MIC_DEVICE_ID', lambda v, _: v if isinstance(v, str) else None)
    SELECTED_SPEAKER_DEVICE_ID = ValidatedProperty('SELECTED_SPEAKER_DEVICE_ID', lambda v, _: v if isinstance(v, str) else None)
    SELECTED_SPEAKER_DEVICE = ValidatedProperty('SELECTED_SPEAKER_DEVICE', _speaker_device_validator)
    SELECTED_TRANSLATION_COMPUTE_DEVICE = ValidatedProperty('SELECTED_TRANSLATION_COMPUTE_DEVICE', _compute_device_validator)
    SELECTED_TRANSCRIPTION_COMPUTE_DEVICE = ValidatedProperty('SELECTED_TRANSCRIPTION_COMPUTE_DEVICE', _compute_device_validator)

    # -- Clipboard control ---
    ENABLE_CLIPBOARD = ManagedProperty('ENABLE_CLIPBOARD', type_=bool)

    # --- VRChat chat-bubble OCR ---
    # Target language is intentionally absent: OCR reads other players' chat,
    # so it always translates into your own language via getOutputTranslate.
    OCR_SOURCE_LANGUAGE = ManagedProperty('OCR_SOURCE_LANGUAGE', type_=str, allowed=lambda v, inst: v in inst.SELECTABLE_OCR_SOURCE_LANGUAGE_LIST)
    OCR_WINDOW_TITLE = ManagedProperty('OCR_WINDOW_TITLE', type_=str, allowed=lambda v, inst: len(v) > 0)
    OCR_POLL_INTERVAL_MS = ManagedProperty('OCR_POLL_INTERVAL_MS', type_=int, allowed=lambda v, inst: 100 <= v <= 5000)
    OCR_MIN_CONFIDENCE = ManagedProperty('OCR_MIN_CONFIDENCE', type_=(int, float), allowed=lambda v, inst: 0.1 <= v <= 0.99)
    OCR_BUBBLE_MIN_TEXT_LENGTH = ManagedProperty('OCR_BUBBLE_MIN_TEXT_LENGTH', type_=int, allowed=lambda v, inst: 1 <= v <= 50)
    # The part of the window to read, and whether to keep only chatbox-style text
    # (light glyphs on a dark panel); both apply with or without the detector.
    # The detector switch only matters once its verified download is present.
    # See ocr_detection.py and ocr_chatbox_detector.py.
    OCR_CAPTURE_REGION = ManagedProperty('OCR_CAPTURE_REGION', type_=dict, allowed=_ocr_capture_region_validator)
    # Keep the original key for the desktop window; VR has independent coordinates.
    OCR_VR_CAPTURE_REGION = ManagedProperty('OCR_VR_CAPTURE_REGION', type_=dict, allowed=_ocr_capture_region_validator)
    OCR_CHATBOX_FILTER = ManagedProperty('OCR_CHATBOX_FILTER', type_=bool)
    OCR_USE_CHATBOX_DETECTOR = ManagedProperty('OCR_USE_CHATBOX_DETECTOR', type_=bool)
    # Linux: what the desktop's ScreenCast portal hands out so that sharing the same window
    # again needs no dialog. The desktop replaces it on every use, so it is saved at once; "" means none.
    OCR_PORTAL_RESTORE_TOKEN = ManagedProperty('OCR_PORTAL_RESTORE_TOKEN', type_=str, allowed=_ocr_portal_restore_token_validator, immediate_save=True)

    def init_config(self):
        self._initialized = False
        self._config_loaded = False
        self._SELECTED_MIC_DEVICE_ID = ''
        self._SELECTED_SPEAKER_DEVICE_ID = ''
        # Read Only
        self._VERSION = "0.2.0-beta.1"
        if getattr(sys, 'frozen', False):
            self._PATH_LOCAL = os_path.dirname(sys.executable)
        else:
            self._PATH_LOCAL = os_path.dirname(os_path.abspath(__file__))
        from runtime_paths import data_root
        self._PATH_DATA = str(data_root(self._PATH_LOCAL))
        # Override mutable state only; resources and existing weights keep their
        # original location. This also permits isolated native acceptance tests.
        state_dir = os_path.abspath(os_path.expanduser(environ.get("VRCT_CONFIG_DIR") or self._PATH_LOCAL))
        self._PATH_CONFIG = os_path.join(state_dir, "config.json")
        self._PATH_LOGS = os_path.join(state_dir, "logs")
        self._GITHUB_URL = "https://api.github.com/repos/kein5/VRCT-VOX/releases/latest"
        self._GITHUB_RELEASES_LIST_URL = "https://api.github.com/repos/kein5/VRCT-VOX/releases"
        # VRCT-VOX numbers its own releases from 0.1.0, each with the version
        # picker UI; older tags in this repository are hidden so users can't
        # switch to a build they can't switch back from.
        # Prereleases of this version (0.1.0-beta.N) are included.
        self._MIN_SUPPORTED_VERSION = "0.1.0"
        self._SELECTABLE_RELEASE_CHANNEL_LIST = ["stable", "beta"]
        self._SELECTED_RELEASE_CHANNEL = "stable"

        self._MAX_MIC_THRESHOLD = 2000
        self._MAX_SPEAKER_THRESHOLD = 2000
        self._WATCHDOG_TIMEOUT = 60
        self._WATCHDOG_INTERVAL = 20

        self._SELECTABLE_TAB_NO_LIST = ["1", "2", "3"]
        # these external mappings may be empty dicts if the optional modules failed to import
        self._SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_LIST = getattr(ctranslate2_weights, 'keys', lambda: [])()
        self._SELECTABLE_WHISPER_WEIGHT_TYPE_LIST = getattr(whisper_models, 'keys', lambda: [])()
        self._SELECTABLE_TRANSLATION_ENGINE_LIST = getattr(translation_lang, 'keys', lambda: [])()
        try:
            # transcription_lang is nested dict; attempt to extract keys defensively
            first_key = next(iter(transcription_lang))
            self._SELECTABLE_TRANSCRIPTION_ENGINE_LIST = list(transcription_lang[first_key].values())[0].keys()
        except Exception:
            self._SELECTABLE_TRANSCRIPTION_ENGINE_LIST = []
        self._SELECTABLE_UI_LANGUAGE_LIST = ["en", "ja"]
        # OCRエンジンが読める言語だけ (VRCTが翻訳できる言語の全てではない)。
        self._SELECTABLE_OCR_SOURCE_LANGUAGE_LIST = list(ocr_selectable_languages)
        self._SELECTABLE_COMPUTE_DEVICE_LIST = getComputeDeviceList()
        self._COMPUTE_MODE = "cuda" if any(
            device.get("device") == "cuda" for device in self._SELECTABLE_COMPUTE_DEVICE_LIST
        ) else "cpu"
        self._SEND_MESSAGE_BUTTON_TYPE_LIST = ["show", "hide", "show_and_disable_enter_key"]

        # Read Write
        self._ENABLE_TRANSLATION = False
        self._ENABLE_TRANSCRIPTION_SEND = False
        self._ENABLE_TRANSCRIPTION_RECEIVE = False
        self._ENABLE_OCR_CAPTURE = False
        self._ENABLE_FOREGROUND = False
        self._ENABLE_CHECK_ENERGY_SEND = False
        self._ENABLE_CHECK_ENERGY_RECEIVE = False
        self._SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT = {}
        for weight_type in self.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_LIST:
            self._SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT[weight_type] = False
        self._SELECTABLE_WHISPER_WEIGHT_TYPE_DICT = {}
        for weight_type in self.SELECTABLE_WHISPER_WEIGHT_TYPE_LIST:
            self._SELECTABLE_WHISPER_WEIGHT_TYPE_DICT[weight_type] = False
        self._SELECTABLE_TRANSLATION_ENGINE_STATUS = {}
        self._SELECTABLE_TRANSCRIPTION_ENGINE_STATUS = {}
        for engine in self.SELECTABLE_TRANSCRIPTION_ENGINE_LIST:
            self._SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = False
        self._SELECTABLE_PLAMO_MODEL_LIST = []
        self._SELECTABLE_GEMINI_MODEL_LIST = []
        self._SELECTABLE_OPENAI_MODEL_LIST = []
        self._SELECTABLE_GROQ_MODEL_LIST = []
        self._SELECTABLE_OPENROUTER_MODEL_LIST = []
        self._SELECTABLE_LMSTUDIO_MODEL_LIST = []
        self._SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST = []
        self._SELECTABLE_OLLAMA_MODEL_LIST = []
        self._SELECTABLE_GROQ_WHISPER_MODEL_LIST = []
        self._SELECTABLE_OPENAI_WHISPER_MODEL_LIST = []
        self._SELECTABLE_CUSTOM_WHISPER_MODEL_LIST = []
        self._SELECTABLE_DEEPGRAM_MODEL_LIST = []
        self._DEEPGRAM_MODEL_LANGUAGES = {}

        # Save Json Data
        ## Main Window
        self._SELECTED_TAB_NO = "1"
        self._SELECTED_TRANSLATION_ENGINES = {}
        for tab_no in self.SELECTABLE_TAB_NO_LIST:
            self._SELECTED_TRANSLATION_ENGINES[tab_no] = "CTranslate2"
        self._SELECTED_YOUR_LANGUAGES = {}
        for tab_no in self.SELECTABLE_TAB_NO_LIST:
            self._SELECTED_YOUR_LANGUAGES[tab_no] = {
                "1": {
                    "language": "Japanese",
                    "country": "Japan",
                    "enable": True,
                },
            }
        self._SELECTED_TARGET_LANGUAGES = {}
        self._SELECTED_TAB_TARGET_LANGUAGES_NO_LIST = ["1", "2", "3"]
        for tab_no in self.SELECTABLE_TAB_NO_LIST:
            for tab_target_lang_no in self.SELECTED_TAB_TARGET_LANGUAGES_NO_LIST:
                if tab_no not in self.SELECTED_TARGET_LANGUAGES:
                    self._SELECTED_TARGET_LANGUAGES[tab_no] = {}
                if tab_target_lang_no not in self.SELECTED_TARGET_LANGUAGES[tab_no]:
                    self._SELECTED_TARGET_LANGUAGES[tab_no][tab_target_lang_no] = {
                        "language": "English",
                        "country": "United States",
                        "enable": True if tab_target_lang_no == self.SELECTED_TAB_TARGET_LANGUAGES_NO_LIST[0] else False,
                    }
        self._SELECTED_TRANSCRIPTION_ENGINE = None
        self._CONVERT_MESSAGE_TO_ROMAJI = False
        self._CONVERT_MESSAGE_TO_HIRAGANA = False
        self._MAIN_WINDOW_SIDEBAR_COMPACT_MODE = False

        ## Config Window
        self._TRANSPARENCY = 100
        self._UI_SCALING = 100
        self._TEXTBOX_UI_SCALING = 100
        self._MESSAGE_BOX_RATIO = 10
        self._SEND_MESSAGE_BUTTON_TYPE = "show"
        self._SHOW_RESEND_BUTTON = False
        self._FONT_FAMILY = "Yu Gothic UI"
        self._UI_LANGUAGE = "en"
        self._MAIN_WINDOW_GEOMETRY = {
            "x_pos": 0,
            "y_pos": 0,
            "width": 870,
            "height": 654,
        }
        self._AUTO_MIC_SELECT = True
        # device_manager may be unavailable or not initialized; use safe defaults
        try:
            if device_manager is not None:
                # getDefaultMicDevice performs lazy init/update if needed
                dm_def = device_manager.getDefaultMicDevice()
                self._SELECTED_MIC_HOST = dm_def.get("host", {}).get("name", "NoHost")
                self._SELECTED_MIC_DEVICE = dm_def.get("device", {}).get("name", "NoDevice")
            else:
                self._SELECTED_MIC_HOST = "NoHost"
                self._SELECTED_MIC_DEVICE = "NoDevice"
        except Exception:
            errorLogging()
            self._SELECTED_MIC_HOST = "NoHost"
            self._SELECTED_MIC_DEVICE = "NoDevice"
        self._MIC_THRESHOLD = 300
        self._MIC_AUTOMATIC_THRESHOLD = False
        self._MIC_RECORD_TIMEOUT = 3
        self._MIC_PHRASE_TIMEOUT = 3
        self._MIC_MAX_PHRASES = 10
        self._MIC_WORD_FILTER = []
        self._HOTKEYS = {
            "open_quick_chat": None,
            "toggle_vrct_visibility": None,
            "toggle_translation": None,
            "toggle_transcription_send": None,
            "toggle_transcription_receive": None,
            "stop_voice": None,
            "toggle_voice_mute": None,
            "toggle_tts": None,
            "toggle_rvc": None,
        }
        self._MIC_AVG_LOGPROB = -0.8
        self._MIC_NO_SPEECH_PROB = 0.6
        self._MIC_NO_REPEAT_NGRAM_SIZE = 0
        self._AUTO_SPEAKER_SELECT = True
        try:
            if device_manager is not None:
                sp_def = device_manager.getDefaultSpeakerDevice()
                self._SELECTED_SPEAKER_DEVICE = sp_def.get("device", {}).get("name", "NoDevice")
            else:
                self._SELECTED_SPEAKER_DEVICE = "NoDevice"
        except Exception:
            errorLogging()
            self._SELECTED_SPEAKER_DEVICE = "NoDevice"
        self._SPEAKER_THRESHOLD = 300
        self._SPEAKER_AUTOMATIC_THRESHOLD = False
        self._SPEAKER_RECORD_TIMEOUT = 3
        self._SPEAKER_PHRASE_TIMEOUT = 3
        self._SPEAKER_MAX_PHRASES = 10
        self._SPEAKER_AVG_LOGPROB = -0.8
        self._SPEAKER_NO_SPEECH_PROB = 0.6
        self._SPEAKER_NO_REPEAT_NGRAM_SIZE = 0
        self._MIC_ENABLE_VAD = False
        self._SPEAKER_ENABLE_VAD = False
        self._OSC_IP_ADDRESS = "127.0.0.1"
        self._OSC_PORT = 9000
        self._AUTH_KEYS = {
            "DeepL_API": None,
            "Plamo_API": None,
            "Gemini_API": None,
            "OpenAI_API": None,
            "OpenAI_Compatible": None,
            "Groq_API": None,
            "OpenRouter_API": None,
        }
        self._TRANSCRIPTION_AUTH_KEYS = {
            "Groq_Whisper": None,
            "OpenAI_Whisper": None,
            "Custom_Whisper": None,
            "Deepgram": None,
        }
        self._TRANSCRIPTION_CUSTOM_URL = ""
        self._SELECTED_TRANSLATION_COMPUTE_DEVICE = copy.deepcopy(self.SELECTABLE_COMPUTE_DEVICE_LIST[0])
        self._SELECTED_TRANSCRIPTION_COMPUTE_DEVICE = copy.deepcopy(self.SELECTABLE_COMPUTE_DEVICE_LIST[0])
        # MIT-licensed. Configs saved by older versions keep their stored
        # value (load_config() overwrites this default), including the
        # previous non-commercial default nllb-200-distilled-600M-ct2-int8.
        self._CTRANSLATE2_WEIGHT_TYPE = DEFAULT_CTRANSLATE2_WEIGHT_TYPE
        self._CTRANSLATE2_LICENSE_NOTICE_SHOWN = False
        self._SELECTED_PLAMO_MODEL = None
        self._SELECTED_GEMINI_MODEL = None
        self._SELECTED_OPENAI_MODEL = None
        self._SELECTED_GROQ_MODEL = None
        self._SELECTED_OPENROUTER_MODEL = None
        self._LMSTUDIO_URL = "http://127.0.0.1:1234/v1"
        self._SELECTED_LMSTUDIO_MODEL = None
        self._OPENAI_COMPATIBLE_URL = "https://api.openai.com/v1"
        self._SELECTED_OPENAI_COMPATIBLE_MODEL = None
        self._SELECTED_OLLAMA_MODEL = None
        self._SELECTED_GROQ_WHISPER_MODEL = None
        self._SELECTED_OPENAI_WHISPER_MODEL = None
        self._SELECTED_CUSTOM_WHISPER_MODEL = None
        self._SELECTED_DEEPGRAM_MODEL = None
        self._SELECTED_TRANSLATION_COMPUTE_TYPE = "auto"
        self._WHISPER_WEIGHT_TYPE = "base"
        self._SELECTED_TRANSCRIPTION_COMPUTE_TYPE = "auto"
        self._AUTO_CLEAR_MESSAGE_BOX = True
        self._SEND_ONLY_TRANSLATED_MESSAGES = False
        self._OVERLAY_SMALL_LOG = False
        self._OVERLAY_SMALL_LOG_SETTINGS = {
            "x_pos": 0.0,
            "y_pos": 0.0,
            "z_pos": 0.0,
            "x_rotation": 0.0,
            "y_rotation": 0.0,
            "z_rotation": 0.0,
            "display_duration": 5,
            "fadeout_duration": 2,
            "opacity": 1.0,
            "ui_scaling": 1.0,
            "tracker": "HMD",
        }
        self._OVERLAY_LARGE_LOG = False
        self._OVERLAY_LARGE_LOG_SETTINGS = {
            "x_pos": 0.0,
            "y_pos": 0.0,
            "z_pos": 0.0,
            "x_rotation": 0.0,
            "y_rotation": 0.0,
            "z_rotation": 0.0,
            "display_duration": 5,
            "fadeout_duration": 2,
            "opacity": 1.0,
            "ui_scaling": 1.0,
            "tracker": "LeftHand",
        }
        self._OVERLAY_DESKTOP = False
        self._OVERLAY_DESKTOP_SETTINGS = {
            "position": "bottom",
            "font_size": 28,
            "display_duration": 6,
            "opacity": 0.6,
        }
        # Where the user's voice and chat go, with stage times, over the desktop (one input by default).
        self._IO_FLOW_OVERLAY_SETTINGS = {"desktop": False, "count": 1}
        self._OVERLAY_VR_LAUNCHER_SETTINGS = dict(DEFAULT_OVERLAY_VR_LAUNCHER_SETTINGS)
        self._OVERLAY_VR_PANEL = False
        self._OVERLAY_VR_PANEL_LOCKED = False
        self._OVERLAY_VR_PANEL_FONT_SIZE = 17
        self._OVERLAY_VR_LAUNCHER_AUTO_HIDE = True
        self._OVERLAY_VR_TOOLTIP = True
        self._OVERLAY_VR_PANEL_SETTINGS = {
            # ログウィンドウの大きさ (論理px)。角を掴んで伸ばす (600x400〜1400x1000)
            "width": 900,
            "height": 700,
            # ワールド固定の初期位置・向き (実機で置いた位置, 2026-10-14)
            "x_pos": 0.5209,
            "y_pos": 0.6442,
            "z_pos": -0.9509,
            "x_rotation": 95.0133,
            "y_rotation": 44.0232,
            "z_rotation": 42.6138,
            "display_duration": 5,
            "fadeout_duration": 0,  # パネルはフェードさせない
            "opacity": 1.0,
            "ui_scaling": 0.4,  # 横幅(m)
            "tracker": "Playspace",  # 初めは、ワールドに固定する (開いたとき、視線の外なら目の前へ置き直す)
        }
        self._OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES = False
        self._SEND_MESSAGE_TO_VRC = True
        self._SEND_RECEIVED_MESSAGE_TO_VRC = False
        self._LOGGER_FEATURE = False
        self._VRC_MIC_MUTE_SYNC = False
        self._NOTIFICATION_VRC_SFX = True
        self._SEND_MESSAGE_FORMAT_PARTS = {
            "message": {
                "prefix": "",
                "suffix": ""
                },
            "separator": "\n",
            "translation": {
                "prefix": "",
                "separator": "\n",
                "suffix": ""
            },
            "translation_first": False,
        }
        self._RECEIVED_MESSAGE_FORMAT_PARTS = {
            "message": {
                "prefix": "",
                "suffix": ""
                },
            "separator": "\n",
            "translation": {
                "prefix": "",
                "separator": "\n",
                "suffix": ""
            },
            "translation_first": False,
        }
        self._VOICE_SETTINGS = VoiceSettings().to_dict()
        self._DIRECT_VOICE_SETTINGS = DirectSettings().to_dict()
        self._REALTIME_ASR_SETTINGS = normalize_realtime_settings({})
        self._SPEECH_SERVER_SETTINGS = normalize_speech_server_settings({})
        self._WEBSOCKET_SERVER = False
        self._WEBSOCKET_HOST = "127.0.0.1"
        self._WEBSOCKET_PORT = 2231
        # 初回起動時のみここでランダム生成される。config.json に既に
        # WEBSOCKET_AUTH_TOKEN が保存されていれば、この直後の
        # load_config() の setattr() でその値に上書きされる (=以降は
        # 再起動しても同じトークンが使われる)。
        self._WEBSOCKET_AUTH_TOKEN = secrets_token_urlsafe(32)
        self._OBS_BROWSER_SOURCE = False
        self._OBS_BROWSER_SOURCE_PORT = 2232
        self._OBS_BROWSER_SOURCE_MAX_MESSAGES = 14
        self._OBS_BROWSER_SOURCE_DISPLAY_DURATION = 60
        self._OBS_BROWSER_SOURCE_FADEOUT_DURATION = 12
        self._OBS_BROWSER_SOURCE_FONT_SIZE = 40
        self._OBS_BROWSER_SOURCE_FONT_COLOR = "#FFFFFF"
        self._OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS = 3
        self._OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR = "#000000"
        self._ENABLE_CLIPBOARD = False
        self._ENABLE_TELEMETRY = True
        self._TELEMETRY_NOTICE = 0
        # Existing weights remain usable; network downloads require opt-in.
        self._AUTO_DOWNLOAD_MODELS = False
        self._LEGACY_MODEL_DOWNLOAD_CONSENTS = {}

        # OCR defaults (VRChat chat-bubble text capture)
        # PP-OCRv6 small が日英中＋ラテン文字系を1モデルで読むので "auto" が既定。
        # ハングル・キリル・タイ・アラビア・デーヴァナーガリーは別モデルが要るため
        # 明示選択する (選択肢は models/ocr/ocr_languages.py)。
        self._OCR_SOURCE_LANGUAGE = "auto"
        # Substring match against visible window titles (case-insensitive).
        self._OCR_WINDOW_TITLE = "VRChat"
        self._OCR_POLL_INTERVAL_MS = 750
        # PP-OCRは読めていないときでもスコアが高い (実測: 正解の最小0.87に対し
        # 誤りの中央値0.91)。0.55では何も落とせず、0.85なら正解を1件も失わずに
        # 誤りの34%を落とせたのでこの値にしている。
        self._OCR_MIN_CONFIDENCE = 0.85
        self._OCR_BUBBLE_MIN_TEXT_LENGTH = 2
        # Whole window until the user narrows it.
        self._OCR_CAPTURE_REGION = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
        self._OCR_VR_CAPTURE_REGION = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
        self._OCR_CHATBOX_FILTER = True
        # VRCT-VOX's chatbox detector is used whenever its verified download is present,
        # unless turned off here. Without the download this has no effect.
        self._OCR_USE_CHATBOX_DETECTOR = True
        # Nothing to restore until the user has shared a window once.
        self._OCR_PORTAL_RESTORE_TOKEN = ""

        # Finish defaults before reading resources or creating directories.
        loaded_translation_lang = loadTranslationLanguages(self.PATH_LOCAL)
        self._SELECTABLE_TRANSLATION_ENGINE_LIST = getattr(loaded_translation_lang, 'keys', lambda: [])()
        self._SELECTABLE_TRANSLATION_ENGINE_STATUS = {
            engine: False for engine in self.SELECTABLE_TRANSLATION_ENGINE_LIST
        }
        self._initialized = True
        try:
            os_makedirs(self._PATH_LOGS, exist_ok=True)
        except OSError:
            # Diagnostics must not prevent complete settings initialization.
            errorLogging()

    def _moveUnreadableConfigAside(self) -> str:
        """Reserve a unique backup name, then preserve the unreadable file."""
        import time
        fd, backup = exclusive_tempfile.mkstemp(
            prefix=f"{os_path.basename(self.PATH_CONFIG)}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}-",
            dir=os_path.dirname(self.PATH_CONFIG))
        os.close(fd)
        try:
            os_replace(self.PATH_CONFIG, backup)
            return backup
        except OSError:
            os_remove(backup)
            raise

    def load_config(self):
        with self._file_lock:
            if not self._initialized:
                raise RuntimeError("Config initialization is incomplete")
            self._config_loaded = False
            for name in ("_timer", "_save_retry_timer"):
                timer = getattr(self, name)
                if timer is not None:
                    timer.cancel()
                    setattr(self, name, None)
        self._loading_saved_config = True
        try:
            self._loadConfig()
        except Exception as error:
            with self._file_lock:
                # Retrying a write cannot repair a read or preservation failure.
                self._saveFailedLocked(error, retry=False)
            return
        finally:
            self._loading_saved_config = False
        with self._file_lock:
            self._config_loaded = True
        self.saveConfigToFile()

    def _loadConfig(self):
        self._config_data = {}
        # Set when config.json could not be read and was moved aside, so the
        # UI can say the app started with defaults and where the old file is.
        self.UNREADABLE_CONFIG_BACKUP = None
        try:
            with open(self.PATH_CONFIG, 'r', encoding="utf-8") as fp:
                self._config_data = json_load(fp)
            if not isinstance(self._config_data, dict):
                raise ValueError("config.json is not a JSON object")
        except FileNotFoundError:
            if os_path.lexists(self.PATH_CONFIG):
                raise
        except (ValueError, UnicodeDecodeError):
            errorLogging()
            self.UNREADABLE_CONFIG_BACKUP = self._moveUnreadableConfigAside()
            self._config_data = {}
        # Old single-region configs already use OCR_CAPTURE_REGION. Retain
        # that window region and migrate VR to the full view, never a copy.
        self._config_data.setdefault("OCR_VR_CAPTURE_REGION",
                                     {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})
        self.INVALID_SAVED_API_URLS = []
        for key, value in self._config_data.items():
            if key in CUSTOM_URL_KEYS and not valid_saved_api_url(value):
                # Empty disables discovery; never move a saved key to a fallback host.
                setattr(self, "_" + key, "")
                self.INVALID_SAVED_API_URLS.append(key)
                continue
            # Korean and Chinese were UI languages until 0.1.0. A setting that names one
            # falls back to English quietly: it is not a broken file.
            if key == "UI_LANGUAGE" and value in RETIRED_UI_LANGUAGES:
                continue
            # 読み込み時: serialize=True かつ readonlyでない Descriptor のみ反映。
            # 未知キー（Descriptorなし）は無視して注入を防止。
            try:
                descriptor = getattr(type(self), key, None)
                if isinstance(descriptor, ManagedProperty):
                    if descriptor.readonly or not descriptor.serialize:
                        continue
                    setattr(self, key, value)
                elif isinstance(descriptor, ValidatedProperty):
                    if not descriptor.serialize:
                        continue
                    setattr(self, key, value)
                else:
                    # 不明キーは破棄（古い/不要/改竄の可能性）
                    continue
            except ConfigValidationError:
                errorLogging()

        # config.json から読み込んだ SELECTED_RELEASE_CHANNEL は、前回起動時に
        # UI でチャンネルを切り替えた「つもり」の値をそのまま引き継いでいる
        # 可能性がある。model.updateSoftware()/updateCudaSoftware() は
        # インストーラ (NSIS) を起動した直後に VRCT を即終了する設計のため、
        # ユーザーがインストーラをキャンセルしても config.json には新
        # チャンネルが書き込まれたまま残ってしまう(実際にインストール
        # されているのは元のバージョンのまま)。起動のたびに、実際に
        # 動いている VERSION から機械的に再判定して上書きすることで、この
        # 不整合を自己修復する(NSIS 側の .onInit が ${VERSION} の
        # "-beta"/"-rc" サフィックスから同じ判定をしているのと同じ
        # ルール)。UI 経由の明示的な変更 (setSelectedReleaseChannel) 自体は
        # 今まで通り可能で、これは「起動時だけは実態を優先する」上書きに
        # すぎない。
        self.SELECTED_RELEASE_CHANNEL = self._channelForVersion(self.VERSION)

        # インストーラ (NSIS) が選択した UI 言語の反映。NSIS 側は config.json
        # を直接 JSON パースせず (UTF-8/非ASCII文字を含む既存ファイルで
        # nsJSON プラグインのパースが実機で確実に失敗することを確認済み、
        # 2026-08-21)、常に ASCII な言語コードだけを書いたこのマーカー
        # ファイルを置く。存在すれば検証の上 UI_LANGUAGE に反映し、
        # 一度使ったら削除する (以後のアプリ内言語変更をこのファイルが
        # 上書きし続けないようにするため)。
        installer_language_marker = os_path.join(self._PATH_LOCAL, "installer_language.txt")
        if os_path.isfile(installer_language_marker):
            try:
                with open(installer_language_marker, 'r', encoding="utf-8") as fp:
                    selected_language = fp.read().strip()
                if selected_language in self._SELECTABLE_UI_LANGUAGE_LIST:
                    self.UI_LANGUAGE = selected_language
            except Exception:
                errorLogging()
            finally:
                try:
                    os_remove(installer_language_marker)
                except Exception:
                    errorLogging()

    def revalidate_selected_models(self):
        pairs = [
            ('SELECTED_PLAMO_MODEL', 'SELECTABLE_PLAMO_MODEL_LIST'),
            ('SELECTED_GEMINI_MODEL', 'SELECTABLE_GEMINI_MODEL_LIST'),
            ('SELECTED_OPENAI_MODEL', 'SELECTABLE_OPENAI_MODEL_LIST'),
            ('SELECTED_GROQ_MODEL', 'SELECTABLE_GROQ_MODEL_LIST'),
            ('SELECTED_OPENROUTER_MODEL', 'SELECTABLE_OPENROUTER_MODEL_LIST'),
            ('SELECTED_LMSTUDIO_MODEL', 'SELECTABLE_LMSTUDIO_MODEL_LIST'),
            ('SELECTED_OPENAI_COMPATIBLE_MODEL', 'SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST'),
            ('SELECTED_OLLAMA_MODEL', 'SELECTABLE_OLLAMA_MODEL_LIST'),
            ('SELECTED_GROQ_WHISPER_MODEL', 'SELECTABLE_GROQ_WHISPER_MODEL_LIST'),
            ('SELECTED_OPENAI_WHISPER_MODEL', 'SELECTABLE_OPENAI_WHISPER_MODEL_LIST'),
            ('SELECTED_CUSTOM_WHISPER_MODEL', 'SELECTABLE_CUSTOM_WHISPER_MODEL_LIST'),
            ('SELECTED_DEEPGRAM_MODEL', 'SELECTABLE_DEEPGRAM_MODEL_LIST'),
        ]
        for sel_attr, list_attr in pairs:
            try:
                current = getattr(self, sel_attr)
                lst = getattr(self, list_attr)
                if lst and current is not None and current not in lst:
                    if len(lst) > 0:
                        setattr(self, sel_attr, lst[0])
                    else:
                        setattr(self, sel_attr, None)
            except Exception:
                errorLogging()

# Auto-register all descriptors after Config class definition
_auto_register_descriptors()

config = Config()

if __name__ == "__main__":
    print("Test config.py")
    for key, value in config._config_data.items():
        print(f"{key}: {value}")
