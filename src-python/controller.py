from models.network_policy import validate_api_url, DiscoveryScope, discovery_scope
from typing import Callable, Any, List, Optional
from contextlib import nullcontext
from subprocess import Popen
from threading import Event, Thread, Lock, RLock
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from dataclasses import asdict, replace
import copy
import functools
import re
from models.obs.settings import parse_numeric_setting
import time
import sys
from os import environ as os_environ
from pathlib import Path
from audio_device_identity import capture_key, device_id, device_options, resolve_device
from device_manager import device_manager
from config import config, ConfigValidationError, DEFAULT_OVERLAY_VR_LAUNCHER_SETTINGS
from model import model, SETUP_LAUNCHED, SETUP_DOWNLOAD_FAILED, SETUP_VERIFY_FAILED
from utils import removeLog, printLog, errorLogging, isConnectedNetwork, isValidIpAddress, isValidPort, isValidWebSocketHost, isAvailableWebSocketServer
from errors import TranscriptionStartError, ErrorCode, OcrStartError, VRCTError
from models.transcription.transcription_openai_compatible import TRANSCRIPTION_MODEL_KEYWORDS, TRANSCRIPTION_API_ENGINES
from models.translation.translation_providers import TRANSLATION_PROVIDER_REGISTRY, CONNECTION_PROVIDER_REGISTRY
from models.translation.translation_utils import ctranslate2_weights, isNonCommercialCTranslate2Weight, MissingCTranslate2Tokenizer
from models.legacy_model_consent import legacyModelCatalog, recordLegacyConsent, consentedLegacyRequest
from models.legacy_model_downloads import LegacyDownloads
from uuid import uuid4
from models.message_pipeline import MessageDirectionSpec, MIC_MESSAGE_SPEC, SPEAKER_MESSAGE_SPEC, CHAT_MESSAGE_SPEC, OCR_MESSAGE_SPEC
from models.message_pipeline import REALTIME_MIC_SPEC, REALTIME_SPEAKER_SPEC
from models.message_snapshot import MessageSnapshot, language_payload
from models.transcription.utterance_diagnostics import SLOW_MS, utterance_diagnostics
from models.transcription.realtime_settings import (
    normalize_settings as normalize_realtime_settings, session_options, endpoint_dict,
    realtime_endpoint, language_supported, SessionOptions)
from models.transcription.realtime_session import RealtimeSession
from models.transcription.realtime_delivery import RealtimeDelivery
from models.transcription.capture_pipewire import enumerate_endpoints, default_endpoint
from models.transcription.speechcpp_asr import SpeechCppASR
from models.transcription.asr_vocabulary import merged_terms
from models.transcription.transcription_languages import transcription_lang
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.tts.converted_router import ConvertedSpeechRouter
from models.io_flow import describe as describe_io_flow
from models.io_trace import IoTraces
from models.tts.speechcpp_tts import SpeechError, SpeechCppTTS
from models.speech_server.runtime import START_TIMEOUT as SPEECH_START_TIMEOUT, SpeechServers, list_gpus
from models.model_downloads.manager import Downloads
from models.model_downloads.catalog import SPEECH_FIELDS as SPEECH_DOWNLOAD_FIELDS
from models.model_downloads.hardware import HardwareProbe
from models.voice_conversion.runtime_setup import RuntimeSetup
from models.ocr import ocr_capture, ocr_chatbox_detector, ocr_languages, ocr_models
from models.ocr import ocr_engine_rapidocr as ocr_engine
from models.speech_server.settings import PROFILES, normalize_settings as normalize_speech_server_settings, start_options as speech_start_options
from models.tts.message_hook import chat_event, microphone_event
from models.audio_routing.audio_router import enumerate_outputs
from models.audio_routing.devices_windows import carries_own_voice, same_output
from models.audio_routing.managed_route import VoiceRoute
from models.audio_routing.monitor_output import monitor_spec
from models.audio_routing.mute_state import MuteState
from models.audio_routing.pipewire_gate import PipeWireGate
from models.audio_routing.source_bridge import PIPEWIRE_MIC_HOST, enumerate_sources, microphone_names, parse_source
from models.voice_conversion.direct_voice import DirectVoice, create_converted_process
from models.voice_conversion.settings import DirectSettings, start_options
from models.overlay.overlay_tooltip import validate_tooltip
from models.overlay.overlay import PANEL_ANCHORS, computeVrLayout, clampPanelSize, mirrorHandPosition, vrPanelSupported

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# モデルダウンロード進捗の間引きしきい値。translation_utils.downloadFile /
# transcription_whisper.downloadFile は 2MB チャンクごとに progressBar を
# 呼ぶため、~2GB の重みで 900+ 回の logging バーストが発生する。
# CTranslate2 と Whisper が同時にダウンロードされると process.log の
# ハンドラロック競合で feedWatchdog が 35s 遅延するのを freeze_trace.log で
# 2026-08-20 に観測した。前回報告から MIN_DELTA 以上進んだ、または
# MIN_INTERVAL_SEC 以上経過した場合のみ forward する (0% / 100% は必ず送る)。
_DOWNLOAD_PROGRESS_MIN_DELTA = 0.01
_DOWNLOAD_PROGRESS_MIN_INTERVAL_SEC = 0.5

# config.OVERLAY_VR_PANEL_SETTINGS / OVERLAY_VR_LAUNCHER_SETTINGS は dict を丸ごと読み書きする。
# 掴み移動の保存 (オーバーレイのスレッド) と、不透明度・ランチャーの手の変更 (エンドポイント) が
# 重なると片方が消えるので、読み書きを直列にする
_VR_WINDOW_SETTINGS_LOCK = Lock()

# Only short OCR intent updates belong here; model loading/joins stay outside.
_OCR_CONTROL_LOCK = Lock()
_OSC_CONTROL_LOCK = RLock()
_LEGACY_DOWNLOAD_OWNER_LOCK = Lock()


def vrLayoutToJson(layout: dict) -> dict:
    """VR画面の並びを UI へ送る形 (リスト) にする。src-ui/views/vr/vr_layout.json と同じ形。"""
    result = {"atlas": list(layout["atlas"]), "regions": {name: list(rect) for name, rect in layout["regions"].items()}}
    if "tooltip_epoch" in layout:
        result["tooltip_epoch"] = layout["tooltip_epoch"]
    return result

# shutdown() が mic/speaker_lifecycle_lock を待つ上限。model.py の
# TRANSCRIPT_STOP_JOIN_TIMEOUT (15s) + PyAudio open の _MIC_OPEN_TIMEOUT_SEC
# (8s) など、ロック保持中に自然完了しうる最長の単発処理より余裕を持たせつつ、
# 万一ロックが本当に返ってこない場合でも終了処理自体を無期限に止めない。
_SHUTDOWN_LIFECYCLE_LOCK_TIMEOUT_SEC = 20.0

# 起動時の翻訳・音声認識エンジンの確認を待つ上限 (段階ごと)。ふだんは数秒で終わる
# (実機で 2.3 秒)。個々の要求の時間の上限は SDK ごとに違い、少しずつ応答を返し続ける
# サーバーではそれも効かないため、全体で区切る。間に合わなかったエンジンは使えない状態で起動する
_ENGINE_CHECK_BUDGET_SEC = 30.0

# shutdown() が OSC/WebSocket/OBS Browser Source/Overlay の各停止関数を
# 待つ上限(フェーズ4項目30)。いずれも自前でタイムアウト付きjoinを持つ設計
# (OSCは serve_forever(0.5) 化により概ね0.5秒以内、WebSocket/OBSは
# join(timeout=2.0)) だが、唯一 Overlay.shutdownOverlay() の
# thread_overlay.join() だけは現状無タイムアウトのまま(フェーズ4項目31で
# 対応予定)。ここで一律に境界を設けることで、万一そのいずれかが想定外に
# 詰まっても shutdown() 自体は無期限にハングしない(_stopLockedForShutdownと
# 同じ考え方)。タイムアウトした場合、対象スレッドはdaemonのまま走らせて
# 諦める(=リソースはプロセス終了が最終的に片付ける)。
_SHUTDOWN_SERVICE_STOP_TIMEOUT_SEC = 5.0

# TRANSLATION_PROVIDER_REGISTRY (フェーズ3項目17) 登録エンジンの
# 「認証/モデル一覧取得/モデル変更/クライアント更新」を model.py の
# どのメソッド"名"に委譲するかの対応表。エンジンを1つレジストリに追加する際、
# ここに4行足すだけで Controller._setTranslationEngineAuthKey 等の
# 共通実装から使えるようになる (model.py 自体の各メソッドはこれまで通り
# 個別に存在する — Translator ファサード層 (layer 1) は
# authenticationRegistryAuthKey 等で既にレジストリ駆動になっているが、
# model.py (layer 2) は薄い1行委譲のみで書き換える理由に乏しいため、
# この対応表で拾う形にした)。
#
# 値をメソッド"名" (str) にしているのは、既存テストが
# `@patch("controller.model")` で model シングルトンを丸ごとモックに
# 差し替える方式に依存しているため。呼び出し時に `getattr(model, name)`
# で毎回引き直すことで、モジュールロード時に実体の bound method を
# キャッシュしてしまい patch が効かなくなる事故を避ける。
_ENGINE_MODEL_BINDINGS = {
    "Plamo_API": {
        "authenticate": "authenticationTranslatorPlamoAuthKey",
        "get_model_list": "getTranslatorPlamoModelList",
        "set_model": "setTranslatorPlamoModel",
        "update_client": "updateTranslatorPlamoClient",
    },
    "Gemini_API": {
        "authenticate": "authenticationTranslatorGeminiAuthKey",
        "get_model_list": "getTranslatorGeminiModelList",
        "set_model": "setTranslatorGeminiModel",
        "update_client": "updateTranslatorGeminiClient",
    },
    "OpenAI_API": {
        "authenticate": "authenticationTranslatorOpenAIAuthKey",
        "get_model_list": "getTranslatorOpenAIModelList",
        "set_model": "setTranslatorOpenAIModel",
        "update_client": "updateTranslatorOpenAIClient",
    },
    "Groq_API": {
        "authenticate": "authenticationTranslatorGroqAuthKey",
        "get_model_list": "getTranslatorGroqModelList",
        "set_model": "setTranslatorGroqModel",
        "update_client": "updateTranslatorGroqClient",
    },
    "OpenRouter_API": {
        "authenticate": "authenticationTranslatorOpenRouterAuthKey",
        "get_model_list": "getTranslatorOpenRouterModelList",
        "set_model": "setTranslatorOpenRouterModel",
        "update_client": "updateTranslatorOpenRouterClient",
    },
    # CONNECTION_PROVIDER_REGISTRY (疎通確認型) 用。"authenticate" は
    # 「接続を確認する」呼び出しに読み替える (LMStudioはbase_url必須、
    # Ollamaは引数なし — 呼び出し時の connect_kwargs で吸収する)。
    "LMStudio": {
        "authenticate": "authenticationTranslatorLMStudio",
        "get_model_list": "getTranslatorLMStudioModelList",
        "set_model": "setTranslatorLMStudioModel",
        "update_client": "updateTranslatorLMStudioClient",
    },
    "Ollama": {
        "authenticate": "authenticationTranslatorOllama",
        "get_model_list": "getTranslatorOllamaModelList",
        "set_model": "setTranslatorOllamaModel",
        "update_client": "updateTranslatorOllamaClient",
    },
}


def _configValidationErrorResponse(error_code: ErrorCode):
    """設定値のディスクリプタ (config.py の ManagedProperty/ValidatedProperty)
    が拒否した場合に `ConfigValidationError` を捕まえ、`VRCTError` の
    エラーレスポンスへ変換するデコレータ (フェーズ3項目24)。

    対象は「`config.X = data` して結果を返すだけ」の単純なエンドポイント
    (例: `setUiLanguage`) — これまでは不正な値を渡されても、ディスクリプタが
    サイレントに値を無視し、変化していない旧値を 200 (成功) で返していた
    (`setUiLanguage(bad_value)` が「成功したが何も変わっていない」レスポンスに
    なる、という誤った契約)。デコレータを付けるだけで、関数本体は一切
    書き換えずに正しいエラー契約に直せる。

    副作用を伴う (例: `self.run(...)` で他のpushを行う) エンドポイントには
    使わないこと — 拒否時、副作用がどこまで実行された状態で例外に
    なったかをこのデコレータは関知しない。
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ConfigValidationError as e:
                # Restore the UI to the accepted value; rejected input may be
                # nonfinite and cannot be serialized in an IPC response.
                return VRCTError.create_error_response(error_code, data=getattr(config, e.attr_name, e.value))
        return wrapper
    return decorator


def _shouldEmitDownloadProgress(handler: Any, progress: float) -> bool:
    """DownloadCTranslate2 / DownloadWhisper の progressBar 用スロットル。

    handler は `_last_progress: float` と `_last_time: float` 属性を持つ
    インスタンス。100% 到達時は必ず True を返す (完了通知が抜けないよう)。
    """
    now = time.monotonic()
    if (
        progress >= 1.0
        or (progress - handler._last_progress) >= _DOWNLOAD_PROGRESS_MIN_DELTA
        or (now - handler._last_time) >= _DOWNLOAD_PROGRESS_MIN_INTERVAL_SEC
    ):
        handler._last_progress = progress
        handler._last_time = now
        return True
    return False


# config.py の値をそのまま返すだけの単純なgetterエンドポイント
# (フェーズ3項目23)。エンドポイントメソッド名 -> config属性名の対応表。
# 実際のメソッド生成・Controllerクラスへの登録は
# _registerSimpleConfigGetters() 参照 (ファイル末尾)。
_SIMPLE_CONFIG_GETTERS = {
    "getVersion": "VERSION",
    "getComputeMode": "COMPUTE_MODE",
    "getComputeDeviceList": "SELECTABLE_COMPUTE_DEVICE_LIST",
    "getSelectedTranslationComputeDevice": "SELECTED_TRANSLATION_COMPUTE_DEVICE",
    "getSelectableCtranslate2WeightTypeDict": "SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT",
    "getSelectedTranscriptionComputeDevice": "SELECTED_TRANSCRIPTION_COMPUTE_DEVICE",
    "getSelectedTabNo": "SELECTED_TAB_NO",
    "getSelectedTranslationEngines": "SELECTED_TRANSLATION_ENGINES",
    "getSelectedYourLanguages": "SELECTED_YOUR_LANGUAGES",
    "getSelectedTargetLanguages": "SELECTED_TARGET_LANGUAGES",
    "getSelectedTranscriptionEngine": "SELECTED_TRANSCRIPTION_ENGINE",
    "getGroqWhisperModelList": "SELECTABLE_GROQ_WHISPER_MODEL_LIST",
    "getGroqWhisperModel": "SELECTED_GROQ_WHISPER_MODEL",
    "getOpenAIWhisperModelList": "SELECTABLE_OPENAI_WHISPER_MODEL_LIST",
    "getOpenAIWhisperModel": "SELECTED_OPENAI_WHISPER_MODEL",
    "getCustomWhisperURL": "TRANSCRIPTION_CUSTOM_URL",
    "getCustomWhisperModelList": "SELECTABLE_CUSTOM_WHISPER_MODEL_LIST",
    "getCustomWhisperModel": "SELECTED_CUSTOM_WHISPER_MODEL",
    "getDeepgramModelList": "SELECTABLE_DEEPGRAM_MODEL_LIST",
    "getDeepgramModel": "SELECTED_DEEPGRAM_MODEL",
    "getSelectableReleaseChannels": "SELECTABLE_RELEASE_CHANNEL_LIST",
    "getSelectedReleaseChannel": "SELECTED_RELEASE_CHANNEL",
    "getConvertMessageToRomaji": "CONVERT_MESSAGE_TO_ROMAJI",
    "getConvertMessageToHiragana": "CONVERT_MESSAGE_TO_HIRAGANA",
    "getMainWindowSidebarCompactMode": "MAIN_WINDOW_SIDEBAR_COMPACT_MODE",
    "getEnableForeground": "ENABLE_FOREGROUND",
    "getTransparency": "TRANSPARENCY",
    "getUiScaling": "UI_SCALING",
    "getTextboxUiScaling": "TEXTBOX_UI_SCALING",
    "getMessageBoxRatio": "MESSAGE_BOX_RATIO",
    "getSendMessageButtonType": "SEND_MESSAGE_BUTTON_TYPE",
    "getShowResendButton": "SHOW_RESEND_BUTTON",
    "getFontFamily": "FONT_FAMILY",
    "getUiLanguage": "UI_LANGUAGE",
    "getMainWindowGeometry": "MAIN_WINDOW_GEOMETRY",
    "getAutoMicSelect": "AUTO_MIC_SELECT",
    "getSelectedMicHost": "SELECTED_MIC_HOST",
    "getSelectedMicDevice": "SELECTED_MIC_DEVICE",
    "getMicThreshold": "MIC_THRESHOLD",
    "getMicAutomaticThreshold": "MIC_AUTOMATIC_THRESHOLD",
    "getMicRecordTimeout": "MIC_RECORD_TIMEOUT",
    "getMicPhraseTimeout": "MIC_PHRASE_TIMEOUT",
    "getMicMaxPhrases": "MIC_MAX_PHRASES",
    "getMicWordFilter": "MIC_WORD_FILTER",
    "getMicAvgLogprob": "MIC_AVG_LOGPROB",
    "getMicNoSpeechProb": "MIC_NO_SPEECH_PROB",
    "getMicVadFilter": "MIC_ENABLE_VAD",
    "getAutoSpeakerSelect": "AUTO_SPEAKER_SELECT",
    "getSelectedSpeakerDevice": "SELECTED_SPEAKER_DEVICE",
    "getSpeakerThreshold": "SPEAKER_THRESHOLD",
    "getSpeakerAutomaticThreshold": "SPEAKER_AUTOMATIC_THRESHOLD",
    "getSpeakerRecordTimeout": "SPEAKER_RECORD_TIMEOUT",
    "getSpeakerPhraseTimeout": "SPEAKER_PHRASE_TIMEOUT",
    "getSpeakerMaxPhrases": "SPEAKER_MAX_PHRASES",
    "getHotkeys": "HOTKEYS",
    "getSpeakerAvgLogprob": "SPEAKER_AVG_LOGPROB",
    "getSpeakerNoSpeechProb": "SPEAKER_NO_SPEECH_PROB",
    "getSpeakerVadFilter": "SPEAKER_ENABLE_VAD",
    "getOscIpAddress": "OSC_IP_ADDRESS",
    "getOscPort": "OSC_PORT",
    "getNotificationVrcSfx": "NOTIFICATION_VRC_SFX",
    "getTranslatorLMStudioURL": "LMSTUDIO_URL",
    "getOpenAICompatibleURL": "OPENAI_COMPATIBLE_URL",
    "getOpenAICompatibleModelList": "SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST",
    "getOpenAICompatibleModel": "SELECTED_OPENAI_COMPATIBLE_MODEL",
    "getCtranslate2WeightType": "CTRANSLATE2_WEIGHT_TYPE",
    "getSelectedTranslationComputeType": "SELECTED_TRANSLATION_COMPUTE_TYPE",
    "getWhisperWeightType": "WHISPER_WEIGHT_TYPE",
    "getSelectedTranscriptionComputeType": "SELECTED_TRANSCRIPTION_COMPUTE_TYPE",
    "getSendMessageFormatParts": "SEND_MESSAGE_FORMAT_PARTS",
    "getReceivedMessageFormatParts": "RECEIVED_MESSAGE_FORMAT_PARTS",
    "getAutoClearMessageBox": "AUTO_CLEAR_MESSAGE_BOX",
    "getSendOnlyTranslatedMessages": "SEND_ONLY_TRANSLATED_MESSAGES",
    "getOverlaySmallLog": "OVERLAY_SMALL_LOG",
    "getOverlaySmallLogSettings": "OVERLAY_SMALL_LOG_SETTINGS",
    "getOverlayLargeLog": "OVERLAY_LARGE_LOG",
    "getOverlayVrPanel": "OVERLAY_VR_PANEL",
    "getOverlayVrPanelLocked": "OVERLAY_VR_PANEL_LOCKED",
    "getOverlayVrPanelFontSize": "OVERLAY_VR_PANEL_FONT_SIZE",
    "getOverlayVrLauncherAutoHide": "OVERLAY_VR_LAUNCHER_AUTO_HIDE",
    "getOverlayVrTooltip": "OVERLAY_VR_TOOLTIP",
    "getOverlayLargeLogSettings": "OVERLAY_LARGE_LOG_SETTINGS",
    "getOverlayDesktop": "OVERLAY_DESKTOP",
    "getOverlayDesktopSettings": "OVERLAY_DESKTOP_SETTINGS",
    "getIoFlowOverlaySettings": "IO_FLOW_OVERLAY_SETTINGS",
    "getOverlayShowOnlyTranslatedMessages": "OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES",
    "getSendMessageToVrc": "SEND_MESSAGE_TO_VRC",
    "getSendReceivedMessageToVrc": "SEND_RECEIVED_MESSAGE_TO_VRC",
    "getLoggerFeature": "LOGGER_FEATURE",
    "getVrcMicMuteSync": "VRC_MIC_MUTE_SYNC",
    "getTelemetry": "ENABLE_TELEMETRY",
    "getAutoDownloadModels": "AUTO_DOWNLOAD_MODELS",
    "getWebSocketHost": "WEBSOCKET_HOST",
    "getWebSocketPort": "WEBSOCKET_PORT",
    "getWebSocketServer": "WEBSOCKET_SERVER",
    "getObsBrowserSource": "OBS_BROWSER_SOURCE",
    "getObsBrowserSourcePort": "OBS_BROWSER_SOURCE_PORT",
    "getObsBrowserSourceMaxMessages": "OBS_BROWSER_SOURCE_MAX_MESSAGES",
    "getObsBrowserSourceDisplayDuration": "OBS_BROWSER_SOURCE_DISPLAY_DURATION",
    "getObsBrowserSourceFadeoutDuration": "OBS_BROWSER_SOURCE_FADEOUT_DURATION",
    "getObsBrowserSourceFontSize": "OBS_BROWSER_SOURCE_FONT_SIZE",
    "getObsBrowserSourceFontColor": "OBS_BROWSER_SOURCE_FONT_COLOR",
    "getObsBrowserSourceFontOutlineThickness": "OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS",
    "getObsBrowserSourceFontOutlineColor": "OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR",
    "getClipboard": "ENABLE_CLIPBOARD",
    "getSelectableOcrSourceLanguages": "SELECTABLE_OCR_SOURCE_LANGUAGE_LIST",
    "getOcrSourceLanguage": "OCR_SOURCE_LANGUAGE",
    "getOcrWindowTitle": "OCR_WINDOW_TITLE",
    "getOcrPollIntervalMs": "OCR_POLL_INTERVAL_MS",
    "getOcrMinConfidence": "OCR_MIN_CONFIDENCE",
    "getOcrBubbleMinTextLength": "OCR_BUBBLE_MIN_TEXT_LENGTH",
    "getOcrCaptureRegion": "OCR_CAPTURE_REGION",
    "getOcrVrCaptureRegion": "OCR_VR_CAPTURE_REGION",
    "getOcrChatboxFilter": "OCR_CHATBOX_FILTER",
    "getOcrUseChatboxDetector": "OCR_USE_CHATBOX_DETECTOR",
    "getOcrPortalRestoreToken": "OCR_PORTAL_RESTORE_TOKEN",
}

# 起動時のエンジンの確認で、選んだモデルの設定とクライアントの生成に使う Model のメソッド名 (モデル一覧を持つエンジン)
_ENGINE_MODEL_CLIENT_CALLS = {
    "Plamo_API": ("setTranslatorPlamoModel", "updateTranslatorPlamoClient"),
    "Gemini_API": ("setTranslatorGeminiModel", "updateTranslatorGeminiClient"),
    "OpenAI_API": ("setTranslatorOpenAIModel", "updateTranslatorOpenAIClient"),
    "Groq_API": ("setTranslatorGroqModel", "updateTranslatorGroqClient"),
    "OpenRouter_API": ("setTranslatorOpenRouterModel", "updateTranslatorOpenRouterClient"),
    "LMStudio": ("setTranslatorLMStudioModel", "updateTranslatorLMStudioClient"),
    "OpenAI_Compatible": ("setTranslatorOpenAICompatibleModel", "updateTranslatorOpenAICompatibleClient"),
    "Ollama": ("setTranslatorOllamaModel", "updateTranslatorOllamaClient"),
}


def _runEngineChecks(check, engines: list, label: str) -> dict:
    """エンジンの確認を同時に走らせ、全体で _ENGINE_CHECK_BUDGET_SEC 秒まで待つ。

    `check(engine)` は `(engine, *結果)` を返す。返り値は {engine: 結果のタプル}。
    間に合わなかったエンジンは含めない (呼び出し元が使えない状態にする)。待ちきれなかった
    確認の通信クライアントを閉じ、遅れた結果を捨てて起動を進める。そのスレッドは config に書かない。
    """
    results = {}
    executor = ThreadPoolExecutor(max_workers=max(1, len(engines)))
    scopes = {engine: DiscoveryScope(_ENGINE_CHECK_BUDGET_SEC) for engine in engines}
    def checked(engine):
        with discovery_scope(scopes[engine]):
            return check(engine)
    futures = {executor.submit(checked, engine): engine for engine in engines}
    try:
        for future in as_completed(futures, timeout=_ENGINE_CHECK_BUDGET_SEC):
            try:
                engine, *rest = future.result()
            except TimeoutError:
                continue
            results[engine] = tuple(rest)
    except FuturesTimeout:
        late = [engine for future, engine in futures.items() if not future.done()]
        printLog(f"{label} checks did not finish in {_ENGINE_CHECK_BUDGET_SEC:.0f}s; starting without them", {"engines": late})
    finally:
        for scope in scopes.values():
            scope.close()
        executor.shutdown(wait=False, cancel_futures=True)
    return results


class Controller:
    def __init__(self, config_override=None, model_override=None) -> None:
        """
        `config_override`/`model_override` はデフォルト引数注入
        (フェーズ3項目22)。既定 (未指定) では、このモジュールが `from
        config import config` / `from model import model` した
        シングルトンをその場で (呼び出し時に) 参照するため、既存の全呼び出し
        (`Controller()`) は無変更で動き、`@patch("controller.model")` の
        ようなモジュール属性差し替えにも追従する。

        NOTE: `def __init__(self, config=config, model=model)` のように
        引数名をモジュールレベル名と揃えて既定値にする書き方は避けた —
        デフォルト値は関数定義時 (＝モジュール import 時) に1回だけ評価
        されるため、後から `@patch("controller.model")` で
        `controller.model` を差し替えても、既に固定された既定値には反映
        されない (実際にこれで既存テストを壊しかけた)。`config`/`model` を
        関数本体側で毎回参照する今の形なら、呼び出し時点の最新の値を拾える。

        テストや将来の DI 移行 (項目23) のために差し替えられるよう
        `self._config`/`self._model` として保持するが、これはコンストラクタ
        自体の足場に留まる: このクラスの残り数千行は引き続き裸のモジュール
        レベル `config`/`model` を直接参照しており、今回それらを
        `self._config`/`self._model` 経由に書き換えることはしていない
        (影響範囲が大きすぎるため項目23の対象)。現時点で `self._model` を
        実際に使っているのは `_bootstrapModel()` (下記) のみ。
        """
        self._config = config_override if config_override is not None else config
        self._model = model_override if model_override is not None else model
        saved_servers = getattr(self._config, "SPEECH_SERVER_SETTINGS", {})
        self._speech_settings = normalize_speech_server_settings(saved_servers if isinstance(saved_servers, dict) else {})
        self._speech_settings_lock = Lock()
        self.speech_servers = SpeechServers(on_end=self._speechServerEnded)
        # TTS servers the main toggle started, as {profile: server generation}.
        # The generation names one run, so a server the user starts from
        # Settings is never adopted or stopped by the toggle.
        self._tts_owner_lock = Lock()
        self._tts_owned = {}
        self._tts_released = {}
        self._tts_ended = {}
        self._tts_attempts = set()
        self._tts_waiting = 0
        voice_settings = getattr(self._config, "VOICE_SETTINGS", {})
        voice_settings = voice_settings if isinstance(voice_settings, dict) else {}
        if voice_settings.get("routing") == "managed" and not sys.platform.startswith("linux"):
            # Carried over from Linux. No such route exists here, and its mute could
            # never be confirmed, so the setting could not be left afterwards.
            voice_settings = {**voice_settings, "routing": "external", "mode": "off", "mic_mode": "off"}
            self._config.VOICE_SETTINGS = voice_settings
        self.voice_events = VoiceEventBus(VoiceSettings.from_dict(voice_settings),
                                          resolve_server=self._ttsSpeechServer, enabled=False,
                                          on_monitor_error=self._voiceMonitorFailed)
        config_path = getattr(self._config, '_PATH_CONFIG', 'config.json')
        if not isinstance(config_path, (str, Path)):
            config_path = 'config.json'
        self.model_downloads = Downloads(Path(config_path).absolute().parent / 'downloaded_models')
        self.vc_runtimes = RuntimeSetup(Path(config_path).absolute().parent / 'vc_runtimes')
        self.legacy_downloads = LegacyDownloads()
        self.model_hardware = HardwareProbe()
        self.direct_voice = DirectVoice(converted_factory=create_converted_process)
        self.voice_events.converted_router = ConvertedSpeechRouter(self.direct_voice)
        # The flow panel: stage times of the user's own messages, and the engine converting the voice.
        self.io_traces = IoTraces(self._ioTraceEmit)
        self.voice_events.on_first_audio = self._ioSpeechStarted
        self._direct_engine = None
        self.voice_route = VoiceRoute(self.voice_events, gate=PipeWireGate(),
                                     store=MuteState(Path(config_path).with_name('voice_mute_state.json')),
                                     on_muted=self.direct_voice.set_monitor_muted)
        self.voice_route.configure(self.voice_events.settings.routing == 'managed',
            suppress_direct=self._gateSuppressesDirect(self.voice_events.settings))
        self._applyDirectPolicy(self.voice_events.settings)
        self._voice_settings_lock = Lock()
        self._language_settings_lock = RLock()
        direct = getattr(self._config, 'DIRECT_VOICE_SETTINGS', {})
        self._direct_settings = DirectSettings.from_dict(direct if isinstance(direct, dict) else {})
        self._direct_voice_closed = False
        choices = getattr(self._config, "REALTIME_ASR_SETTINGS", {})
        self._initRealtimeASR(choices if isinstance(choices, dict) else {})
        # typed attributes to satisfy static type checkers
        self.init_mapping: dict = {}
        self.run_mapping: dict = {}
        # initialize with a no-op callable so callers can safely call self.run
        def _noop_run(status: int, endpoint: str, payload: Any = None) -> None:
            return None
        self.run: Callable[[int, str, Any], None] = _noop_run
        # マイク/スピーカーそれぞれの文字起こし・エナジー計測の start/stop を
        # 直列化するロック。mic/speaker で分離しているのは、片方の重い
        # open/close 中にもう片方が待たされないようにするため。
        # 非再入の Lock を使う。VRAM エラー発生時に start*Message の except節
        # が同一スレッド上で停止処理を行う必要があるが、そこでは
        # _stopTranscriptionSendMessageLocked のようなロック不要の内部版を
        # 呼ぶことで再入を避けている (公開の stop*Message は自前でロックを
        # 取るため、start*Message の中から呼ぶとデッドロックする)。
        self.mic_lifecycle_lock = RLock()
        self.speaker_lifecycle_lock = RLock()

    def getModelDownloadCatalog(self, *args, **kwargs):
        return {'status': 200, 'result': {**self.model_downloads.catalog(), 'legacy_models': legacyModelCatalog()}}

    def getModelDownloadHardware(self, *args, **kwargs):
        return {'status': 200, 'result': self.model_hardware.state()}

    def refreshModelDownloadHardware(self, data=None):
        if data not in (None, {}):
            return {'status': 400, 'result': {'error_code': 'download_request_invalid'}}
        try:
            return {'status': 200, 'result': self.model_hardware.refresh()}
        except ValueError:
            return {'status': 409, 'result': {'error_code': 'hardware_closed'}}

    def getModelDownloadState(self, *args, **kwargs):
        return {'status': 200, 'result': self.model_downloads.state()}

    @staticmethod
    def _modelDownloadFailure(error):
        conflict = {'download_busy', 'downloads_closed', 'stale_job', 'download_not_ready',
                    'settings_changed', 'model_target_busy'}
        return {'status': 409 if str(error) in conflict else 400,
                'result': {'error_code': str(error)}}

    @staticmethod
    def _modelDownloadRequest(data, apply=False):
        required = {'id', 'job_id', 'expected'} if apply else {'id', 'job_id'}
        if (not isinstance(data, dict) or set(data) != required
                or any(not isinstance(data[key], str) or not data[key] for key in ('id', 'job_id'))):
            raise ValueError('download_request_invalid')

    def getVcRuntimeCatalog(self, *args, **kwargs):
        return {'status': 200, 'result': self.vc_runtimes.catalog()}

    def getVcRuntimeState(self, *args, **kwargs):
        return {'status': 200, 'result': self.vc_runtimes.state()}

    @staticmethod
    def _vcRuntimeFailure(error):
        conflict = {'vc_runtime_busy', 'vc_runtime_closed', 'stale_job'}
        return {'status': 409 if str(error) in conflict else 400, 'result': {'error_code': str(error)}}

    def startVcRuntimeSetup(self, data, *args, **kwargs):
        try:
            return {'status': 200, 'result': self.vc_runtimes.start(data)}
        except ValueError as error:
            return self._vcRuntimeFailure(error)

    def cancelVcRuntimeSetup(self, data, *args, **kwargs):
        try:
            self._modelDownloadRequest(data)
            return {'status': 200, 'result': self.vc_runtimes.cancel(data['id'], data['job_id'])}
        except ValueError as error:
            return self._vcRuntimeFailure(error)

    def startModelDownload(self, data, *args, **kwargs):
        try:
            return {'status': 200, 'result': self.model_downloads.start(data)}
        except ValueError as error:
            return self._modelDownloadFailure(error)

    def cancelModelDownload(self, data, *args, **kwargs):
        try:
            self._modelDownloadRequest(data)
            return {'status': 200, 'result': self.model_downloads.cancel(data['id'], data['job_id'])}
        except ValueError as error:
            return self._modelDownloadFailure(error)

    def applyModelDownload(self, data, *args, **kwargs):
        try:
            self._modelDownloadRequest(data, apply=True)
            def apply(entry, paths):
                expected = data['expected']
                if entry.target == 'ocr':
                    # Chat reading finds verified downloads by catalog id; there is
                    # no path setting to change (models/ocr/ocr_models.py).
                    if expected not in ({}, None):
                        raise ValueError('download_request_invalid')
                    return
                keys = {'model', 'index'} if entry.target == 'rvc' else {'model'}
                if not isinstance(expected, dict) or set(expected) != keys or any(not isinstance(v, str) for v in expected.values()):
                    raise ValueError('download_request_invalid')
                if entry.target == 'rvc':
                    with self._voice_settings_lock:
                        state = self.direct_voice.health()
                        if self._direct_voice_closed or any(state.get(k) for k in ('requested', 'pending', 'stopping')):
                            raise ValueError('model_target_busy')
                        settings = self._direct_settings.to_dict()
                        if any(settings['rvc_' + k] != expected[k] for k in keys):
                            raise ValueError('settings_changed')
                        settings.update(rvc_model=paths['model'], rvc_index=paths.get('index', ''))
                        updated = DirectSettings.from_dict(settings)
                        self.direct_voice.stop()  # Invalidate queued starts, as in the normal settings setter.
                        self._config.DIRECT_VOICE_SETTINGS = updated.to_dict()
                        self._direct_settings = updated
                else:
                    # A VAD file goes to the asr profile's vad_model; expected names that field's value.
                    profile, field = SPEECH_DOWNLOAD_FIELDS[entry.target]
                    with self._speech_settings_lock:
                        if self.speech_servers.state()[profile]['state'] not in ('stopped', 'failed'):
                            raise ValueError('model_target_busy')
                        settings = copy.deepcopy(self._speech_settings)
                        if settings['profiles'][profile][field] != expected['model']:
                            raise ValueError('settings_changed')
                        settings['profiles'][profile][field] = paths['model']
                        self._config.SPEECH_SERVER_SETTINGS = settings
                        self._speech_settings = settings
            return {'status': 200, 'result': self.model_downloads.apply(data['id'], data['job_id'], apply)}
        except ValueError as error:
            return self._modelDownloadFailure(error)
        except OSError:
            return {'status': 400, 'result': {'error_code': 'download_apply_failed'}}

    def getSpeechServerSettings(self, *args, **kwargs):
        with self._speech_settings_lock:
            return {"status": 200, "result": copy.deepcopy(self._speech_settings)}

    def setSpeechServerSettings(self, data, *args, **kwargs):
        try:
            settings = normalize_speech_server_settings(data)
        except ValueError:
            return {"status": 400, "result": {"error_code": "speech_server_settings_invalid"}}
        with self._speech_settings_lock:
            self._config.SPEECH_SERVER_SETTINGS = settings
            self._speech_settings = settings
        return self.getSpeechServerSettings()

    def getSpeechServerDevices(self, *args, **kwargs):
        return {"status": 200, "result": {"devices": list_gpus()}}

    def getSpeechServerState(self, *args, **kwargs):
        return {"status": 200, "result": self.speech_servers.state()}

    def _ttsSpeechServer(self, profile):
        try:
            return self.speech_servers.binding(profile)
        except RuntimeError:
            # Preserve the safe public code instead of reporting an output
            # device error for a deliberately stopped inference server.
            raise SpeechError("speech_server_not_ready") from None

    @staticmethod
    def _speechRequest(data, *, start=False):
        keys = {"profile", "generation"} if start else {"profile"}
        if not isinstance(data, dict) or set(data) != keys or data.get("profile") not in PROFILES:
            raise ValueError("speech_server_request_invalid")
        if start and (type(data["generation"]) is not int or data["generation"] < 0):
            raise ValueError("speech_server_request_invalid")
        return data["profile"]

    def startSpeechServer(self, data, *args, **kwargs):
        try:
            profile = self._speechRequest(data, start=True)
            # File validation runs outside the fast-stop locks. The hub checks
            # the original generation after it, so Stop cannot be undone.
            options = speech_start_options(self.getSpeechServerSettings()["result"], profile)
        except ValueError as exc:
            return {"status": 400, "result": {"error_code": str(exc)}}
        try:
            self.speech_servers.start(profile, options, data["generation"])
        except RuntimeError as exc:
            code = str(exc)
            if code not in ("speech_server_closed", "speech_server_stale_start", "speech_server_busy"):
                code = "speech_server_start_failed"
            return {"status": 409, "result": {"error_code": code}}
        return self.getSpeechServerState()

    def _enableSpeechServerTts(self, roles, generation):
        """Commit ON after rechecking bundled availability under the end lock."""
        with self._tts_owner_lock:
            settings = self.voice_events.settings
            try:
                for role in roles:
                    if getattr(settings, role + '_server') == 'bundled':
                        self.speech_servers.binding(role)
            except RuntimeError:
                return 'speech_server_not_ready'
            # A terminal callback takes this lock too, so it cannot miss the
            # dependency between the final readiness check and enabling TTS.
            if not self.voice_events.set_enabled(True, expected_generation=generation):
                return 'tts_state_changed'
        return None

    def _speechTtsDependency(self, profile, run):
        """Snapshot the TTS epoch currently using this exact bundled run."""
        while True:
            state = self.voice_events.status()
            if (not state['tts_enabled'] or state['closed']
                    or self.speech_servers.current_run(profile) != run
                    or getattr(self.voice_events.settings, profile + '_server') != 'bundled'):
                return None
            # Saves/language changes can alter the selected roles while TTS
            # stays on. Stop/Mute can advance its epoch without ending it.
            code, roles = self._ttsRolesLocked(state['tts_generation'], allow_muted=True)
            if code == 'tts_state_changed':
                continue
            return state['tts_generation'] if code is None and profile in roles else None

    def _speechServerEnded(self, profile, run=None):
        # Called after releasing hub locks, including on natural child failure.
        if profile in ("japanese", "multilingual"):
            with self._tts_owner_lock:
                if run is None or run <= self._tts_ended.get(profile, -1):
                    return
                self._tts_ended[profile] = run
                if self._tts_released.get(profile) == run:
                    del self._tts_released[profile]
                    return  # The end of a run the TTS toggle's own OFF stopped.
                while True:
                    generation = self._speechTtsDependency(profile, run)
                    if generation is None:
                        return
                    # Settings/Stop/Mute can change the epoch without this lock.
                    # Invalidate only the session whose dependency we checked.
                    if self.voice_events.set_enabled(False, expected_generation=generation):
                        break
                owned = dict(self._tts_owned)
            # TTS is off now, so servers the main toggle started for it go too.
            # A waiting ON is not cancelled here: it reports this failure itself.
            self._releaseTtsServers(only=owned)
        elif profile == "asr":
            with self._realtime_lock:
                affected = []
                for source in ("mic", "speaker"):
                    if (run is not None and self._realtime_requested[source]
                            and self._realtime_server_runs[source] == (self._realtime_generation[source], run)):
                        affected.append(source)
                        self._invalidateRealtimeLocked(source)
                row = self.speech_servers.state()["asr"] if affected else None
            if affected:
                # A crash is worth a notice; a Stop from Settings is the user's own.
                reason = (row.get("error_code") or "speech_server_start_failed") if row["state"] == "failed" else None
                for source in affected:
                    self._publishRealtimeToggle(source, reason)

    def stopSpeechServer(self, data, *args, **kwargs):
        try:
            profile = self._speechRequest(data)
        except ValueError:
            return {"status": 400, "result": {"error_code": "speech_server_request_invalid"}}
        if profile == "asr":
            self._refuseResumeAfterAsrStop()
        # Revoke endpoint availability first; new work cannot bind between
        # invalidating clients and the Stop signal. Neither operation joins.
        self.speech_servers.stop(profile, on_stop=self._speechServerEnded)
        return self.getSpeechServerState()

    def _refuseResumeAfterAsrStop(self):
        """利用者が設定画面で内蔵の音声認識サーバーを止めた。閉じたときに入力を再開しない。

        設定画面を開くと、UI はマイクと聞き取りを一時停止し、閉じるときに元へ戻す。入力を戻すと、
        メインのスイッチは内蔵サーバーを自分で起動する。そのため、止めた 0.25 秒後に設定画面を
        閉じると、サーバーが 4 秒ほどで起動し直し、マイクの認識が再開していた。読み上げでは、
        設定から止めたら TTS もオフにしている。入力も同じ扱いにする。
        """
        settings = getattr(self, "_realtime_settings", None) or {}
        if settings.get("server") != "bundled":
            return  # 入力は別のサーバーを使っている。内蔵サーバーを止めても関係がない。
        with self._realtime_lock:
            self._realtime_resume_refused |= self._realtime_settings_paused

    def _noteRealtimePause(self, source, data):
        """入力をオフにした理由を覚える。設定画面による一時停止でなければ、利用者が自分で切った。"""
        paused = isinstance(data, dict) and data.get("reason") == "settings_pause"
        with self._realtime_lock:
            (self._realtime_settings_paused.add if paused else self._realtime_settings_paused.discard)(source)
            self._realtime_resume_refused.discard(source)

    def _initRealtimeASR(self, choices):
        self._realtime_settings = normalize_realtime_settings(choices)
        self._realtime_lock = Lock()
        self._realtime_settings_lock = Lock()
        self._realtime_generation = {source: 0 for source in ("mic", "speaker")}
        self._realtime_requested = dict.fromkeys(self._realtime_generation, False)
        self._realtime_owners = dict.fromkeys(self._realtime_generation)
        self._realtime_server_runs = dict.fromkeys(self._realtime_generation)
        self._realtime_errors = dict.fromkeys(self._realtime_generation)
        self._realtime_closed = False
        # Linux main toggles: the state last shown for each source, a bundled
        # ASR server a toggle started (its generation), and toggles starting.
        self._realtime_toggle_lock = Lock()
        self._realtime_toggle_shown = dict.fromkeys(self._realtime_generation, False)
        # 設定画面を開いている間だけ止めている入力と、その間に利用者が内蔵の音声認識サーバーを
        # 止めたために、設定画面を閉じても再開しない入力。
        self._realtime_settings_paused = set()
        self._realtime_resume_refused = set()
        self._asr_server_owned = None
        self._asr_toggle_starting = 0

    @staticmethod
    def _realtimeSource(data):
        if not isinstance(data, dict) or data.get("source") not in ("mic", "speaker"):
            raise ValueError("realtime_source_invalid")
        return data["source"]

    @staticmethod
    def _realtimeLanguage(code):
        # Translator and overlay APIs take the existing display names, whereas
        # speech.cpp takes language codes. Prefer an exact locale when present.
        for engine in ("Google", "Whisper"):
            for name, locales in transcription_lang.items():
                if any(row.get(engine, "").lower() == code.lower() for row in locales.values()):
                    return name
        raise ValueError("realtime_translation_language_unsupported")

    def getRealtimeASRSettings(self, *args, **kwargs):
        with self._realtime_lock:
            return {"status": 200, "result": copy.deepcopy(self._realtime_settings)}

    def _invalidateRealtimeLocked(self, source):
        self._realtime_generation[source] += 1
        self._realtime_requested[source] = False
        self._realtime_server_runs[source] = None
        if source == "mic":
            self._cancelMicVoice()
        owner = self._realtime_owners[source]
        if owner is not None:
            owner[1].request_stop()

    def setRealtimeASRSettings(self, data, *args, **kwargs):
        try:
            settings = normalize_realtime_settings(data)
        except ValueError:
            return {"status": 400, "result": {"error_code": "realtime_settings_invalid"}}
        with self._realtime_settings_lock:
            with self._realtime_lock:
                old = self._realtime_settings
                shared_changed = any(settings[key] != old[key] for key in ("server", "base_url", "model", "vocabulary"))
                for source in ("mic", "speaker"):
                    if shared_changed or settings[source] != old[source]:
                        self._invalidateRealtimeLocked(source)
                self._realtime_settings = settings
            # Disk persistence never holds the fast-stop lock.
            config.REALTIME_ASR_SETTINGS = settings
        for source in ("mic", "speaker"):
            self._publishRealtimeToggle(source)
        return self.getRealtimeASRSettings()

    def getRealtimeASREndpoints(self, data, *args, **kwargs):
        try:
            source = self._realtimeSource(data)
        except ValueError:
            return {"status": 400, "result": {"error_code": "realtime_source_invalid"}}
        if sys.platform not in ("linux", "win32"):
            return {"status": 200, "result": {"source": source, "endpoints": [], "error_code": "realtime_platform_unsupported"}}
        try:
            rows = [{"endpoint": endpoint_dict(row["endpoint"]), "label": row["label"]}
                    for row in enumerate_endpoints(source)]
            return {"status": 200, "result": {"source": source, "endpoints": rows, "error_code": None}}
        except Exception:
            return {"status": 200, "result": {"source": source, "endpoints": [], "error_code": "realtime_graph_unavailable"}}

    def getRealtimeASRModels(self, *args, **kwargs):
        settings = self.getRealtimeASRSettings()["result"]
        result = dict(server=settings["server"], configured_url=settings["base_url"],
                      base_url=settings["base_url"], server_generation=None, models=[], error_code=None)
        if settings["server"] == "bundled":
            # Identify the server incarnation even when the OS reuses a port.
            result["server_generation"] = self.speech_servers.state()["asr"]["generation"]
            try:
                result["base_url"] = self.speech_servers.binding("asr")
            except RuntimeError:
                result.update(base_url=None, error_code="speech_server_not_ready")
                return {"status": 200, "result": result}
        try:
            models = SpeechCppASR(result["base_url"], timeout=5).recognizers()
            result["models"] = [asdict(row) for row in models]
        except Exception:
            result["error_code"] = "realtime_models_unavailable"
        return {"status": 200, "result": result}

    def getRealtimeASRState(self, *args, **kwargs):
        with self._realtime_lock:
            result = {}
            for source in ("mic", "speaker"):
                owner = self._realtime_owners[source]
                health = owner[0].health() if owner else dict(source=source, state="idle", namespace=None, error_code=None)
                health.update(generation=self._realtime_generation[source],
                              requested=self._realtime_requested[source] and health["state"] not in ("closed", "failed", "stopping"),
                              error_code=self._realtime_errors[source] or health.get("error_code"))
                result[source] = health
            return {"status": 200, "result": result}

    def stopRealtimeASR(self, data, *args, **kwargs):
        try:
            source = self._realtimeSource(data)
        except ValueError:
            return {"status": 400, "result": {"error_code": "realtime_source_invalid"}}
        with self._realtime_lock:
            self._invalidateRealtimeLocked(source)
        self._publishRealtimeToggle(source)
        return self.getRealtimeASRState()

    def _drainRealtimeASR(self, source, timeout=3.0):
        # Callers serialize replacement with the source lifecycle lock. Keep a
        # busy owner referenced so repeated starts cannot accumulate workers.
        with self._realtime_lock:
            owner = self._realtime_owners[source]
        if owner is None:
            return True
        deadline = time.monotonic() + timeout
        session_done = owner[0].close(timeout)
        delivery_done = owner[1].close(max(0.0, deadline - time.monotonic()))
        if session_done and delivery_done:
            with self._realtime_lock:
                if self._realtime_owners[source] is owner:
                    self._realtime_owners[source] = None
            return True
        return False

    def _closeRealtimeASR(self):
        with self._realtime_lock:
            self._realtime_closed = True
            for source in ("mic", "speaker"):
                self._invalidateRealtimeLocked(source)
        # In-flight starts recheck closed/generation before creating an owner.
        results = [self._drainRealtimeASR(source) for source in ("mic", "speaker")]
        return all(results)

    def startRealtimeASR(self, data, *args, **kwargs):
        try:
            source = self._realtimeSource(data)
            expected = data.get("_realtime_generation")
            if type(expected) is not int or expected < 0:
                raise ValueError()
        except ValueError:
            return {"status": 400, "result": {"error_code": "realtime_start_invalid"}}
        result = self._startRealtime(source, expected)
        self._publishRealtimeToggle(source)
        return result

    # ------------------------------------------------------------------
    # Linux main Mic/Speaker toggles. PyAudioWPatch, the legacy recorder, is
    # Windows-only, so on Linux these toggles start and stop the realtime
    # session of their source with the saved realtime settings, and show its
    # state. config.ENABLE_TRANSCRIPTION_* stays False there, so the legacy
    # device-change paths keyed on it never start the legacy recorder.
    # ------------------------------------------------------------------
    # A started server enforces its own START_TIMEOUT; this only bounds the
    # toggle's wait if that end state is somehow never published.
    _ASR_SERVER_WAIT = SPEECH_START_TIMEOUT + 5
    _ASR_START_FAILURES = ("speech_server_out_of_memory", "speech_server_start_timeout",
                           "speech_server_vulkan_missing", "speech_server_device_failed")

    def _realtimeToggles(self):
        if sys.platform == "linux":
            return True
        # Windows keeps the legacy recorder until the user picks the bundled server.
        settings = getattr(self, "_realtime_settings", None) or {}
        return sys.platform == "win32" and settings.get("server") == "bundled"

    def _realtimeActiveLocked(self, source):
        owner = self._realtime_owners[source]
        state = owner[0].health()["state"] if owner else "idle"
        return self._realtime_requested[source] and state not in ("closed", "failed", "stopping")

    def _realtimeNotReady(self, source, reason):
        # details.reason names the missing piece; the UI turns it into the next step.
        code = ErrorCode.TRANSCRIPTION_SEND_NOT_READY if source == "mic" else ErrorCode.TRANSCRIPTION_RECEIVE_NOT_READY
        return VRCTError.create_error_response(code, data=False, details={"reason": str(reason)})

    def _publishRealtimeToggle(self, source, reason=None):
        """Show the realtime state as the Linux toggle; reason explains a stop nobody asked for."""
        # Moving off the bundled server on Windows still has to clear a shown ON.
        if not self._realtimeToggles() and not self._realtime_toggle_shown[source]:
            return
        direction = "send" if source == "mic" else "receive"
        with self._realtime_toggle_lock:
            with self._realtime_lock:
                active = self._realtimeActiveLocked(source)
            if active != self._realtime_toggle_shown[source]:
                self._realtime_toggle_shown[source] = active
                if not active and reason:
                    response = self._realtimeNotReady(source, reason)
                    self.run(response["status"], "/set/enable/transcription_" + direction, response["result"])
                else:
                    self.run(200, "/set/%s/transcription_%s" % ("enable" if active else "disable", direction), active)
        self._releaseAsrServer()

    def _realtimeEnded(self, source, generation):
        """A session's delivery stopped. If it was still wanted, it failed: say why."""
        if not self._realtimeToggles():
            return
        with self._realtime_lock:
            wanted = self._realtime_generation[source] == generation and self._realtime_requested[source]
            if wanted:
                model.message_delivery.revoke(source)
            owner = self._realtime_owners[source]
            code = self._realtime_errors[source] or (owner[0].health().get("error_code") if owner else None)
        self._publishRealtimeToggle(source, (code or "realtime_session_failed") if wanted else None)

    def _releaseAsrServer(self):
        """Stop a bundled ASR server a toggle started, once neither toggle uses it."""
        with self._realtime_toggle_lock:
            owned = self._asr_server_owned
            if owned is None or self._asr_toggle_starting:
                return
            with self._realtime_lock:
                if any(self._realtimeActiveLocked(source) for source in ("mic", "speaker")):
                    return
            self._asr_server_owned = None
            # Non-joining. A server started from Settings has another generation
            # and keeps running; so does one started after this run ended.
            self.speech_servers.stop("asr", generation=owned)

    def _realtimeStartCurrent(self, source, expected):
        with self._realtime_lock:
            return not self._realtime_closed and expected == self._realtime_generation[source]

    def _awaitAsrServer(self, source, expected):
        """Start the bundled ASR server if it is stopped, then wait until it is ready."""
        if not self._realtimeStartCurrent(source, expected):
            return "realtime_stale_start"
        row = self.speech_servers.state()["asr"]
        if row["state"] == "stopping":
            return "speech_server_busy"
        run = row["generation"]
        if row["state"] not in ("ready", "preparing"):
            with self._speech_settings_lock:
                settings = copy.deepcopy(self._speech_settings)
            profile = settings["profiles"]["asr"]
            if not profile["model"].strip():
                return "realtime_asr_model_missing"
            if not profile["vad_model"].strip():
                return "realtime_vad_model_missing"
            try:
                options = speech_start_options(settings, "asr")
            except ValueError:
                return "speech_server_model_invalid"
            with self._realtime_toggle_lock:
                try:
                    self.speech_servers.start("asr", options, run)
                except RuntimeError as exc:
                    return "speech_server_busy" if str(exc) == "speech_server_busy" else "speech_server_start_failed"
                run += 1  # start() succeeds only from that generation and takes the next.
                self._asr_server_owned = run
        deadline = time.monotonic() + self._ASR_SERVER_WAIT
        while True:
            if not self._realtimeStartCurrent(source, expected):
                return "realtime_stale_start"
            row = self.speech_servers.state()["asr"]
            if row["state"] == "failed":
                code = row.get("error_code")
                return code if code in self._ASR_START_FAILURES else "speech_server_start_failed"
            if row["generation"] != run or row["state"] in ("stopped", "stopping"):
                return "speech_server_not_ready"  # Stopped from Settings meanwhile.
            if row["state"] == "ready":
                return None
            if time.monotonic() >= deadline:
                return "speech_server_start_timeout"
            time.sleep(0.05)

    def _prepareRealtimeToggle(self, source, expected):
        """Check a toggle ON against settings and the server; (code, None) names what is missing."""
        with self._realtime_lock:
            if self._realtime_closed or expected != self._realtime_generation[source]:
                return "realtime_stale_start", None
            settings = normalize_realtime_settings(self._realtime_settings)
        row = settings[source]
        try:
            # Fail before loading a model for a missing device or one that cannot be read.
            endpoint = realtime_endpoint(settings, source) or default_endpoint(source)
        except ValueError as exc:
            return str(exc), None
        if self._carriesOwnVoice(endpoint):
            return "realtime_endpoint_feedback", None
        if not self._realtimeStartCurrent(source, expected):
            return "realtime_stale_start", None
        if settings["server"] == "bundled":
            code = self._awaitAsrServer(source, expected)
            if code:
                return code, None
            try:
                base_url = self.speech_servers.binding("asr")
            except RuntimeError:
                return "speech_server_not_ready", None
        else:
            base_url = settings["base_url"]
        if not self._realtimeStartCurrent(source, expected):
            return "realtime_stale_start", None
        try:
            models = SpeechCppASR(base_url, timeout=5).recognizers()
        except Exception:
            return "realtime_models_unavailable", None
        if not self._realtimeStartCurrent(source, expected):
            return "realtime_stale_start", None
        chosen = next((m for m in models if m.id == settings["model"]), None)
        if chosen is None and settings["server"] == "bundled" and len(models) == 1:
            # The bundled server loads exactly one recognizer: switching the
            # downloaded model must not also require picking its id again.
            chosen = models[0]
        if chosen is None:
            return ("realtime_model_unavailable" if settings["model"] else "realtime_model_required"), None
        if not language_supported(chosen, row["language"]):
            return ("realtime_language_auto_unsupported" if row["language"] == "auto"
                    else "realtime_language_unsupported"), None
        return None, SessionOptions(base_url, chosen.id, row["language"], merged_terms(settings["vocabulary"]))

    def _enableRealtimeToggle(self, source, data=None):
        with self._realtime_lock:
            # 設定画面を閉じたときの復帰 (reason: settings_resume) だけを断る。利用者がメイン画面で
            # スイッチを押した場合は、止めたあとでも本人の新しい操作なので、そのまま始める。
            refused = (isinstance(data, dict) and data.get("reason") == "settings_resume"
                       and source in self._realtime_resume_refused)
            self._realtime_settings_paused.discard(source)
            self._realtime_resume_refused.discard(source)
        if refused:
            self._publishRealtimeToggle(source)
            return {"status": 200, "result": False}
        with self._realtime_lock:
            # IPC supplies the receipt-time stamp. Direct callers take their
            # snapshot here, before any potentially blocking preparation.
            expected = self._realtime_generation[source]
            if isinstance(data, dict):
                expected = data.get("_realtime_generation", expected)
            if type(expected) is not int or expected < 0:
                return self._realtimeNotReady(source, "realtime_start_invalid")
            if self._realtime_closed or expected != self._realtime_generation[source]:
                return self._realtimeNotReady(source, "realtime_stale_start")
            active = self._realtimeActiveLocked(source)
        if not active:
            with self._realtime_toggle_lock:
                self._asr_toggle_starting += 1  # Keeps a just-started server from release.
            try:
                code, options = self._prepareRealtimeToggle(source, expected)
                if code is None:
                    result = self._startRealtime(source, expected, options)
                    if result["status"] != 200:
                        code = result["result"]["error_code"]
            finally:
                with self._realtime_toggle_lock:
                    self._asr_toggle_starting -= 1
                # Includes cancellation and preparation exceptions. Only stop
                # the server incarnation owned by toggles, when none uses it.
                self._releaseAsrServer()
            if code is not None:
                self._publishRealtimeToggle(source)
                return self._realtimeNotReady(source, code)
        with self._realtime_lock:
            active = self._realtimeActiveLocked(source)
            owner = self._realtime_owners[source]
            code = self._realtime_errors[source] or (owner[0].health().get("error_code") if owner else None)
        self._publishRealtimeToggle(source)
        # A session can fail before this returns; report that, not a stale ON.
        return {"status": 200, "result": True} if active else self._realtimeNotReady(source, code or "realtime_session_failed")

    def _disableRealtimeToggle(self, source):
        with self._realtime_lock:
            self._invalidateRealtimeLocked(source)
        self._publishRealtimeToggle(source)
        return {"status": 200, "result": False}

    def _realtimeFallbackLanguage(self, source):
        # With "auto" the model names each final's language. Without one, use
        # the language VRCT has for this side, as the legacy recorder does.
        try:
            languages = config.SELECTED_YOUR_LANGUAGES if source == "mic" else config.SELECTED_TARGET_LANGUAGES
            return languages[config.SELECTED_TAB_NO]["1"]["language"]
        except (KeyError, TypeError, AttributeError):
            return None

    def _carriesOwnVoice(self, endpoint):
        return (self._directUsesOutputDevice()
                and carries_own_voice(endpoint.name, self.voice_events.settings.output_device))

    def _startRealtime(self, source, expected, prepared=None):
        """prepared: SessionOptions that a main toggle already checked with the server."""
        def failure(code, status=409):
            return {"status": status, "result": {"error_code": code}}

        def precheck():
            if self._realtime_closed or expected != self._realtime_generation[source]:
                return failure("realtime_stale_start")
            if sys.platform not in ("linux", "win32"):
                return failure("realtime_platform_unsupported")
            if self._realtime_requested[source]:
                owner = self._realtime_owners[source]
                if owner is None or owner[0].health()["state"] not in ("closed", "failed"):
                    return failure("realtime_already_started")
            return None

        with getattr(self, source + "_lifecycle_lock"):
            with self._realtime_lock:
                refused = precheck()
                row = self._realtime_settings[source]
                follow = row["endpoint"] is None and row["follow_default"]
            if refused:
                return refused
            default = None
            if follow:
                # Read the graph outside the fast-stop lock; a settings change
                # meanwhile advances the generation and makes this start stale.
                try:
                    default = default_endpoint(source)
                except ValueError as exc:
                    return failure(str(exc))
            with self._realtime_lock:
                refused = precheck()
                if refused:
                    return refused
                try:
                    endpoint = realtime_endpoint(self._realtime_settings, source)
                    if endpoint is None:
                        endpoint = default
                    if endpoint is None:
                        raise ValueError("realtime_endpoint_required")
                    if self._carriesOwnVoice(endpoint):
                        raise ValueError("realtime_endpoint_feedback")
                    if prepared is not None:
                        options = prepared
                    else:
                        options, _ = session_options(self._realtime_settings, source)
                    server_run = None
                    if self._realtime_settings["server"] == "bundled":
                        server_run = self.speech_servers.current_run("asr")
                        options = replace(options, base_url=self.speech_servers.binding("asr"))
                        if server_run is None or self.speech_servers.current_run("asr") != server_run:
                            return failure("speech_server_not_ready")
                    detect = options.language == "auto"
                    language = self._realtimeFallbackLanguage(source) if detect else self._realtimeLanguage(options.language)
                except RuntimeError:
                    return failure("speech_server_not_ready")
                except ValueError as exc:
                    return failure(str(exc), 400)
                if source == "mic":
                    # A terminal owner's cleanup may run after this ownership
                    # advance. Cancel its speech before making it stale.
                    self._cancelMicVoice()
                self._realtime_generation[source] += 1
                generation = self._realtime_generation[source]
                self._realtime_requested[source] = True
                # Terminal handling takes this lock too, including while the
                # source is still draining its previous capture owner.
                self._realtime_server_runs[source] = (generation, server_run) if server_run is not None else None
                self._realtime_errors[source] = None

            def current():
                with self._realtime_lock:
                    return (not self._realtime_closed and self._realtime_requested[source]
                            and self._realtime_generation[source] == generation)

            def fail_start(code):
                with self._realtime_lock:
                    if self._realtime_generation[source] == generation:
                        model.message_delivery.revoke(source)
                        self._invalidateRealtimeLocked(source)
                        self._realtime_errors[source] = code
                return failure(code)

            if not self._drainRealtimeASR(source):
                return fail_start("realtime_previous_owner_busy")
            if not current():
                return failure("realtime_stale_start")
            direction = "SEND" if source == "mic" else "RECEIVE"
            try:
                setattr(config, "ENABLE_TRANSCRIPTION_" + direction, False)
                setattr(config, "ENABLE_CHECK_ENERGY_" + direction, False)
                self.run(200, "/set/disable/check_" + source + "_threshold", False)
                if model.stopCaptureForRealtime(source) is not True:
                    return fail_start("realtime_legacy_stop_failed")
                # Where the Mic/Speaker toggles show realtime itself, turning them
                # off here would undo this start. Elsewhere they showed the
                # legacy recorder that just stopped.
                if not self._realtimeToggles():
                    self.run(200, "/set/disable/transcription_" + direction.lower(), False)
            except Exception:
                return fail_start("realtime_legacy_stop_failed")

            def publish(payload, admitted, snapshot):
                if payload["state"] == "outcome":
                    # RealtimeDelivery only emits this for a published final.
                    # Settling its log row must outlive mute, stop and expiry.
                    self.run(200, "/run/realtime_caption", {**payload, "generation": generation})
                    return True

                def valid():
                    return current() and admitted()

                failures = []
                spec = REALTIME_MIC_SPEC if source == "mic" else REALTIME_SPEAKER_SPEC
                msg_id = payload["namespace"] + ":" + payload["item_id"]
                shown = self._runMessageSink("ui", lambda: self.run(
                    200, "/run/realtime_caption", {**payload, "generation": generation}),
                    valid, failures, spec, msg_id)

                def overlay():
                    if config.OVERLAY_LARGE_LOG is True and self._is_overlay_available():
                        def valid_overlay():
                            return (valid() and config.OVERLAY_LARGE_LOG and session.is_current(payload["namespace"])
                                    and (payload["state"] == "discarded" or time.monotonic_ns() < payload["expires_ns"]))
                        model.publishRealtimeCaptionOverlay(
                            payload, snapshot.source_language, language_payload(snapshot.destinations), valid_overlay,
                            only_translated=snapshot.overlay_only_translated)

                self._runMessageSink("overlay_large", overlay, valid, failures, spec, msg_id)
                return shown

            def clear_overlay():
                with self._realtime_lock:
                    if source == "mic" and self._realtime_generation[source] == generation:
                        self.voice_events.cancel_source("mic")
                namespace = session.health()["namespace"]
                if namespace and self._is_overlay_available():
                    model.clearRealtimeCaptionOverlay(source, namespace)

            def process(update, valid, admitted, mic_snapshot, snapshot, sequence):
                def guard():
                    return current() and valid() and admitted()
                if not guard():
                    return None
                return self._processMessage(
                    REALTIME_MIC_SPEC if source == "mic" else REALTIME_SPEAKER_SPEC,
                    update.text, snapshot.source_language, msg_id=update.namespace + ":" + update.item_id,
                    publication_guard=guard, speech_update=update if source == "mic" else None,
                    mic_snapshot=mic_snapshot, settings_snapshot=snapshot, chatbox_sequence=sequence,
                    output_progress=valid.output)

            def admit(update):
                admitted = self._messagePublicationGuard(source)
                spec = REALTIME_MIC_SPEC if source == "mic" else REALTIME_SPEAKER_SPEC
                spoken = language
                if detect and getattr(update, "language", ""):
                    try:
                        spoken = self._realtimeLanguage(update.language)
                    except ValueError:
                        pass  # Keep the configured fallback for unknown language codes.
                sequence = model.chatbox_order.admit() if source == "mic" and update.is_final else None
                with self._voice_settings_lock, getattr(self, "_language_settings_lock", nullcontext()):
                    snapshot = MessageSnapshot.capture(config, spec, spoken)
                    mic_snapshot = update.voice_snapshot if source == "mic" and update.is_final else None
                return (
                    lambda payload: publish(payload, admitted, snapshot),
                    lambda event, valid: process(event, valid, admitted, mic_snapshot, snapshot, sequence),
                    admitted,
                )

            def error(code):
                with self._realtime_lock:
                    if self._realtime_generation[source] == generation:
                        self._realtime_errors[source] = code

            with self._realtime_lock:
                if self._realtime_closed or self._realtime_generation[source] != generation:
                    return failure("realtime_stale_start")
                try:
                    session = RealtimeSession(source, options, endpoint,
                                              snapshot_voice=self._snapshotMicVoice if source == "mic" else None)
                    def stopped():
                        try:
                            clear_overlay()
                        finally:
                            self._realtimeEnded(source, generation)
                    delivery = RealtimeDelivery(session, publish, process, error, on_stopped=stopped, admit=admit)
                    self._realtime_owners[source] = (session, delivery)
                    # These only launch workers; neither waits for capture/network.
                    session.start()
                    delivery.start()
                except Exception:
                    model.message_delivery.revoke(source)
                    self._invalidateRealtimeLocked(source)
                    self._realtime_errors[source] = "realtime_start_failed"
                    return failure("realtime_start_failed")
        return self.getRealtimeASRState()

    def _is_overlay_available(self) -> bool:
        """Safe check whether overlay is present and initialized.

        This avoids AttributeError when `model` was not fully initialized.
        """
        try:
            overlay = getattr(model, "overlay", None)
            return overlay is not None and getattr(overlay, "initialized", False)
        except Exception:
            errorLogging()
            return False

    def setInitMapping(self, init_mapping:dict) -> None:
        self.init_mapping = init_mapping

    def setRunMapping(self, run_mapping:dict) -> None:
        self.run_mapping = run_mapping

    def setRun(self, run:Callable[[int, str, Any], None]) -> None:
        self.run = run

    def _stopLockedForShutdown(self, lock: Lock, stop_fn: Callable[[], None], label: str) -> None:
        """shutdown() 専用: lock を取得してから stop_fn() を呼ぶ。

        通常経路 (stopTranscriptionSendMessage 等) と同じロックを使うが、
        shutdown() は他の全ての mic/speaker_lifecycle_lock 保持経路
        (start/stop 系, AudioLifecycleWorker 経由のデバイス切替等) と
        直列化されないまま model.* を直接叩いていたため、_stop() と
        _start() が同一 Session に対して並行実行され得た。取得を
        acquire(timeout=...) にしているのは、終了処理自体がロック待ちで
        無期限にハングしないようにするため (ロックが返らない場合は
        ログを残してこの停止だけスキップし、後続の停止処理は続行する)。
        """
        acquired = lock.acquire(timeout=_SHUTDOWN_LIFECYCLE_LOCK_TIMEOUT_SEC)
        if not acquired:
            printLog(f"shutdown: {label} のロック取得が {_SHUTDOWN_LIFECYCLE_LOCK_TIMEOUT_SEC}s でタイムアウトしたため、この停止処理をスキップします")
            return
        try:
            stop_fn()
        except Exception:
            errorLogging()
        finally:
            lock.release()

    @staticmethod
    def _stopWorkerForShutdown(worker) -> None:
        """shutdown() 専用: AudioLifecycleWorker.stop() の例外を握りつぶす。

        mic/speaker で独立したワーカーなので、shutdown() 側では
        ThreadPoolExecutor で並行に stop() することで、直列に呼んだ場合の
        最大2倍の待ち時間 (各最大 _SHUTDOWN_LIFECYCLE_LOCK_TIMEOUT_SEC 秒)
        を避ける (コードレビュー指摘)。
        """
        try:
            worker.stop(timeout=_SHUTDOWN_LIFECYCLE_LOCK_TIMEOUT_SEC)
        except Exception:
            errorLogging()

    @staticmethod
    def _stopServiceForShutdown(stop_fn: Callable[[], None], label: str) -> None:
        """shutdown() 専用: stop_fn() を最大 _SHUTDOWN_SERVICE_STOP_TIMEOUT_SEC
        秒の別スレッドで実行する。OSC/WebSocket/OBS Browser Source/Overlayの
        各停止処理を、詰まっても shutdown() 自体を道連れにしない形で呼ぶための
        共通ヘルパー(フェーズ4項目30)。
        """
        def _run() -> None:
            try:
                stop_fn()
            except Exception:
                errorLogging()

        thread = Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=_SHUTDOWN_SERVICE_STOP_TIMEOUT_SEC)
        if thread.is_alive():
            printLog(
                f"shutdown: {label} の停止が {_SHUTDOWN_SERVICE_STOP_TIMEOUT_SEC}s "
                "でタイムアウトしました(プロセス終了時に破棄されます)"
            )

    def shutdown(self, *args, **kwargs) -> dict:
        """Shutdown controller and model (including telemetry).

        Returns:
            dict with status 200 and result True on success.
        """
        # Close admission and revoke existing work before any cleanup can wait.
        model.message_delivery.close()
        model.requestOSCShutdown()
        # Signal both owners before either close can wait on a worker or lock.
        for owner in (getattr(self, 'model_downloads', None), getattr(self, 'vc_runtimes', None),
                      getattr(self, 'legacy_downloads', None)):
            if owner is not None:
                owner.request_close()
        if getattr(self, 'model_downloads', None) is not None:
            if not self.model_downloads.close():
                printLog('[models] download/apply shutdown pending')
        if getattr(self, 'vc_runtimes', None) is not None and not self.vc_runtimes.close():
            printLog('[voice] runtime setup shutdown pending')
        if getattr(self, 'legacy_downloads', None) is not None:
            if not self.legacy_downloads.close():
                printLog('[models] legacy download cancellation pending; publication is disabled')
        with _OCR_CONTROL_LOCK:
            self._ocr_shutting_down = True
            config.ENABLE_OCR_CAPTURE = False
            # Signal without waiting for a concurrent model load/lifecycle lock.
            model.requestOCRShutdown()
        self._stopServiceForShutdown(model.stopOCRCapture, "OCR capture")
        if getattr(self, 'model_hardware', None) is not None and not self.model_hardware.close():
            printLog('[models] hardware inspection shutdown pending')
        if not self._closeRealtimeASR():
            printLog("[asr] realtime shutdown unconfirmed")
        if getattr(self, "direct_voice", None) is not None:
            with self._voice_settings_lock:
                self._direct_voice_closed = True
                self.direct_voice.stop()
        if getattr(self, "voice_route", None) is not None:
            # One in-flight gate operation (<=4.5s) plus the final mute (<=4.5s).
            # close bounds its own wait; do not truncate it with the generic 5s wrapper.
            if not self.voice_route.close(timeout=10):
                printLog("[voice] shutdown mute unconfirmed; check the virtual microphone")
        if getattr(self, "direct_voice", None) is not None:
            if not self.direct_voice.close(timeout=3):
                printLog("[voice] input forwarding shutdown unconfirmed")
        if getattr(self, "voice_events", None) is not None:
            self._stopServiceForShutdown(self.voice_events.close, "TTS")
        if getattr(self, "speech_servers", None) is not None:
            if not self.speech_servers.close(timeout=3):
                printLog("[speech] owned server shutdown unconfirmed")
        # デバイス監視・録音系スレッドを明示的に停止する。これを怠ると
        # PyAudio/WASAPI ストリームが open されたままプロセスが終了し、
        # デバイスハンドルがリークしたり、次回起動時の初期化に影響し得る。
        # 各停止は個別に例外を握りつぶし、1つの失敗が他の停止処理を
        # ブロックしないようにする。
        #
        # Auto Mic/Speaker Select の ActiveEndpointTracker は
        # setMicAutoActive(False)/setSpeakerAutoActive(False) を呼ばない
        # 限り止まらない (stopMonitoring は別スレッドの監視ループのみを
        # 止める)。ここで止めずに終了すると、tracker が COM 呼び出しの
        # 途中でプロセスごと終了することになり、CoUninitialize されない
        # まま COM ポインタが破棄されて access violation
        # (Exception ignored in: _compointer_base.__del__) を起こす経路が
        # 残る。stopMonitoring() より前に呼ぶ: 後で呼ぶと
        # _syncMonitoringLifecycleLocked() が「もう片方はまだ active」と見て
        # 監視スレッドを再起動してしまう。
        try:
            device_manager.setDeviceListMonitoringActive(False)
        except Exception:
            errorLogging()
        try:
            device_manager.setMicAutoActive(False)
        except Exception:
            errorLogging()
        try:
            device_manager.setSpeakerAutoActive(False)
        except Exception:
            errorLogging()
        try:
            device_manager.stopMonitoring()
        except Exception:
            errorLogging()
        # mic/speaker_lifecycle_worker を止め、以後の enqueue を無視する。
        # ここで止めておかないと、シャットダウン中に届いた古いデバイス
        # 通知やミュート同期の再送が、直後の _stopLockedForShutdown による
        # リソース解放と競合しうる (フェーズ3項目21)。mic/speakerは互いに
        # 無関係なので、直列ではなく並行に stop() する (コードレビュー指摘:
        # 直列だと最大 _SHUTDOWN_LIFECYCLE_LOCK_TIMEOUT_SEC 秒の2倍を
        # 待ちうる。ここは watchdog の強制終了デッドライン
        # [mainloop._WATCHDOG_GRACE_PERIOD_SEC] と競争している区間)。
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._stopWorkerForShutdown, model.mic_lifecycle_worker),
                executor.submit(self._stopWorkerForShutdown, model.speaker_lifecycle_worker),
            ]
            for future in futures:
                future.result()
        # 以下の4つは他の全ての start/stop 系 (mic/speaker_lifecycle_lock を
        # 保持する) と直列化する必要がある。ロック未取得のまま model.* を
        # 直接叩くと、AudioLifecycleWorker がまだ実行中の
        # restartAccessMicDevices 等と _stop()/_start() が並行実行され、
        # 片方が代入した新しい Recorder をもう片方が知らずに破棄する形で
        # listener スレッドと PyAudio ストリームが宙に浮いたままプロセスが
        # 終了しうる。
        self._stopLockedForShutdown(self.mic_lifecycle_lock, model.stopMicTranscript, "mic transcript")
        self._stopLockedForShutdown(self.speaker_lifecycle_lock, model.stopSpeakerTranscript, "speaker transcript")
        self._stopLockedForShutdown(self.mic_lifecycle_lock, model.stopCheckMicEnergy, "mic energy")
        self._stopLockedForShutdown(self.speaker_lifecycle_lock, model.stopCheckSpeakerEnergy, "speaker energy")
        # OSC / WebSocket / OBS Browser Source / Overlay も明示的に停止する
        # (フェーズ4項目30)。以前はここが抜けており daemon thread としての
        # プロセス終了任せになっていた: OSCQueryはzeroconfでサービス広告を
        # 出しているため、close()無しの終了は他アプリ側に無効なレコードを
        # 残す。呼び出し順は「依存する側を先に」— OBS Browser SourceはWebSocket
        # サーバ経由でメッセージを受け取るため、OBSを先に止める。
        self._stopServiceForShutdown(model.stopReceiveOSC, "OSC receive server")
        self._stopServiceForShutdown(model.stopObsBrowserSourceServer, "OBS browser source server")
        self._stopServiceForShutdown(model.stopWebSocketServer, "WebSocket server")
        self._stopServiceForShutdown(model.shutdownOverlay, "Overlay")
        # watchdog も明示停止する。init() が startWatchdog() で武装する
        # faulthandler.dump_traceback_later が残ったままだと、フロントエンドは
        # 終了操作と同時に feed を止めるため、プロセスが (interval + 15秒)
        # 以上生き残った場合に「正常終了なのに freeze_trace.log へフリーズ
        # ダンプが出る」。この計装はフリーズ調査の一次情報源なので汚さない。
        self._stopServiceForShutdown(model.stopWatchdog, "watchdog")
        # 翻訳の常設プール。非デーモンスレッドなので、止めないと
        # インタプリタ終了時の atexit join で終了が止まりうる。
        self._stopServiceForShutdown(model.stopTranslationExecutor, "translation executor")
        try:
            # A setting changed in the last few seconds may still be sitting
            # in the debounce timer rather than on disk; flush it now so a
            # normal app close never silently drops the change.
            config.saveConfigToFile()
        except Exception:
            errorLogging()
        utterance_diagnostics.flush(reason="shutdown")
        try:
            model.telemetryShutdown()
            return {"status": 200, "result": True}
        except Exception:
            errorLogging()
            return {"status": 500, "result": False}

    # response functions
    def connectedNetwork(self) -> None:
        self.run(
            200,
            self.run_mapping["connected_network"],
            True,
        )

    def disconnectedNetwork(self) -> None:
        self.run(
            200,
            self.run_mapping["connected_network"],
            False,
        )

    @staticmethod
    def _missingBuiltInModelInUse(ctranslate2_available: bool, whisper_available: bool) -> bool:
        """いま選んでいるエンジンが、取得していない内蔵モデルを必要としているか。

        以前は、どちらか一方でも無ければ起動のたびに警告していた。そのため、翻訳モデルを取得して
        文字起こしは Google を選んでいる人や、どちらも外部のサービスを使う人にも、使わないモデルに
        ついての警告が毎回出ていた。選んでいないエンジンのモデルは、選んだときに取得を案内する。
        """
        translation = config.SELECTED_TRANSLATION_ENGINES.get(config.SELECTED_TAB_NO) == "CTranslate2"
        transcription = config.SELECTED_TRANSCRIPTION_ENGINE == "Whisper"
        return (translation and not ctranslate2_available) or (transcription and not whisper_available)

    def enableAiModels(self) -> None:
        self.run(
            200,
            self.run_mapping["enable_ai_models"],
            True,
        )

    def disableAiModels(self) -> None:
        self.run(
            200,
            self.run_mapping["enable_ai_models"],
            False,
        )

    def updateMicHostList(self) -> None:
        self.run(
            200,
            self.run_mapping["selectable_mic_host_list"],
            model.getListMicHost(),
        )

    def _audioLock(self, source):
        name = source + "_lifecycle_lock"
        lock = getattr(self, name, None)
        if lock is None:
            lock = RLock()
            setattr(self, name, lock)
        return lock

    def _audioGeneration(self, source, *, advance=False):
        name = "_" + source + "_intent_generation"
        generation = getattr(self, name, 0) + int(advance)
        setattr(self, name, generation)
        return generation

    @staticmethod
    def _audioFlags(source):
        suffix = "SEND" if source == "mic" else "RECEIVE"
        return "ENABLE_TRANSCRIPTION_" + suffix, "ENABLE_CHECK_ENERGY_" + suffix

    def _audioDevices(self, source):
        if source == "mic":
            return [(host, d) for host, devices in device_manager.getMicDevices().items() for d in devices]
        return [(None, d) for d in device_manager.getSpeakerDevices()]

    def _selectedAudioDevice(self, source):
        devices = [d for host, d in self._audioDevices(source)
                   if source != "mic" or host == config.SELECTED_MIC_HOST]
        return resolve_device(devices, getattr(config, "SELECTED_" + source.upper() + "_DEVICE_ID"),
                              getattr(config, "SELECTED_" + source.upper() + "_DEVICE"))

    def _audioTarget(self, source, *, follow_default=True):
        selected = self._selectedAudioDevice(source)
        auto = getattr(config, "AUTO_" + source.upper() + "_SELECT")
        if selected is not None and not (auto and follow_default):
            return selected
        available = [d for _, d in self._audioDevices(source) if d.get("name") != "NoDevice"]
        # Do not guess which of two identically named devices an old setting meant.
        name = getattr(config, "SELECTED_" + source.upper() + "_DEVICE")
        endpoint_id = getattr(config, "SELECTED_" + source.upper() + "_DEVICE_ID")
        if not auto and not endpoint_id and len([d for d in available if d.get("name") == name]) > 1:
            return None
        default = (device_manager.getDefaultMicDevice() if source == "mic"
                   else device_manager.getDefaultSpeakerDevice()).get("device", {})
        matched = resolve_device(available, device_id(default), default.get("name"))
        return matched or (available[0] if available else None)

    def _publishAudioDeviceLocked(self, source, device, previous=None):
        prefix = "SELECTED_" + source.upper() + "_DEVICE"
        name = device.get("name", "NoDevice") if device else "NoDevice"
        identity = device_id(device)
        old_name = getattr(config, prefix)
        ambiguous = (not device and not getattr(config, prefix + "_ID")
                     and len([d for _, d in self._audioDevices(source) if d.get("name") == old_name]) > 1)
        if source == "mic" and not ambiguous:
            host = next((host for host, item in self._audioDevices(source)
                         if capture_key(item) == capture_key(device)), device.get("host_name", "NoHost")) if device else "NoHost"
            config.SELECTED_MIC_HOST = host
            self.run(200, "/run/selectable_mic_host_list", list(device_manager.getMicDevices()))
            self.run(200, self.run_mapping.get("selected_mic_host", "/run/selected_mic_host"), host)
        if not ambiguous:
            setattr(config, prefix, name)
        setattr(config, prefix + "_ID", identity)
        # Publish options first, so a newly opened fallback has a visible label.
        self.run(200, "/run/selectable_" + source + "_device_options", self._audioDeviceOptionsLocked(source))
        self.run(200, self.run_mapping.get("selected_" + source + "_device", "/run/selected_" + source + "_device"), name)
        self.run(200, "/run/selected_" + source + "_device_id", identity)
        if previous and device and (device_id(previous), previous.get("name")) != (identity, name):
            self.run(200, "/run/audio_device_switched", {
                "source": source,
                "old_device": {"id": device_id(previous), "name": previous.get("name", "")},
                "new_device": {"id": identity, "name": name},
            })

    def _audioDeviceOptions(self, source):
        with self._audioLock(source):
            return self._audioDeviceOptionsLocked(source)

    def _audioDeviceOptionsLocked(self, source):
        devices = [d for host, d in self._audioDevices(source)
                   if source != "mic" or host == config.SELECTED_MIC_HOST]
        session = getattr(model, "_" + source + "_session", None)
        active = getattr(session, "_active_device", None)
        if active and device_id(active):
            # A refresh may precede the queued switch. Keep the current
            # capture's label available until its owner has actually stopped.
            devices = [active if device_id(d) == device_id(active) else d for d in devices]
            if not any(device_id(d) == device_id(active) for d in devices):
                devices.append(active)
        return device_options(devices)

    def _publishDeviceOptions(self, source):
        self.run(200, "/run/selectable_" + source + "_device_options", self._audioDeviceOptions(source))

    def _wireAudioSessionLocked(self, source):
        model.ensure_initialized()
        session = getattr(model, "_" + source + "_session")
        generation = self._audioGeneration(source)
        session.publication_guard_fnc = lambda: self._messagePublicationGuard(source)
        session.device_fnc = lambda device, previous: self._publishAudioDeviceLocked(source, device, previous)
        # Start/rollback callbacks run under the caller's source lock. Recorder
        # errors arrive on another thread and must enter through the lock boundary.
        session.error_fnc = lambda failure: self._audioPipelineFailedLocked(source, generation, failure)
        session.runtime_error_fnc = lambda failure: self._audioPipelineFailed(source, generation, failure)
        session.terminal_failure_fnc = lambda: self._audioTerminalFailureLocked(source, generation)
        return session

    def _audioTerminalFailureLocked(self, source, generation):
        if generation == self._audioGeneration(source):
            if any(getattr(config, flag) for flag in self._audioFlags(source)):
                self._disableTranscriptionAfterPipelineErrorLocked(source)

    def _audioPipelineFailed(self, source, generation, failure):
        with self._audioLock(source):
            self._audioPipelineFailedLocked(source, generation, failure, cleanup=True)

    def _audioPipelineFailedLocked(self, source, generation, failure, *, cleanup=False):
        if generation != self._audioGeneration(source):
            return
        revision = failure.get("capture_revision")
        if revision is not None and not self._audioCaptureCurrentLocked(source, revision):
            return
        failed_device = failure.get("failed_device")
        public_failure = {key: value for key, value in failure.items()
                          if key not in ("failed_device", "capture_revision")}
        if failed_device and failure.get("error_code") == "AUDIO_READ_ERROR":
            # A read error can precede the device-list notification. Reconcile
            # one fresh snapshot before declaring the user's capture ended.
            worker = getattr(model, source + "_lifecycle_worker", None)
            if worker is not None and worker.enqueue(
                    lambda: self._recoverAudioDeviceLoss(source, generation, revision, failed_device, public_failure),
                    coalesce_key=f"{source}_read_error_{generation}_{revision}") is not False:
                return
        if cleanup:
            public_failure = self._disableAudioAfterDeviceLossLocked(source) or public_failure
        else:
            self._audioTerminalFailureLocked(source, generation)
        self.run(200, self.run_mapping.get("transcription_recognition_error", "/run/transcription_recognition_error"), public_failure)

    def _audioCaptureCurrentLocked(self, source, revision):
        session = getattr(model, "_" + source + "_session")
        return session._recorder is not None and session._capture_revision == revision

    def _recoverAudioDeviceLoss(self, source, generation, revision, failed_device, failure):
        with self._audioLock(source):
            if (generation != self._audioGeneration(source)
                    or not self._audioCaptureCurrentLocked(source, revision)):
                return
        refresh_failed = False
        try:
            device_manager.update()
        except Exception:
            refresh_failed = True
            errorLogging()
        with self._audioLock(source):
            if (generation != self._audioGeneration(source)
                    or not self._audioCaptureCurrentLocked(source, revision)):
                return
            available = [d for _, d in self._audioDevices(source)]
            if not refresh_failed and not any(capture_key(d) == capture_key(failed_device) for d in available):
                self._reconcileAudioLocked(source, generation, previous_device=failed_device)
                return
            failure = self._disableAudioAfterDeviceLossLocked(source) or failure
            self.run(200, self.run_mapping.get("transcription_recognition_error", "/run/transcription_recognition_error"), failure)

    def _queueAudioReconciliation(self, source):
        with self._audioLock(source):
            generation = self._audioGeneration(source)
            flags = self._audioFlags(source)
            if not any(getattr(config, flag) for flag in flags):
                self._publishAudioDeviceLocked(source, self._audioTarget(source))
                return
        worker = getattr(model, source + "_lifecycle_worker", None)
        job = lambda: self._reconcileAudio(source, generation)
        if worker is not None:
            worker.enqueue(job, coalesce_key=f"{source}_device_reconcile_{generation}")
        else:
            job()

    def _reconcileAudio(self, source, generation=None, *, follow_default=True, device=None, previous_device=None):
        with self._audioLock(source):
            return self._reconcileAudioLocked(source, generation, follow_default=follow_default, device=device, previous_device=previous_device)

    def _reconcileAudioLocked(self, source, generation=None, *, follow_default=True, device=None, previous_device=None):
        if generation is not None and generation != self._audioGeneration(source):
            return
        transcript_flag, energy_flag = self._audioFlags(source)
        transcript, energy = getattr(config, transcript_flag), getattr(config, energy_flag)
        target = device if device is not None else self._audioTarget(source, follow_default=follow_default)
        if not transcript and not energy:
            self._publishAudioDeviceLocked(source, target)
            return
        if not target or target.get("name") == "NoDevice":
            self._disableAudioAfterDeviceLossLocked(source)
            self._publishAudioDeviceLocked(source, None)
            return
        session = self._wireAudioSessionLocked(source)
        pause = getattr(device_manager, "pause" + source.capitalize() + "EndpointTracker")
        resume = getattr(device_manager, "resume" + source.capitalize() + "EndpointTracker")
        pause()
        try:
            # Flags and generation are checked under the same lock used by OFF.
            previous = {"previous_device": previous_device} if previous_device else {}
            session.reconfigure(transcript=transcript, energy=energy,
                                device=target or {"name": "NoDevice"}, **previous)
            if not session.features:
                self._audioTerminalFailureLocked(source, self._audioGeneration(source))
                self._publishAudioDeviceLocked(source, None)
            elif session._active_device is not None:
                self._publishAudioDeviceLocked(source, session._active_device)
        except Exception:
            errorLogging()
            self._audioTerminalFailureLocked(source, self._audioGeneration(source))
        finally:
            resume()

    def updateMicDeviceList(self) -> None:
        self._queueAudioReconciliation("mic")
        self.run(200, self.run_mapping["selectable_mic_device_list"], model.getListMicDevice())
        self._publishDeviceOptions("mic")

    def updateSpeakerDeviceList(self) -> None:
        self._queueAudioReconciliation("speaker")
        self.run(200, self.run_mapping["selectable_speaker_device_list"], model.getListSpeakerDevice())
        self._publishDeviceOptions("speaker")

    def _synchronizeMicSelectionAfterDeviceUpdate(self):
        self._queueAudioReconciliation("mic")

    def _synchronizeSpeakerSelectionAfterDeviceUpdate(self):
        self._queueAudioReconciliation("speaker")

    def _disableAudioAfterDeviceLoss(self, source):
        with self._audioLock(source):
            self._disableAudioAfterDeviceLossLocked(source)

    def _disableAudioAfterDeviceLossLocked(self, source):
        self._audioGeneration(source, advance=True)
        # Revocation is a terminal intent change, never an internal switch.
        # It must precede joins/cleanup so admitted output cannot escape meanwhile.
        self._disableTranscriptionAfterPipelineErrorLocked(source)
        session = self._wireAudioSessionLocked(source)
        session.reconfigure(transcript=False, energy=False)
        if session._cleanup_workers:
            return session._make_pipeline_failure(ErrorCode.CLEANUP_TIMEOUT, "cleanup").to_notification()

    def updateConfigSettings(self) -> None:
        settings = {}
        for endpoint, dict_data in self.init_mapping.items():
            # 1つのgetterが例外を投げるとinit()がここで死に、
            # /run/initialization_complete が永久に送られずUIがローディング
            # 画面のまま固まる。値が取れなかった項目はNoneにして続行する。
            try:
                response = dict_data["variable"](None)
                result = response.get("result", None)
            except Exception:
                errorLogging()
                printLog(f"updateConfigSettings: failed to collect {endpoint}")
                result = None
            settings[endpoint] = result
        self.run(
            200,
            self.run_mapping["initialization_complete"],
            settings,
        )

    def restartAccessMicDevices(self, generation=None) -> None:
        self._reconcileAudio("mic", generation)

    def restartAccessSpeakerDevices(self, generation=None) -> None:
        self._reconcileAudio("speaker", generation)

    def stopAccessMicDevices(self) -> None:
        with self._audioLock("mic"):
            model.stopCaptureForRealtime("mic")

    def stopAccessSpeakerDevices(self) -> None:
        with self._audioLock("speaker"):
            model.stopCaptureForRealtime("speaker")

    def updateSelectedMicDevice(self, host, device) -> None:
        config.SELECTED_MIC_HOST = host
        config.SELECTED_MIC_DEVICE = device
        self.run(200, self.run_mapping["selected_mic_host"], config.SELECTED_MIC_HOST)
        self.run(200, self.run_mapping["selected_mic_device"], config.SELECTED_MIC_DEVICE)

    def updateSelectedSpeakerDevice(self, device) -> None:
        config.SELECTED_SPEAKER_DEVICE = device
        self.run(
            200,
            self.run_mapping["selected_speaker_device"],
            device,
        )

    def progressBarMicEnergy(self, energy) -> None:
        if energy is False:
            config.ENABLE_CHECK_ENERGY_SEND = False
            self.run(200, "/set/disable/check_mic_threshold", False)
            self.run(200, "/run/check_mic_volume", 0)
            error_response = VRCTError.create_error_response(
                ErrorCode.DEVICE_NO_MIC,
                data=None
            )
            self.run(
                error_response["status"],
                self.run_mapping["error_device"],
                error_response["result"],
            )
        else:
            self.run(
                200,
                self.run_mapping["check_mic_volume"],
                energy,
            )

    def progressBarSpeakerEnergy(self, energy) -> None:
        if energy is False:
            config.ENABLE_CHECK_ENERGY_RECEIVE = False
            self.run(200, "/set/disable/check_speaker_threshold", False)
            self.run(200, "/run/check_speaker_volume", 0)
            error_response = VRCTError.create_error_response(
                ErrorCode.DEVICE_NO_SPEAKER,
                data=None
            )
            self.run(
                error_response["status"],
                self.run_mapping["error_device"],
                error_response["result"],
            )
        else:
            self.run(
                200,
                self.run_mapping["check_speaker_volume"],
                energy,
            )

    class DownloadCTranslate2:
        def __init__(self, run_mapping:dict,  weight_type:str, run:Callable[[int, str, Any], None]) -> None:
            self.run_mapping = run_mapping
            self.weight_type = weight_type
            self.run = run
            self._last_progress = -1.0
            self._last_time = 0.0
            self.job_id = uuid4().hex
            self._terminal_lock = Lock()
            self._terminal_sent = False

        def progressBar(self, progress) -> None:
            if not _shouldEmitDownloadProgress(self, progress):
                return
            printLog("CTranslate2 Weight Download Progress", progress)
            self.run(
                200,
                self.run_mapping["download_progress_ctranslate2_weight"],
                {"weight_type": self.weight_type, "job_id": self.job_id, "progress": progress},
            )

        def downloaded(self, ready=False, error=None) -> None:
            with self._terminal_lock:
                if self._terminal_sent:
                    return
                self._terminal_sent = True
            config.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT[self.weight_type] = ready is True
            data = {"weight_type": self.weight_type, "job_id": self.job_id, "downloaded": ready is True}
            if ready is True:
                self.run(200, self.run_mapping["downloaded_ctranslate2_weight"], data)
            else:
                error_response = VRCTError.create_error_response(
                    ErrorCode.WEIGHT_CTRANSLATE2_DOWNLOAD, data={**data, "reason": error},
                )
                self.run(error_response["status"], self.run_mapping["error_ctranslate2_weight"], error_response["result"])

    class DownloadWhisper:
        def __init__(self, run_mapping:dict, weight_type:str, run:Callable[[int, str, Any], None]) -> None:
            self.run_mapping = run_mapping
            self.weight_type = weight_type
            self.run = run
            self._last_progress = -1.0
            self._last_time = 0.0
            self.job_id = uuid4().hex
            self._terminal_lock = Lock()
            self._terminal_sent = False

        def progressBar(self, progress) -> None:
            if not _shouldEmitDownloadProgress(self, progress):
                return
            printLog("Whisper Weight Download Progress", progress)
            self.run(
                200,
                self.run_mapping["download_progress_whisper_weight"],
                {"weight_type": self.weight_type, "job_id": self.job_id, "progress": progress},
            )

        def downloaded(self, ready=False, error=None) -> None:
            with self._terminal_lock:
                if self._terminal_sent:
                    return
                self._terminal_sent = True
            config.SELECTABLE_WHISPER_WEIGHT_TYPE_DICT[self.weight_type] = ready is True
            data = {"weight_type": self.weight_type, "job_id": self.job_id, "downloaded": ready is True}
            if ready is True:
                self.run(200, self.run_mapping["downloaded_whisper_weight"], data)
            else:
                error_response = VRCTError.create_error_response(
                    ErrorCode.WEIGHT_WHISPER_DOWNLOAD, data={**data, "reason": error},
                )
                self.run(error_response["status"], self.run_mapping["error_whisper_weight"], error_response["result"])

    def _messagePublicationGuard(self, source, publication_guard=None):
        def muted():
            return (source == "mic" and config.VRC_MIC_MUTE_SYNC is True
                    and model.mic_mute_status is not False)

        # A result refused at admission must stay refused after unmute.
        if muted():
            return lambda: False
        delivery = model.message_delivery
        epoch = delivery.snapshot(source)

        def current():
            return (delivery.current(source, epoch) and not muted()
                    and (publication_guard is None or publication_guard()))

        return current

    def _snapshotMicVoice(self):
        with self._voice_settings_lock:
            if getattr(self, "voice_events", None) is not None:
                if self.voice_events.settings.mic_mode == "translated" and config.ENABLE_TRANSLATION:
                    return (self.voice_events.settings, self.voice_events.generation(),
                            self.voice_events.source_generation("mic"))
        return None

    def _runMessageSink(self, output, action, current, failures, spec, msg_id):
        if not current():
            return False
        try:
            action()
            return True
        except Exception:
            failure = {"output": output, "error_code": ErrorCode.MESSAGE_OUTPUT_FAILED.value}
            failures.append(failure)
            # Diagnostic or notification failure must not escape into an ASR callback.
            try:
                errorLogging()
            except Exception:
                pass
            if current():
                try:
                    response = VRCTError.create_error_response(
                        ErrorCode.MESSAGE_OUTPUT_FAILED,
                        data={"id": msg_id, "source": spec.kind, **failure})
                    self.run(response["status"], self.run_mapping.get("message_output_error", "/run/message_output_error"),
                             response["result"])
                except Exception:
                    try:
                        errorLogging()
                    except Exception:
                        pass
            return False

    def _processMessage(
        self,
        spec: MessageDirectionSpec,
        message: str,
        language: Optional[str],
        msg_id: Optional[str] = None,
        asr_ms: Optional[int] = None,
        voice_generation: Optional[int] = None,
        publication_guard: Optional[Callable[[], bool]] = None,
        speech_update=None,
        mic_snapshot=None,
        settings_snapshot=None,
        chatbox_sequence=None,
        feature_enabled=None,
        output_progress=None,
    ) -> Optional[dict]:
        """mic/speaker/chatMessage共通のパイプライン(バックエンドレビュー
        フェーズ3項目25、`MessageDirectionSpec`参照)。

        「ワードフィルタ→繰り返し検出→翻訳→transliteration→OSC送信→
        オーバーレイ更新→(mic限定)クリップボード→UI配信→WebSocket送信→
        ロガー→履歴記録」を`spec`の差分だけで吸収する。呼び出し元は
        非空メッセージであることを保証してから呼ぶこと。

        `spec.delivery=="push"`の場合は内部で`self.run()`を呼び`None`を
        返す。`"return"`(chat)の場合は`{"id", "original", "translations"}`
        を返す(呼び出し元が`{"status":200,"result":...}`に包む)。
        ワードフィルタ・繰り返し検出・VRAMエラーで早期returnした場合は
        `model.addTranslationHistory`を呼ばない(旧実装の挙動を踏襲)。
        """
        current = self._messagePublicationGuard(spec.kind, publication_guard)
        # Internal capture pauses/handoffs keep admitted work. Explicit OFF
        # revokes its epoch instead of relying on a later live feature check.
        if feature_enabled is None:
            feature_enabled = spec.feature_gate_attr is None or getattr(config, spec.feature_gate_attr) is True
        if not current():
            return None
        with getattr(self, "_voice_settings_lock", nullcontext()), \
                getattr(self, "_language_settings_lock", nullcontext()):
            snapshot = settings_snapshot or MessageSnapshot.capture(config, spec, language)
            voice_snapshot = None
            if spec.kind == "chat" and getattr(self, "voice_events", None) is not None:
                if self.voice_events.settings.mode != "off":
                    voice_snapshot = (
                        snapshot, self.voice_events.settings,
                        voice_generation if type(voice_generation) is int else self.voice_events.generation())
        if chatbox_sequence is None and spec.osc_send_gate_attr is not None:
            chatbox_sequence = model.chatbox_order.admit()
        failures = []

        def sink(output, action):
            if trace is not None and output in ("osc", "tts"):
                action = self._tracedSink(trace, output, action)
            self._runMessageSink(output, (lambda: output_progress(action)) if output_progress else action,
                                 current, failures, spec, msg_id)

        if spec.has_word_filter and model.checkKeywords(message):
            if not current():
                return None
            self.run(
                200,
                self.run_mapping["word_filter"],
                {"message": f"Detected by word filter: {message}"},
            )
            return None

        if spec.repeat_detector_attr is not None and getattr(model, spec.repeat_detector_attr)(message):
            return None

        # 「発話終了から画面表示まで」の内訳を実測するための計装
        # (再評価 2026-09-14 M-1)。ワードフィルタ/繰り返し検出で早期 return
        # した場合は出力自体が無いので測らない。
        pipeline_started_at = time.perf_counter()
        translate_elapsed_ms = 0
        # Realtime mic intent is stamped before entering the session mailbox.
        # Typed chat carries the receiver's generation through translation.
        voice_started_ns = time.monotonic_ns()
        trace = self._beginIoTrace(spec, message, msg_id, voice_started_ns, asr_ms, speech_update)

        # Original speech has no dependency on the translator or text delivery.
        # The receiver's generation also invalidates chat waiting in Main.queue.
        if voice_snapshot is not None and voice_snapshot[1].mode == "original":
            sink("tts", lambda: self._publishChatVoice(
                voice_snapshot, message, [], [], [], msg_id, voice_started_ns, current))

        translation: list = []
        success: list = []
        provenance: list = []
        if snapshot.translation_enabled is False:
            pass
        else:
            translate_started_at = time.perf_counter()
            translation_completed = False
            try:
                translate = getattr(model, spec.translate_attr)
                translation, success, provenance = translate(
                    message, source_language=snapshot.source_language, snapshot=snapshot, with_provenance=True)
                if not current():
                    return None
                if all(success) is not True:
                    self.changeToCTranslate2Process(snapshot=snapshot)
                    error_response = VRCTError.create_error_response(
                        ErrorCode.TRANSLATION_ENGINE_LIMIT,
                        data=None
                    )
                    self.run(
                        error_response["status"],
                        self.run_mapping["error_translation_engine"],
                        error_response["result"],
                    )
                translation_completed = True
            except Exception as e:
                if not current():
                    return None
                # VRAM不足エラーの検出
                is_vram_error, error_message = model.detectVRAMError(e)
                if not is_vram_error:
                    # その他のエラーは通常通り処理
                    raise
                error_response = VRCTError.create_error_response(
                    spec.vram_error_code,
                    data=error_message
                )
                self.run(
                    error_response["status"],
                    self.run_mapping[spec.vram_run_mapping_key],
                    error_response["result"],
                )
                # 翻訳機能をOFFにする
                self.setDisableTranslation()
                disable_response = VRCTError.create_error_response(
                    ErrorCode.TRANSLATION_DISABLED_VRAM,
                    data=False
                )
                self.run(
                    disable_response["status"],
                    self.run_mapping["enable_translation"],
                    disable_response["result"],
                )
                if spec.delivery == "return":
                    # エラー時は翻訳なしで返す
                    return {
                        **({"delivery_outcome": "failed", "delivery_reason": "processing_failed"}
                           if spec in (REALTIME_MIC_SPEC, REALTIME_SPEAKER_SPEC) else {}),
                        "id": msg_id,
                        "original": {"message": message, "transliteration": []},
                        "translations": [
                            {"message": "", "transliteration": []}
                            for _ in snapshot.target_slots
                        ],
                    }
                return None
            finally:
                translate_elapsed_ms = round((time.perf_counter() - translate_started_at) * 1000)
                # Realtime expiry/stop can return inside this try. Keep slow
                # translation evidence even when publication is invalidated.
                if not translation_completed and spec.kind in ("mic", "speaker"):
                    self._recordMessageLatency(
                        spec, asr_ms, translate_elapsed_ms,
                        round((time.perf_counter() - pipeline_started_at) * 1000),
                        aborted=True,
                    )

        if not current():
            return None
        transliteration_message: List[Any] = []
        transliteration_translation = []
        if snapshot.hiragana or snapshot.romaji:
            own_language = (snapshot.your_languages["1"]["language"]
                            if spec.own_transliteration_source == "your_language"
                            else snapshot.source_language)
            if own_language == "Japanese":
                transliteration_message = model.convertMessageToTransliteration(
                    message, hiragana=snapshot.hiragana, romaji=snapshot.romaji)
        # Translation results are compacted to enabled slots, not fixed slot indices.
        for slot, text in zip(snapshot.target_slots, translation):
            if (snapshot.hiragana or snapshot.romaji) and snapshot.destinations[slot]["language"] == "Japanese":
                transliteration_translation.append(model.convertMessageToTransliteration(
                    text, hiragana=snapshot.hiragana, romaji=snapshot.romaji))
            else:
                transliteration_translation.append([])

        if not current():
            return None
        payload = {
            "original": {
                "message": message,
                "transliteration": transliteration_message
            },
            "translations": [
                {
                    "message": translation_message,
                    "transliteration": transliteration
                } for translation_message, transliteration in zip(translation, transliteration_translation)
            ]
        }
        # UIは source でメッセージの出自を見分ける (OCR由来にバッジを出す)。
        # id は UI 側で未指定ならUUIDが振られるが、ログとの突き合わせのため
        # 呼び出し元が持っていれば載せる。
        if spec.payload_source is not None:
            payload["source"] = spec.payload_source
        if msg_id is not None:
            payload = {"id": msg_id, **payload}

        if feature_enabled:
            def send_osc():
                if spec.osc_send_gate_attr is None:
                    return
                if not getattr(config, spec.osc_send_gate_attr):
                    # The user's own message stayed out of the chatbox by their setting.
                    # The row says so: "sent" alone would read as "it went to VRChat".
                    if spec.osc_format_type == "SEND":
                        payload["delivery_reason"] = "vrchat_off"
                    return
                original = "" if snapshot.send_only_translated and snapshot.translation_enabled else message
                formatted = self.messageFormatter(spec.osc_format_type, translation, original, snapshot.format_parts)
                osc_current = lambda: current() and getattr(config, spec.osc_send_gate_attr)
                sent = model.chatbox_order.send(
                    chatbox_sequence, lambda: model.oscSendMessage(formatted, current=osc_current), osc_current)
                if sent is False:
                    if spec is REALTIME_MIC_SPEC:
                        payload.update(delivery_outcome="not_delivered", delivery_reason="superseded")
                    printLog(f"[message][{spec.kind}] chatbox skipped: newer message already sent sequence={chatbox_sequence}")
                return sent

            sink("osc", send_osc)

            def small_overlay():
                if not (spec.render_overlay and spec.overlay_small_log and config.OVERLAY_SMALL_LOG
                        and self._is_overlay_available()):
                    return
                if snapshot.overlay_only_translated and not translation:
                    return
                overlay_current = model.overlayPublicationGuard("small", current)
                image = model.createOverlayImageSmallLog(
                    None if snapshot.overlay_only_translated else message,
                    None if snapshot.overlay_only_translated else snapshot.source_language,
                    translation, language_payload(snapshot.destinations),
                    transliteration_message, transliteration_translation)
                if current() and config.OVERLAY_SMALL_LOG:
                    model.updateOverlaySmallLog(image, current=overlay_current)

            sink("overlay_small", small_overlay)

            def large_overlay():
                if not (spec.render_overlay and config.OVERLAY_LARGE_LOG and self._is_overlay_available()):
                    return
                if snapshot.overlay_only_translated and not translation:
                    return
                model.publishMessageOverlayLargeLog(
                    spec.overlay_direction,
                    None if snapshot.overlay_only_translated else message,
                    None if snapshot.overlay_only_translated else snapshot.source_language,
                    translation, language_payload(snapshot.destinations),
                    transliteration_message, transliteration_translation,
                    current=lambda: current() and config.OVERLAY_LARGE_LOG)

            sink("overlay_large", large_overlay)

            def clipboard():
                if spec.clipboard and config.ENABLE_CLIPBOARD:
                    formatted = self.messageFormatter(spec.osc_format_type, translation, message, snapshot.format_parts)
                    if current() and config.ENABLE_CLIPBOARD:
                        return model.setCopyToClipboardAndPasteFromClipboard(formatted) is not False

            sink("clipboard", clipboard)
            if spec.delivery == "push":
                sink("ui", lambda: self.run(200, self.run_mapping[spec.run_mapping_key], payload))

            def websocket():
                if model.checkWebSocketServerAlive() is True and current():
                    return model.websocketSendMessage({
                        "type": spec.ws_type,
                        "src_languages": language_payload(snapshot.your_languages if spec.multi_target else snapshot.target_languages),
                        "dst_languages": language_payload(snapshot.destinations),
                        "message": message, "translation": translation,
                        "transliteration": transliteration_translation,
                    }) is not False

            sink("websocket", websocket)

            def logger():
                if config.LOGGER_FEATURE:
                    translation_text = f" ({'/'.join(translation)})" if translation else ""
                    model.logger.info(f"{spec.logger_prefix} {message}{translation_text}")
                    return True

            sink("logger", logger)

        if not current():
            return None
        sink("history", lambda: model.addTranslationHistory(spec.kind, message, snapshot=snapshot))

        if voice_snapshot is not None and voice_snapshot[1].mode == "translated":
            sink("tts", lambda: self._publishChatVoice(
                voice_snapshot, message, translation, success, provenance, msg_id, voice_started_ns, current))
        if mic_snapshot is not None:
            sink("tts", lambda: self._publishMicVoice(
                mic_snapshot, snapshot, speech_update, translation, success, provenance, current))
        if failures:
            payload["output_failures"] = list(failures)

        pipeline_elapsed_ms = round((time.perf_counter() - pipeline_started_at) * 1000)
        self._recordMessageLatency(spec, asr_ms, translate_elapsed_ms, pipeline_elapsed_ms)
        if trace is not None:
            self._publishIoTrace(trace, translation if snapshot.translation_enabled is not False else None,
                                 translate_elapsed_ms, pipeline_elapsed_ms - translate_elapsed_ms, failures)

        if spec.delivery == "return":
            return {"id": msg_id, **payload}
        return None

    # --- The flow panel: where the user's own messages go, and how long each step took (ms).

    def _ioTraceEmit(self, payload):
        # A readout never stops the message it describes, nor the speech that follows.
        try:
            self.run(200, "/run/io_trace", payload)
        except Exception:
            try:
                errorLogging()
            except Exception:
                pass

    def _beginIoTrace(self, spec, message, msg_id, started_ns, asr_ms, speech_update):
        traces = getattr(self, "io_traces", None)
        if traces is None or spec not in (MIC_MESSAGE_SPEC, REALTIME_MIC_SPEC, CHAT_MESSAGE_SPEC):
            return None
        trace_id = msg_id if msg_id is not None else uuid4()
        if spec is CHAT_MESSAGE_SPEC:
            return traces.begin(trace_id, "chat", message, "send", started_ns)
        received = getattr(speech_update, "received_ns", None)
        if type(received) is int and 0 < received <= started_ns:
            trace = traces.begin(trace_id, "voice", message, "final", received)
            trace.stage("wait", (started_ns - received) / 1e6)
            return trace
        if isinstance(asr_ms, (int, float)) and not isinstance(asr_ms, bool) and asr_ms >= 0:
            trace = traces.begin(trace_id, "voice", message, "recognition", started_ns - int(asr_ms * 1e6))
            trace.stage("recognition", asr_ms)
            return trace
        return traces.begin(trace_id, "voice", message, "received", started_ns)

    @staticmethod
    def _tracedSink(trace, output, action):
        def traced():
            result = action()
            if output == "osc":
                state = {True: "sent", False: "superseded"}.get(result, "off")
                trace.output("chatbox", state, time.monotonic_ns() if state == "sent" else None)
            else:
                trace.speech_queued(result is True)
            return result
        return traced

    def _publishIoTrace(self, trace, translation, translate_ms, deliver_ms, failures):
        if translation is not None:
            trace.stage("translate", translate_ms)
            trace.translation = next((text for text in translation if isinstance(text, str) and text), "")
        trace.stage("deliver", deliver_ms)
        for failure in failures:
            name = {"osc": "chatbox", "tts": "speech"}.get(failure.get("output"))
            if name is not None:
                trace.output(name, "failed")
        self.io_traces.publish(trace)

    def _ioSpeechStarted(self, event, timestamp_ns, converted):
        # TTS worker thread. The conversion's round trip is its recent median, a guide only.
        conversion_ms = self.direct_voice.health().get("round_trip_ms") if converted else None
        self.io_traces.speech_started(event.event_id, timestamp_ns, converted=converted, conversion_ms=conversion_ms)

    def getIoFlow(self, *args, **kwargs) -> dict:
        tab = config.SELECTED_TAB_NO
        targets = config.SELECTED_TARGET_LANGUAGES.get(tab, {})
        enabled = [row.get("language") for _, row in sorted(targets.items()) if row.get("enable") is True]
        voice = self.voice_events.settings
        selected = targets.get(voice.target_slot, {})
        status = self.voice_events.status()
        direct = self.direct_voice.health()
        with self._realtime_lock:
            realtime_requested = self._realtime_requested["mic"]
        state = dict(
            mic_on=config.ENABLE_TRANSCRIPTION_SEND is True or realtime_requested,
            realtime=self._realtimeToggles(), engine=config.SELECTED_TRANSCRIPTION_ENGINE,
            translation=config.ENABLE_TRANSLATION is True,
            source_language=config.SELECTED_YOUR_LANGUAGES.get(tab, {}).get("1", {}).get("language"),
            targets=enabled,
            speech_language=selected.get("language") if selected.get("enable") is True else None,
            send_to_vrc=config.SEND_MESSAGE_TO_VRC is True,
            only_translated=config.SEND_ONLY_TRANSLATED_MESSAGES is True,
            desktop=config.OVERLAY_DESKTOP is True, large_log=config.OVERLAY_LARGE_LOG is True,
            clipboard=config.ENABLE_CLIPBOARD is True,
            websocket=model.checkWebSocketServerAlive() is True,
            voice=voice.to_dict(), tts_enabled=status["tts_enabled"] is True, muted=status["muted"] is True,
            direct=dict(mode=direct["mode"], active=direct["active"] is True,
                        engine=self._direct_engine if direct["mode"] == "converted" else None),
            round_trip_ms=direct.get("round_trip_ms"),
        )
        return {"status": 200, "result": describe_io_flow(state)}

    @staticmethod
    def _recordMessageLatency(spec, asr_ms, translate_elapsed_ms, pipeline_elapsed_ms, *, aborted=False):
        # total は従来通り ASR + 出力処理。録音/VAD/キュー待ちは含まない。
        # realtime の ASR 所要時間はサーバーから提供されない。
        asr_part = f"asr={asr_ms}ms " if asr_ms is not None else ""
        total_ms = pipeline_elapsed_ms + (asr_ms or 0)
        detail = (
            f"[latency][{spec.kind}] {asr_part}"
            f"translate={translate_elapsed_ms}ms "
            f"output={pipeline_elapsed_ms - translate_elapsed_ms}ms "
            f"total={total_ms}ms"
        )
        if spec.kind not in ("mic", "speaker"):
            printLog(detail)
            return
        realtime = spec is REALTIME_MIC_SPEC or spec is REALTIME_SPEAKER_SPEC
        stages = {
            "realtime_translate_ms" if realtime else "translate_ms": translate_elapsed_ms,
            "output_ms": pipeline_elapsed_ms - translate_elapsed_ms,
        }
        if not realtime:
            stages["total_ms"] = total_ms
        utterance_diagnostics.record(
            spec.kind, "message_aborted" if aborted else "message", stages,
            detail + (" publication=aborted" if aborted else ""),
            immediate=asr_ms is not None and asr_ms >= SLOW_MS["asr_ms"],
        )

    def micMessage(self, result: dict) -> None:
        batch_guard = result.get("_publication_guard")
        current = self._messagePublicationGuard("mic", batch_guard)
        if (
            result.get("recognition_error") is not True
            and not current()
        ):
            return

        if result.get("recognition_error") is True:
            is_pipeline_error = all(
                key in result for key in ("error_code", "stage", "source", "message", "recoverable")
            )
            if is_pipeline_error:
                self._disableTranscriptionAfterPipelineError("mic")
                error_payload = {
                    "error_code": result["error_code"],
                    "stage": result["stage"],
                    "source": result["source"],
                    "message": result["message"],
                    "recoverable": result["recoverable"],
                }
            else:
                # 既存の recognition_error 通知を受ける呼び出し元との互換性を
                # 保つ。新しい音声パイプラインエラーは上の構造化 payload を使う。
                error_payload = {
                    "message": "Mic speech recognition request failed. Check your network connection.",
                    "data": None,
                }
            self.run(
                200,
                self.run_mapping["transcription_recognition_error"],
                error_payload,
            )
            return

        message = result["text"]
        language = result["language"]
        if isinstance(message, bool) and message is False:
            # Same shape as the energy meter's device error, so the UI shows
            # its translated message instead of a generic one.
            error_response = VRCTError.create_error_response(ErrorCode.DEVICE_NO_MIC, data=None)
            self.run(
                error_response["status"],
                self.run_mapping["error_device"],
                error_response["result"],
            )
        elif isinstance(message, str) and len(message) > 0:
            self._processMessage(MIC_MESSAGE_SPEC, message, language, asr_ms=result.get("asr_ms"),
                                 publication_guard=current, feature_enabled=True if batch_guard is not None else None)

    def speakerMessage(self, result:dict) -> None:
        batch_guard = result.get("_publication_guard")
        current = self._messagePublicationGuard("speaker", batch_guard)
        if result.get("recognition_error") is True:
            is_pipeline_error = all(
                key in result for key in ("error_code", "stage", "source", "message", "recoverable")
            )
            if is_pipeline_error:
                self._disableTranscriptionAfterPipelineError("speaker")
                error_payload = {
                    "error_code": result["error_code"],
                    "stage": result["stage"],
                    "source": result["source"],
                    "message": result["message"],
                    "recoverable": result["recoverable"],
                }
            else:
                error_payload = {
                    "message": "Speaker speech recognition request failed. Check your network connection.",
                    "data": None,
                }
            self.run(
                200,
                self.run_mapping["transcription_recognition_error"],
                error_payload,
            )
            return

        message = result["text"]
        language = result["language"]
        if isinstance(message, bool) and message is False:
            # Same shape as the energy meter's device error, so the UI shows
            # its translated message instead of a generic one.
            error_response = VRCTError.create_error_response(ErrorCode.DEVICE_NO_SPEAKER, data=None)
            self.run(
                error_response["status"],
                self.run_mapping["error_device"],
                error_response["result"],
            )
        elif isinstance(message, str) and len(message) > 0:
            self._processMessage(SPEAKER_MESSAGE_SPEC, message, language, asr_ms=result.get("asr_ms"),
                                 publication_guard=current, feature_enabled=True if batch_guard is not None else None)

    def ocrMessage(self, result: dict) -> bool:
        """OCRで読んだチャット吹き出しを、受信メッセージと同じ経路へ流す。

        speakerMessage と同じく `_processMessage` に委ねる。OCR固有の差分
        (OSCへ送らない、小さいオーバーレイを使わない、payloadに source="ocr" を
        載せる) は `OCR_MESSAGE_SPEC` 側に持たせている。

        OSCチャットボックスへは送らない。他人の発言を自分のチャットボックスへ
        流し返すことになり、スパムに当たるため (設定ではなく仕様で封じている)。
        """
        current = self._messagePublicationGuard("ocr")
        if getattr(self, "_ocr_shutting_down", False) or config.ENABLE_OCR_CAPTURE is not True:
            return False

        message = result.get("text")
        if not isinstance(message, str) or len(message) == 0:
            return False

        # 読んでいるのは相手の発言なので、翻訳の原文言語もそちら側。空なら
        # getOutputTranslate が SELECTED_TARGET_LANGUAGES へフォールバックする。
        # 自分の言語へフォールバックさせてはいけない (自分の言語から自分の言語への
        # 翻訳を頼むことになる)。
        language = result.get("language")
        source_language = language if isinstance(language, str) and len(language) > 0 else None

        segment_id = result.get("segment_id")
        msg_id = f"transcription-ocr-{segment_id}" if segment_id is not None else None
        self._processMessage(
            OCR_MESSAGE_SPEC, message, source_language, msg_id=msg_id,
            publication_guard=lambda: current() and not getattr(self, "_ocr_shutting_down", False),
        )
        return current() and not getattr(self, "_ocr_shutting_down", False)

    def _disableTranscriptionAfterPipelineError(self, source: str) -> None:
        if source not in ("mic", "speaker"):
            return
        with self._audioLock(source):
            self._disableTranscriptionAfterPipelineErrorLocked(source)

    def _disableTranscriptionAfterPipelineErrorLocked(self, source: str) -> None:
        transcript_flag, energy_flag = self._audioFlags(source)
        transcript_enabled = getattr(config, transcript_flag)
        energy_enabled = getattr(config, energy_flag)
        setattr(config, transcript_flag, False)
        setattr(config, energy_flag, False)
        if transcript_enabled:
            model.message_delivery.revoke(source)
        direction = "send" if source == "mic" else "receive"
        self.run(200, self.run_mapping.get("disable_transcription_" + direction,
                                         "/set/disable/transcription_" + direction), False)
        if energy_enabled:
            self.run(200, "/set/disable/check_" + source + "_threshold", False)
            self.run(200, "/run/check_" + source + "_volume", 0)

    @staticmethod
    def _voiceMonitorFailed(code):
        # Monitor thread; the code is a fixed identifier, never a device name.
        printLog("[voice] monitor output unavailable", code)

    def getVoiceSettings(self, *args, **kwargs) -> dict:
        return {"status": 200, "result": config.VOICE_SETTINGS}

    def _publishChatVoice(self, voice_snapshot, message, translations, success, provenance, msg_id, started_ns, current):
        snapshot, voice_settings, generation = voice_snapshot
        with self._voice_settings_lock:
            if current() and self.voice_events.settings == voice_settings:
                event = chat_event(
                    message, translations, success=success, provenance=provenance,
                    event_id=msg_id, started_ns=started_ns, source_language=snapshot.source_language,
                    targets=snapshot.target_languages, target_slots=snapshot.target_slots,
                    selected_slot=voice_settings.target_slot)
                if voice_settings.mode == "original" or event.translated_text is not None:
                    return self.voice_events.publish(event, expected_generation=generation)

    def _publishMicVoice(self, voice_snapshot, snapshot, update, translations, success, provenance, current):
        settings, generation, source_generation = voice_snapshot
        with self._voice_settings_lock:
            if (not current() or self.voice_events.settings != settings
                    or not config.ENABLE_TRANSLATION or config.SELECTED_TAB_NO != snapshot.tab):
                return
            # Text keeps its snapshot; speech also requires the selected target to remain current.
            if (config.SELECTED_TARGET_LANGUAGES.get(snapshot.tab, {}).get(settings.target_slot)
                    != snapshot.target_languages.get(settings.target_slot)):
                return
            usable = [ok is True and origin == "translated" for ok, origin in zip(success, provenance)]
            event = microphone_event(update, translations, usable, source_language=snapshot.source_language,
                                     targets=snapshot.target_languages, selected_slot=settings.target_slot)
            if event is not None:
                return self.voice_events.publish(event, expected_generation=generation,
                                                 expected_source_generation=source_generation)

    def _cancelMicVoice(self):
        bus = getattr(self, "voice_events", None)
        if bus is not None:
            bus.cancel_source("mic")

    def setVoiceSettings(self, data, *args, **kwargs) -> dict:
        with self._voice_settings_lock:
            try:
                settings = VoiceSettings.from_dict({**self.voice_events.settings.to_dict(), **data})
                if settings.routing == 'managed' and not sys.platform.startswith('linux'):
                    raise ValueError('managed_route_linux_only')
            except (ValueError, TypeError):
                return {"status": 400, "result": {"error_code": "VOICE_SETTINGS_INVALID",
                        "message": "Invalid voice settings; select an output and local server.", "data": None}}
            current = self.voice_events.settings
            device_route = self._directUsesOutputDevice()
            if (settings.routing != current.routing
                    or (device_route and settings.output_device != current.output_device)):
                direct = self.direct_voice.health()
                if direct['requested'] or direct['pending'] or direct.get('stopping'):
                    return {'status': 409, 'result': {'error_code': 'direct_voice_stop_required'}}
            try:
                # On Windows direct voice writes to the external output device.
                if settings.routing != 'managed' and not device_route:
                    self.direct_voice.stop()
                self.voice_route.configure(settings.routing == 'managed',
                    suppress_direct=self._gateSuppressesDirect(settings))
                self._applyDirectPolicy(settings)
            except RuntimeError as exc:
                return {'status': 409, 'result': {'error_code': str(exc)}}
            config.VOICE_SETTINGS = settings.to_dict()
            self.voice_events.configure(settings)
        return self.getVoiceSettings()

    def getVoiceStatus(self, *args, **kwargs) -> dict:
        # tts_server_starting: an ON request is waiting for a bundled server to load.
        return {"status": 200, "result": dict(self.voice_events.status(), tts_server_starting=self._tts_waiting > 0)}

    def getTtsModelOptions(self, data, *args, **kwargs) -> dict:
        if (not isinstance(data, dict) or set(data) not in ({'role'}, {'role', 'request_id'})
                or data['role'] not in ('japanese', 'multilingual')
                or ('request_id' in data and (not isinstance(data['request_id'], str)
                    or not 1 <= len(data['request_id']) <= 64
                    or not all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in data['request_id'])))):
            return {'status': 400, 'result': {'error_code': 'tts_role_invalid'}}
        role = data['role']
        with self._voice_settings_lock:
            settings = self.voice_events.settings
            server = getattr(settings, role + '_server')
            configured_url = getattr(settings, role + '_url')
            generation = self.speech_servers.state()[role]['generation'] if server == 'bundled' else None
        result = dict(role=role, server=server, configured_url=configured_url, server_generation=generation,
                      base_url=None, options=None, error_code=None)
        if 'request_id' in data:
            result['request_id'] = data['request_id']
        try:
            result['base_url'] = self._ttsSpeechServer(role) if server == 'bundled' else configured_url
            result['options'] = SpeechCppTTS(result['base_url']).get_model_options()
            if server == 'bundled' and self.speech_servers.state()[role]['generation'] != generation:
                raise SpeechError('tts_state_changed')
        except (ValueError, SpeechError) as exc:
            result['options'] = None
            result['error_code'] = str(exc) if isinstance(exc, SpeechError) else 'tts_model_options_unavailable'
        return {'status': 200, 'result': result}

    # A started server enforces its own START_TIMEOUT; this only bounds the
    # toggle's wait if that end state is somehow never published.
    _TTS_SERVER_WAIT = SPEECH_START_TIMEOUT + 5
    # Server failures with their own next step; the rest share a generic code.
    _TTS_START_FAILURES = ('speech_server_out_of_memory', 'speech_server_start_timeout',
                           'speech_server_low_latency_requires_gpu_irodori',
                           'speech_server_vulkan_missing', 'speech_server_device_failed')

    def enableTts(self, data, *args, **kwargs) -> dict:
        if (not isinstance(data, dict) or set(data) != {'generation'}
                or type(data.get('generation')) is not int or data['generation'] < 0):
            return {'status': 400, 'result': {'error_code': 'invalid_tts_toggle'}}
        attempt, started = Event(), {}
        with self._tts_owner_lock:
            self._tts_attempts.add(attempt)
        try:
            code = self._enableTts(data['generation'], attempt, started)
        finally:
            with self._tts_owner_lock:
                self._tts_attempts.discard(attempt)
        if code:
            # A failed or cancelled ON leaves no server of its own running.
            self._releaseTtsServers(only=started)
            # OFF during ON is the user's choice, not an error to report.
            return {'status': 409, 'result': {'error_code': 'tts_enable_cancelled' if attempt.is_set() else code}}
        return self.getVoiceStatus()

    def _enableTts(self, generation, attempt, started):
        with self._voice_settings_lock:
            code, roles = self._ttsRolesLocked(generation)
            if code:
                return code
            settings = self.voice_events.settings
            bundled = sorted(role for role in roles if getattr(settings, role + '_server') == 'bundled')
        if bundled:
            # Loading a model takes seconds. Wait without the settings lock so
            # saves and status polls are not blocked; OFF cancels the wait.
            code = self._awaitTtsServers(bundled, generation, attempt, started)
            if code:
                return code
        with self._voice_settings_lock:
            code, roles = self._ttsRolesLocked(generation)
            if code:
                return code
            settings = self.voice_events.settings
            try:
                urls = {self._ttsSpeechServer(role) if getattr(settings, role + '_server') == 'bundled'
                        else getattr(settings, role + '_url') for role in roles}
                for url in urls:
                    SpeechCppTTS(url).check_health()
            except SpeechError:
                # A stopped bundled server and an unreachable external URL both
                # need the user to start (or fix) the server for that language.
                return 'speech_server_not_ready'
            except (ValueError, KeyError, TypeError):
                return 'speech_server_or_settings_not_ready'
            # OFF bypasses this lock; the epoch must be rechecked after probing.
            return self._enableSpeechServerTts(roles, generation)

    def _ttsRolesLocked(self, generation, *, allow_muted=False):
        """Check selected roles at an epoch; allow mute only for end dependency checks."""
        state = self.voice_events.status()
        if generation != state['tts_generation']:
            return 'tts_state_changed', None
        # Name the blocking condition: the UI turns each code into its next step.
        if state['closed']:
            return 'voice_route_closed', None
        if state['muted'] and not allow_muted:
            return 'voice_route_muted', None
        settings = self.voice_events.settings
        if settings.mode == 'off' and settings.mic_mode == 'off':
            return 'tts_source_not_selected', None
        try:
            # Resolve only the selected sources/languages; do not require an
            # unused multilingual model to enable Japanese-only speech.
            languages = []
            cfg = self._config
            if settings.mode == 'original':
                languages.append(cfg.SELECTED_YOUR_LANGUAGES[cfg.SELECTED_TAB_NO]['1']['language'])
            if settings.mode == 'translated' or settings.mic_mode == 'translated':
                target = cfg.SELECTED_TARGET_LANGUAGES[cfg.SELECTED_TAB_NO][settings.target_slot]
                if not cfg.ENABLE_TRANSLATION or target.get('enable') is not True:
                    return 'tts_translation_not_ready', None
                languages.append(target['language'])
            from models.tts.settings import language_tag
            roles = set()
            for language in languages:
                try:
                    tag = language_tag(language)
                except ValueError:
                    return 'tts_language_unsupported', None
                roles.add('japanese' if tag == 'ja' else 'multilingual')
            # Checked before any server starts, so this never costs a model load.
            if not settings.playback_device.strip():
                return 'tts_output_missing', None
        except (KeyError, TypeError):
            return 'speech_server_or_settings_not_ready', None
        return None, roles

    def _awaitTtsServers(self, roles, generation, attempt, started):
        """Start stopped bundled servers for roles, then wait until all are ready."""
        state = self.speech_servers.state()
        for role in roles:
            row = state[role]
            if row['state'] in ('ready', 'preparing'):
                continue  # Started from Settings: wait for it, but never own it.
            if row['state'] == 'stopping':
                return 'speech_server_busy'
            try:
                options = speech_start_options(self.getSpeechServerSettings()['result'], role)
            except ValueError as exc:
                return 'speech_server_model_invalid' if str(exc) == 'speech_server_model_invalid' else 'speech_server_start_failed'
            with self._tts_owner_lock:
                # OFF takes this lock too: it either cancels first or sees ownership.
                if attempt.is_set():
                    return 'tts_enable_cancelled'
                try:
                    self.speech_servers.start(role, options, row['generation'])
                except RuntimeError as exc:
                    return 'speech_server_busy' if str(exc) == 'speech_server_busy' else 'speech_server_start_failed'
                # start() succeeds only from this generation and takes the next one.
                started[role] = self._tts_owned[role] = row['generation'] + 1
        with self._tts_owner_lock:
            self._tts_waiting += 1
        try:
            deadline = time.monotonic() + self._TTS_SERVER_WAIT
            while not attempt.is_set():
                state = self.speech_servers.state()
                rows = {role: state[role] for role in roles}
                # Report a failure before the TTS epoch bump that it causes.
                failed = [row['error_code'] for row in rows.values() if row['state'] == 'failed']
                if failed:
                    return failed[0] if failed[0] in self._TTS_START_FAILURES else 'speech_server_start_failed'
                if any(row['state'] in ('stopped', 'stopping') or row['generation'] != started.get(role, row['generation'])
                       for role, row in rows.items()):
                    return 'speech_server_not_ready'  # Stopped from Settings meanwhile.
                if all(row['state'] == 'ready' for row in rows.values()):
                    return None
                if self.voice_events.generation() != generation:
                    return 'tts_state_changed'
                if time.monotonic() >= deadline:
                    return 'speech_server_start_timeout'
                attempt.wait(.05)
            return 'tts_enable_cancelled'
        finally:
            with self._tts_owner_lock:
                self._tts_waiting -= 1

    def _releaseTtsServers(self, only=None, cancel=False):
        """Stop TTS servers the main toggle started; servers started from Settings stay up."""
        with self._tts_owner_lock:
            if cancel:
                for attempt in self._tts_attempts:
                    attempt.set()
            owned = {role: run for role, run in self._tts_owned.items() if only is None or only.get(role) == run}
            for role, run in owned.items():
                del self._tts_owned[role]
                # Match the immutable run, not the public Stop/end generation.
                # Its late end must not invalidate a quick OFF -> ON.
                self._tts_released[role] = run
        for role, run in owned.items():
            # Non-joining like stopSpeechServer; a newer run is left alone.
            if not self.speech_servers.stop(role, generation=run):
                with self._tts_owner_lock:
                    if self._tts_released.get(role) == run:
                        del self._tts_released[role]

    def disableTts(self, *args, **kwargs) -> dict:
        self.voice_events.set_enabled(False)
        # OFF also cancels an ON that is still waiting for its server.
        self._releaseTtsServers(cancel=True)
        return self.getVoiceStatus()

    @staticmethod
    def _directUsesOutputDevice():
        return sys.platform == 'win32'

    @staticmethod
    def _suppressesDirect(settings):
        return settings.mic_mode == 'translated' and settings.direct_policy == 'suppress'

    @classmethod
    def _gateSuppressesDirect(cls, settings):
        # Speech through the conversion leaves by the conversion's sink, so the OS gate
        # cannot silence that sink; the conversion silences the microphone's blocks itself.
        return cls._suppressesDirect(settings) and settings.conversion != 'on'

    def _applyDirectPolicy(self, settings):
        # The managed route does this with an OS gate; a device route has none.
        suppress, through = self._suppressesDirect(settings), settings.conversion == 'on'
        self.direct_voice.set_suppressed(self._directUsesOutputDevice() and suppress and not through)
        # Block by block, on either route, while speech goes through the conversion (ADR-007).
        self.direct_voice.set_direct_suppressed(suppress and through)

    def _directOutput(self, mode, options):
        """Device for a Windows Start; None on Linux, where the managed route decides."""
        settings = self.voice_events.settings
        if not self._directUsesOutputDevice():
            if not sys.platform.startswith('linux'):
                raise RuntimeError('source_bridge_linux_only')
            if settings.routing != 'managed':
                raise RuntimeError('source_bridge_managed_required')
            return None
        if not settings.output_device:
            raise RuntimeError('source_bridge_output_required')
        return settings.output_device

    def getDirectVoiceSources(self, *args, **kwargs) -> dict:
        try:
            sources, error = enumerate_sources(), None
        except Exception:
            sources = []
            error = ('source_bridge_devices_unavailable' if self._directUsesOutputDevice()
                     else 'source_bridge_linux_only' if not sys.platform.startswith('linux')
                     else 'source_bridge_graph_unavailable')
        return {'status': 200, 'result': {'sources': sources, 'error': error,
                                          'preferred': self._preferredDirectSource(sources)}}

    def _preferredDirectSource(self, sources):
        """The Device page Mic choice is the default RVC input; the UI applies it
        only while the user has not picked another input on the RVC page."""
        selected = getattr(config, 'SELECTED_MIC_DEVICE', None)
        names = microphone_names(sources)
        if not self._directUsesOutputDevice():
            if getattr(config, 'SELECTED_MIC_HOST', None) != PIPEWIRE_MIC_HOST:
                return None
            return next((item['id'] for item, name in zip(sources, names) if name == selected), None)
        # The Device page defaults to MME; its choice is the same hardware under a cut name.
        match = next((item['id'] for item, name in zip(sources, names)
                      if isinstance(selected, str) and same_output(name, selected)), None)
        if match is not None or not sources:
            return match
        try:
            default = default_endpoint('mic').name
        except ValueError:
            return None
        return next((item['id'] for item in sources if item['id']['name'] == default), None)

    def getDirectVoiceState(self, *args, **kwargs) -> dict:
        state = self.direct_voice.health()
        # The VC router's stderr is not kept; log each new monitor code once here.
        code = state.get('monitor_error')
        if code and code != getattr(self, '_vc_monitor_logged', None):
            self._voiceMonitorFailed(code)
        self._vc_monitor_logged = code
        return {'status': 200, 'result': dict(state, settings=self._direct_settings.to_dict(),
                                              output_route='device' if self._directUsesOutputDevice() else 'managed')}

    def setDirectVoiceSettings(self, data, *args, **kwargs) -> dict:
        try:
            settings = DirectSettings.from_dict(data)
        except ValueError:
            return {'status': 400, 'result': {'error_code': 'vc_settings_invalid'}}
        with self._voice_settings_lock:
            state = self.direct_voice.health()
            if self._direct_voice_closed or state['requested'] or state['pending']:
                return {'status': 409, 'result': {'error_code': 'vc_stop_required'}}
            # Saving new intent invalidates any Start queued before the change.
            self.direct_voice.stop()
            self._config.DIRECT_VOICE_SETTINGS = settings.to_dict()
            self._direct_settings = settings
        return self.getDirectVoiceState()

    def startDirectVoice(self, data, *args, **kwargs) -> dict:
        try:
            if not isinstance(data, dict) or type(data.get('_direct_generation')) is not int:
                raise ValueError('source_bridge_source_invalid')
            source = parse_source(data.get('source'))
            mode = data.get('mode', 'passthrough')
            options = start_options(mode, data.get('options'))
        except ValueError:
            return {'status': 400, 'result': {'error_code': 'source_bridge_source_invalid'}}
        with self._voice_settings_lock:
            try:
                if self._direct_voice_closed:
                    raise RuntimeError('source_bridge_closed')
                output = self._directOutput(mode, options)
                # One monitor setting covers TTS and converted voice; passthrough is never monitored.
                monitor = monitor_spec(self.voice_events.settings.monitor_choice) if mode == 'converted' else None
                extra = {} if output is None else {'output': output}
                self.direct_voice.start(source=source, expected_generation=data['_direct_generation'],
                                        mode=mode, options=options, monitor=monitor, **extra)
                self._direct_engine = options.get('engine') if mode == 'converted' else None
            except RuntimeError as exc:
                return {'status': 409, 'result': {'error_code': str(exc)}}
        return self.getDirectVoiceState()

    def stopDirectVoice(self, *args, **kwargs) -> dict:
        # Receiver fast path: no settings lock, graph query, or worker join.
        self.direct_voice.stop()
        return self.getDirectVoiceState()

    def getVoiceRoute(self, *args, **kwargs) -> dict:
        return {'status': 200, 'result': dict(self.voice_route.status(),
                                              covers_direct=self._directUsesOutputDevice())}

    def muteVoice(self, *args, **kwargs) -> dict:
        self.voice_route.mute()
        return self.getVoiceRoute()

    def resumeVoice(self, *args, **kwargs) -> dict:
        try:
            self.voice_route.resume()
        except RuntimeError as exc:
            return {'status': 409, 'result': {'error_code': str(exc)}}
        return self.getVoiceRoute()

    def getVoiceOutputDevices(self, *args, **kwargs) -> dict:
        try:
            settings = self.voice_events.settings
            devices = enumerate_outputs((settings.output_device, settings.monitor_device))
            return {"status": 200, "result": {"devices": devices, "error": None}}
        except Exception:
            return {"status": 200, "result": {"devices": [], "error": "audio_devices_unavailable"}}

    def stopVoice(self, *args, **kwargs) -> dict:
        self.voice_events.cancel()
        return self.getVoiceStatus()

    def chatMessage(self, data) -> dict:
        current = self._messagePublicationGuard("chat")
        if not current():
            return {"status": 200, "result": None}
        msg_id = data["id"]
        message = data["message"]
        if len(message) == 0:
            # 既知のバグ修正: 以前はここで translation/transliteration_* が
            # 未初期化のまま戻り値の構築に使われ UnboundLocalError になっていた。
            model.addTranslationHistory("chat", message)
            return {
                "status": 200,
                "result": {
                    "id": msg_id,
                    "original": {"message": message, "transliteration": []},
                    "translations": []
                },
            }
        result = self._processMessage(CHAT_MESSAGE_SPEC, message, None, msg_id=msg_id,
                                      voice_generation=data.get("_voice_generation"), publication_guard=current)
        return {"status": 200, "result": result}


    def checkSoftwareUpdated(self) -> dict:
        software_update_info = model.checkSoftwareUpdated()
        self.run(
            200,
            self.run_mapping["software_update_info"],
            software_update_info,
        )
        return {"status":200, "result": software_update_info}




    def setSelectedTranslationComputeDevice(self, device:str, *args, **kwargs) -> dict:
        printLog("setSelectedTranslationComputeDevice", device)
        config.SELECTED_TRANSLATION_COMPUTE_DEVICE = device
        config.SELECTED_TRANSLATION_COMPUTE_TYPE = "auto"
        self.run(200, self.run_mapping["selected_translation_compute_type"], config.SELECTED_TRANSLATION_COMPUTE_TYPE)
        model.setChangedTranslatorParameters(True)
        return {"status":200,"result":config.SELECTED_TRANSLATION_COMPUTE_DEVICE}



    def setSelectedTranscriptionComputeDevice(self, device:str, *args, **kwargs) -> dict:
        printLog("setSelectedTranscriptionComputeDevice", device)
        config.SELECTED_TRANSCRIPTION_COMPUTE_DEVICE = device
        config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE = "auto"
        self.run(200, self.run_mapping["selected_transcription_compute_type"], config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE)
        return {"status":200,"result":config.SELECTED_TRANSCRIPTION_COMPUTE_DEVICE}

    @staticmethod
    def getSelectableWhisperWeightTypeDict(*args, **kwargs) -> dict:
        return {"status":200, "result":config.SELECTABLE_WHISPER_WEIGHT_TYPE_DICT}

    # @staticmethod
    # def getMaxMicThreshold(*args, **kwargs) -> dict:
    #     return {"status":200, "result":config.MAX_MIC_THRESHOLD}

    # @staticmethod
    # def getMaxSpeakerThreshold(*args, **kwargs) -> dict:
    #     return {"status":200, "result":config.MAX_SPEAKER_THRESHOLD}

    def setEnableTranslation(self, *args, **kwargs) -> dict:
        if config.ENABLE_TRANSLATION is False:
            engine = config.SELECTED_TRANSLATION_ENGINES[config.SELECTED_TAB_NO]
            if (engine != "CTranslate2" and
                    config.SELECTABLE_TRANSLATION_ENGINE_STATUS.get(engine) is True and
                    config.SELECTABLE_TRANSLATION_ENGINE_STATUS.get("CTranslate2") is False):
                # A connected external provider does not require local weights.
                # Keep the legacy warm fallback when CTranslate2 is available.
                config.ENABLE_TRANSLATION = True
                return {"status": 200, "result": True}
            if model.isLoadedCTranslate2Model() is False or model.isChangedTranslatorParameters() is True:
                try:
                    model.changeTranslatorCTranslate2Model()
                    model.setChangedTranslatorParameters(False)
                    config.ENABLE_TRANSLATION = True
                except Exception as e:
                    # VRAM不足エラーの検出（デバイス切り替え時）
                    is_vram_error, error_message = model.detectVRAMError(e)
                    if is_vram_error:
                        # Defaultのデバイス設定に戻す
                        printLog("VRAM error detected, reverting device setting")
                        error_response = VRCTError.create_error_response(
                            ErrorCode.TRANSLATION_VRAM_ENABLE,
                            data=error_message
                        )
                        self.run(
                            error_response["status"],
                            self.run_mapping["error_translation_enable_vram_overflow"],
                            error_response["result"],
                        )
                        self.setDisableTranslation()
                        disable_response = VRCTError.create_error_response(
                            ErrorCode.TRANSLATION_DISABLED_VRAM,
                            data=False
                        )
                        self.run(
                            disable_response["status"],
                            self.run_mapping["enable_translation"],
                            disable_response["result"],
                        )
                        model.changeTranslatorCTranslate2Model()
                        model.setChangedTranslatorParameters(False)
                    else:
                        # 理由を返す。False だけを返すと、画面ではスイッチが戻るだけで何も分からない
                        missing = (isinstance(e, MissingCTranslate2Tokenizer) or
                                   not model.hasTranslatorCTranslate2ModelWeightFile(config.CTRANSLATE2_WEIGHT_TYPE))
                        if not missing:
                            # A model that was never downloaded is where every new user starts, and the
                            # UI answers it with the download review. Only a load that failed is logged.
                            errorLogging()
                        return VRCTError.create_error_response(
                            ErrorCode.TRANSLATION_MODEL_MISSING if missing else ErrorCode.TRANSLATION_MODEL_LOAD_FAILED,
                            data=False,
                        )
            else:
                config.ENABLE_TRANSLATION = True
        return {"status":200, "result":config.ENABLE_TRANSLATION}

    def setDisableTranslation(self, *args, **kwargs) -> dict:
        with getattr(self, "_voice_settings_lock", nullcontext()):
            self._cancelMicVoice()
            config.ENABLE_TRANSLATION = False
        return {"status":200, "result":config.ENABLE_TRANSLATION}

    @staticmethod
    def setEnableForeground(*args, **kwargs) -> dict:
        if config.ENABLE_FOREGROUND is False:
            config.ENABLE_FOREGROUND = True
        return {"status":200, "result":config.ENABLE_FOREGROUND}

    @staticmethod
    def setDisableForeground(*args, **kwargs) -> dict:
        if config.ENABLE_FOREGROUND is True:
            config.ENABLE_FOREGROUND = False
        return {"status":200, "result":config.ENABLE_FOREGROUND}


    def setSelectedTabNo(self, selected_tab_no:str, *args, **kwargs) -> dict:
        printLog("setSelectedTabNo", selected_tab_no)
        with getattr(self, "_voice_settings_lock", nullcontext()), \
                getattr(self, "_language_settings_lock", nullcontext()):
            self._cancelMicVoice()
            config.SELECTED_TAB_NO = selected_tab_no
            self.updateTranslationEngineAndEngineList()
        return {"status":200, "result":config.SELECTED_TAB_NO}

    @staticmethod
    def getTranslationEngines(*args, **kwargs) -> dict:
        engines = model.findTranslationEngines(
            config.SELECTED_YOUR_LANGUAGES[config.SELECTED_TAB_NO],
            config.SELECTED_TARGET_LANGUAGES[config.SELECTED_TAB_NO],
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS,
            )

        your_language = config.SELECTED_YOUR_LANGUAGES[config.SELECTED_TAB_NO]["1"]
        for target_language in config.SELECTED_TARGET_LANGUAGES[config.SELECTED_TAB_NO].values():
            if your_language["language"] == target_language["language"] and target_language["enable"] is True:
                if config.SELECTABLE_TRANSLATION_ENGINE_STATUS["CTranslate2"] is True:
                    engines = ["CTranslate2"]
                else:
                    engines = []

        return {"status":200, "result":engines}

    @staticmethod
    def getListLanguageAndCountry(*args, **kwargs) -> dict:
        return {"status":200, "result": model.getListLanguageAndCountry()}

    @staticmethod
    def getMicHostList(*args, **kwargs) -> dict:
        return {"status":200, "result": model.getListMicHost()}

    @staticmethod
    def getMicDeviceList(*args, **kwargs) -> dict:
        return {"status":200, "result": model.getListMicDevice()}

    @staticmethod
    def getSpeakerDeviceList(*args, **kwargs) -> dict:
        return {"status":200, "result": model.getListSpeakerDevice()}


    def setSelectedTranslationEngines(self, data:dict, *args, **kwargs) -> dict:
        with getattr(self, "_voice_settings_lock", nullcontext()), \
                getattr(self, "_language_settings_lock", nullcontext()):
            try:
                config.SELECTED_TRANSLATION_ENGINES = data
            except ConfigValidationError:
                return VRCTError.create_error_response(
                    ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                    data=config.SELECTED_TRANSLATION_ENGINES,
                )
            self._cancelMicVoice()
            self.updateTranslationEngineAndEngineList()
            return {"status":200, "result":config.SELECTED_TRANSLATION_ENGINES}


    def setSelectedYourLanguages(self, select:dict, *args, **kwargs) -> dict:
        with getattr(self, "_voice_settings_lock", nullcontext()), \
                getattr(self, "_language_settings_lock", nullcontext()):
            try:
                config.SELECTED_YOUR_LANGUAGES = select
            except ConfigValidationError:
                return VRCTError.create_error_response(
                    ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                    data=config.SELECTED_YOUR_LANGUAGES,
                )
            self._cancelMicVoice()
            self.updateTranslationEngineAndEngineList()
            return {"status":200, "result":config.SELECTED_YOUR_LANGUAGES}


    def setSelectedTargetLanguages(self, select:dict, *args, **kwargs) -> dict:
        with getattr(self, "_voice_settings_lock", nullcontext()), \
                getattr(self, "_language_settings_lock", nullcontext()):
            try:
                config.SELECTED_TARGET_LANGUAGES = select
            except ConfigValidationError:
                return VRCTError.create_error_response(
                    ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                    data=config.SELECTED_TARGET_LANGUAGES,
                )
            self._cancelMicVoice()
            self.updateTranslationEngineAndEngineList()
            return {"status":200, "result":config.SELECTED_TARGET_LANGUAGES}


    @staticmethod
    def getTranscriptionEngines(*args, **kwargs) -> dict:
        engines = [key for key, value in config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS.items() if value is True]
        return {"status":200, "result":engines}


    def setSelectedTranscriptionEngine(self, data, *args, **kwargs) -> dict:
        # setSelectedTranslationEngines() -> updateTranslationEngineAndEngineList()
        # と同じパターン: 希望値をまず渡し、言語フォールバック・
        # 言語リストのpushは updateTranscriptionEngine() 側に集約する。
        self.updateTranscriptionEngine(requested_engine=str(data))
        return {"status":200, "result":config.SELECTED_TRANSCRIPTION_ENGINE}

    def fallbackUnsupportedLanguagesForTranscriptionEngine(self, engine: str) -> bool:
        """文字起こしエンジンが切り替わった際、既に選択されている言語が
        新しいエンジンで対応していなければデフォルト言語 (日本語/英語) へ
        リセットする (翻訳側の fallbackUnsupportedLanguagesForEngine の
        文字起こしエンジン版)。

        SELECTED_TRANSCRIPTION_ENGINE はタブ横断のグローバル設定
        (SELECTED_TRANSLATION_ENGINES と違いタブごとではない) なので、
        全タブについて確認する。

        Returns True if any language was reset.
        """
        changed = False

        your_languages = copy.deepcopy(config.SELECTED_YOUR_LANGUAGES)
        target_languages = copy.deepcopy(config.SELECTED_TARGET_LANGUAGES)

        for tab_no in your_languages.keys():
            your_language = your_languages[tab_no]["1"]
            enabled_target_languages = {
                target_language["language"]
                for target_language in target_languages.get(tab_no, {}).values()
                if target_language["enable"] is True
            }
            if not model.isLanguageSupportedByTranscriptionEngine(engine, your_language["language"], your_language["country"]):
                default = model.pickDefaultLanguageAndCountryForTranscriptionEngine(engine, enabled_target_languages)
                if default is not None:
                    your_languages[tab_no]["1"] = {**default, "enable": True}
                    changed = True
                    your_language = your_languages[tab_no]["1"]

            taken_languages = {your_language["language"]}
            for target_language in target_languages.get(tab_no, {}).values():
                if target_language["enable"] is not True:
                    continue
                if model.isLanguageSupportedByTranscriptionEngine(engine, target_language["language"], target_language["country"]):
                    taken_languages.add(target_language["language"])
                    continue
                default = model.pickDefaultLanguageAndCountryForTranscriptionEngine(engine, taken_languages)
                if default is not None:
                    target_language["language"] = default["language"]
                    target_language["country"] = default["country"]
                    changed = True
                taken_languages.add(target_language["language"])

        if changed:
            config.SELECTED_YOUR_LANGUAGES = your_languages
            config.SELECTED_TARGET_LANGUAGES = target_languages
            self.run(200, self.run_mapping["selected_your_languages"], config.SELECTED_YOUR_LANGUAGES)
            self.run(200, self.run_mapping["selected_target_languages"], config.SELECTED_TARGET_LANGUAGES)

        return changed

    # ------------------------------------------------------------------
    # Transcription API engines (Groq Whisper / OpenAI Whisper / カスタムサーバー)
    #
    # 翻訳側のエンジンと違い、文字起こし側にはエンジンごとの永続クライアント
    # オブジェクトが存在しない (AudioTranscriber がセッション開始のたびに
    # config の現在値からプロバイダを都度組み立てる設計のため、
    # model.updateTranslatorXClient() に相当する呼び出しは不要)。
    # モデル選択の検証も、翻訳側のようにクライアントへ問い合わせる
    # model.setTranslatorXModel(...) 相当は行わず、
    # SELECTABLE_*_MODEL_LIST に含まれているかどうかだけで判定する。
    # ------------------------------------------------------------------
    def _setTranscriptionCredential(self, engine, data, base_url=None):
        printLog(f"Set {engine} Auth Key")
        prefix = engine.upper()
        try:
            data = str(data).strip()
            if not data:
                raise ValueError("Empty credential")
            if engine == "Deepgram":
                if model.authenticationDeepgramApiKey(api_key=data) is not True:
                    raise ValueError("Credential authentication failed")
                models_detailed = model.getDeepgramModelListDetailed(api_key=data)
                model_list = [item["name"] for item in models_detailed]
                languages = {item["name"]: item["languages"] for item in models_detailed}
            else:
                if model.authenticationTranscriptionApiKey(api_key=data, base_url=base_url) is not True:
                    raise ValueError("Credential authentication failed")
                filters = {} if engine == "Custom_Whisper" else {"keyword_filter": TRANSCRIPTION_MODEL_KEYWORDS}
                model_list = model.getTranscriptionApiModelList(api_key=data, base_url=base_url, **filters)
            if not isinstance(model_list, list) or not model_list or any(
                not isinstance(name, str) or not name.strip() for name in model_list
            ):
                raise ValueError("No supported models available")
            model_list = list(model_list)
            selected_model = getattr(config, f"SELECTED_{prefix}_MODEL")
            if selected_model not in model_list:
                selected_model = model_list[0]
        except Exception:
            errorLogging(provider=engine)
            return VRCTError.create_error_response(
                ErrorCode.TRANSCRIPTION_API_AUTH_FAILED,
                data=config.TRANSCRIPTION_AUTH_KEYS.get(engine),
            )
        with config.credential_lock:
            if engine == "Custom_Whisper" and config.TRANSCRIPTION_CUSTOM_URL != base_url:
                return VRCTError.create_error_response(
                    ErrorCode.TRANSCRIPTION_API_AUTH_FAILED,
                    data=config.TRANSCRIPTION_AUTH_KEYS.get(engine),
                )
            config.updateCredential("TRANSCRIPTION_AUTH_KEYS", engine, data)
            setattr(config, f"SELECTABLE_{prefix}_MODEL_LIST", model_list)
            setattr(config, f"SELECTED_{prefix}_MODEL", selected_model)
            if engine == "Deepgram":
                config.DEEPGRAM_MODEL_LANGUAGES = languages
            config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = True
            self.run(200, self.run_mapping[f"selectable_{engine.lower()}_model_list"], model_list)
            self.run(200, self.run_mapping[f"selected_{engine.lower()}_model"], selected_model)
            self.updateTranscriptionEngine()
        return {"status": 200, "result": data}

    @staticmethod
    def getGroqWhisperAuthKey(*args, **kwargs) -> dict:
        return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS["Groq_Whisper"]}

    def setGroqWhisperAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranscriptionCredential("Groq_Whisper", data, base_url=config.GROQ_WHISPER_BASE_URL)

    def delGroqWhisperAuthKey(self, *args, **kwargs) -> dict:
        with config.credential_lock:
            engine = "Groq_Whisper"
            config.updateCredential("TRANSCRIPTION_AUTH_KEYS", engine, None)
            config.SELECTABLE_GROQ_WHISPER_MODEL_LIST = []
            config.SELECTED_GROQ_WHISPER_MODEL = None
            self.run(200, self.run_mapping["selectable_groq_whisper_model_list"], config.SELECTABLE_GROQ_WHISPER_MODEL_LIST)
            self.run(200, self.run_mapping["selected_groq_whisper_model"], config.SELECTED_GROQ_WHISPER_MODEL)
            config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = False
            self.updateTranscriptionEngine()
            return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS[engine]}


    @staticmethod
    def setGroqWhisperModel(data, *args, **kwargs) -> dict:
        printLog("Set Groq Whisper Model", data)
        data = str(data)
        if data in config.SELECTABLE_GROQ_WHISPER_MODEL_LIST:
            config.SELECTED_GROQ_WHISPER_MODEL = data
            return {"status":200, "result":config.SELECTED_GROQ_WHISPER_MODEL}
        return VRCTError.create_error_response(
            ErrorCode.MODEL_TRANSCRIPTION_INVALID,
            data=config.SELECTED_GROQ_WHISPER_MODEL
        )

    @staticmethod
    def getOpenAIWhisperAuthKey(*args, **kwargs) -> dict:
        return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS["OpenAI_Whisper"]}

    def setOpenAIWhisperAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranscriptionCredential("OpenAI_Whisper", data, base_url=config.OPENAI_WHISPER_BASE_URL)

    def delOpenAIWhisperAuthKey(self, *args, **kwargs) -> dict:
        with config.credential_lock:
            engine = "OpenAI_Whisper"
            config.updateCredential("TRANSCRIPTION_AUTH_KEYS", engine, None)
            config.SELECTABLE_OPENAI_WHISPER_MODEL_LIST = []
            config.SELECTED_OPENAI_WHISPER_MODEL = None
            self.run(200, self.run_mapping["selectable_openai_whisper_model_list"], config.SELECTABLE_OPENAI_WHISPER_MODEL_LIST)
            self.run(200, self.run_mapping["selected_openai_whisper_model"], config.SELECTED_OPENAI_WHISPER_MODEL)
            config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = False
            self.updateTranscriptionEngine()
            return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS[engine]}


    @staticmethod
    def setOpenAIWhisperModel(data, *args, **kwargs) -> dict:
        printLog("Set OpenAI Whisper Model", data)
        data = str(data)
        if data in config.SELECTABLE_OPENAI_WHISPER_MODEL_LIST:
            config.SELECTED_OPENAI_WHISPER_MODEL = data
            return {"status":200, "result":config.SELECTED_OPENAI_WHISPER_MODEL}
        return VRCTError.create_error_response(
            ErrorCode.MODEL_TRANSCRIPTION_INVALID,
            data=config.SELECTED_OPENAI_WHISPER_MODEL
        )

    @staticmethod
    def getCustomWhisperAuthKey(*args, **kwargs) -> dict:
        return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS["Custom_Whisper"]}

    def setCustomWhisperAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranscriptionCredential("Custom_Whisper", data, base_url=config.TRANSCRIPTION_CUSTOM_URL)

    def setCustomWhisperAuthKeyAndURL(self, data, *args, **kwargs) -> dict:
        return self._setEndpointCredential("Custom_Whisper", data)

    def delCustomWhisperAuthKey(self, *args, **kwargs) -> dict:
        with config.credential_lock:
            engine = "Custom_Whisper"
            config.updateCredential("TRANSCRIPTION_AUTH_KEYS", engine, None)
            config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST = []
            config.SELECTED_CUSTOM_WHISPER_MODEL = None
            self.run(200, self.run_mapping["selectable_custom_whisper_model_list"], config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST)
            self.run(200, self.run_mapping["selected_custom_whisper_model"], config.SELECTED_CUSTOM_WHISPER_MODEL)
            config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = False
            self.updateTranscriptionEngine()
            return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS[engine]}


    def setCustomWhisperURL(self, data, *args, **kwargs) -> dict:
        """Require explicit key entry before changing a credential's destination."""
        try:
            data = validate_api_url(data.strip() if isinstance(data, str) else data)
        except ValueError:
            return VRCTError.create_error_response(
                ErrorCode.CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID, data=config.TRANSCRIPTION_CUSTOM_URL)
        printLog("Set Custom Whisper URL", data)
        with config.credential_lock:
            if data == config.TRANSCRIPTION_CUSTOM_URL:
                return {"status": 200, "result": config.TRANSCRIPTION_CUSTOM_URL}
            if config.TRANSCRIPTION_AUTH_KEYS["Custom_Whisper"]:
                return VRCTError.create_error_response(
                    ErrorCode.CREDENTIAL_REENTRY_REQUIRED, data=config.TRANSCRIPTION_CUSTOM_URL)
            config.TRANSCRIPTION_CUSTOM_URL = data
            return {"status": 200, "result": config.TRANSCRIPTION_CUSTOM_URL}


    @staticmethod
    def setCustomWhisperModel(data, *args, **kwargs) -> dict:
        printLog("Set Custom Whisper Model", data)
        data = str(data)
        if data in config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST:
            config.SELECTED_CUSTOM_WHISPER_MODEL = data
            return {"status":200, "result":config.SELECTED_CUSTOM_WHISPER_MODEL}
        return VRCTError.create_error_response(
            ErrorCode.MODEL_TRANSCRIPTION_INVALID,
            data=config.SELECTED_CUSTOM_WHISPER_MODEL
        )

    @staticmethod
    def getDeepgramAuthKey(*args, **kwargs) -> dict:
        return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS["Deepgram"]}

    def setDeepgramAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranscriptionCredential("Deepgram", data, base_url=None)

    def delDeepgramAuthKey(self, *args, **kwargs) -> dict:
        with config.credential_lock:
            engine = "Deepgram"
            config.updateCredential("TRANSCRIPTION_AUTH_KEYS", engine, None)
            config.SELECTABLE_DEEPGRAM_MODEL_LIST = []
            config.DEEPGRAM_MODEL_LANGUAGES = {}
            config.SELECTED_DEEPGRAM_MODEL = None
            self.run(200, self.run_mapping["selectable_deepgram_model_list"], config.SELECTABLE_DEEPGRAM_MODEL_LIST)
            self.run(200, self.run_mapping["selected_deepgram_model"], config.SELECTED_DEEPGRAM_MODEL)
            config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = False
            self.updateTranscriptionEngine()
            return {"status":200, "result":config.TRANSCRIPTION_AUTH_KEYS[engine]}


    def setDeepgramModel(self, data, *args, **kwargs) -> dict:
        printLog("Set Deepgram Model", data)
        data = str(data)
        if data in config.SELECTABLE_DEEPGRAM_MODEL_LIST:
            config.SELECTED_DEEPGRAM_MODEL = data
            # 対応言語はモデルごとに異なるため、Deepgramが現在選択中の
            # 文字起こしエンジンである場合のみ、表示中の言語リストと
            # 既存の言語選択への影響を反映する。
            if config.SELECTED_TRANSCRIPTION_ENGINE == "Deepgram":
                self.fallbackUnsupportedLanguagesForTranscriptionEngine("Deepgram")
                self.run(200, self.run_mapping["selectable_language_list"], model.getListLanguageAndCountry())
            return {"status":200, "result":config.SELECTED_DEEPGRAM_MODEL}
        return VRCTError.create_error_response(
            ErrorCode.MODEL_TRANSCRIPTION_INVALID,
            data=config.SELECTED_DEEPGRAM_MODEL
        )



    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setSelectedReleaseChannel(data, *args, **kwargs) -> dict:
        config.SELECTED_RELEASE_CHANNEL = str(data)
        return {"status":200, "result":config.SELECTED_RELEASE_CHANNEL}

    @staticmethod
    def listAvailableReleases(*args, **kwargs) -> dict:
        releases = model.listAvailableReleases()
        return {"status":200, "result":[asdict(r) for r in releases]}


    @staticmethod
    def setEnableConvertMessageToRomaji(*args, **kwargs) -> dict:
        if config.CONVERT_MESSAGE_TO_ROMAJI is False:
            if config.CONVERT_MESSAGE_TO_HIRAGANA is False:
                model.startTransliteration()
            config.CONVERT_MESSAGE_TO_ROMAJI = True
        return {"status":200, "result":config.CONVERT_MESSAGE_TO_ROMAJI}

    @staticmethod
    def setDisableConvertMessageToRomaji(*args, **kwargs) -> dict:
        if config.CONVERT_MESSAGE_TO_ROMAJI is True:
            if config.CONVERT_MESSAGE_TO_HIRAGANA is False:
                model.stopTransliteration()
            config.CONVERT_MESSAGE_TO_ROMAJI = False
        return {"status":200, "result":config.CONVERT_MESSAGE_TO_ROMAJI}


    @staticmethod
    def setEnableConvertMessageToHiragana(*args, **kwargs) -> dict:
        if config.CONVERT_MESSAGE_TO_HIRAGANA is False:
            if config.CONVERT_MESSAGE_TO_ROMAJI is False:
                model.startTransliteration()
            config.CONVERT_MESSAGE_TO_HIRAGANA = True
        return {"status":200, "result":config.CONVERT_MESSAGE_TO_HIRAGANA}

    @staticmethod
    def setDisableConvertMessageToHiragana(*args, **kwargs) -> dict:
        if config.CONVERT_MESSAGE_TO_HIRAGANA is True:
            if config.CONVERT_MESSAGE_TO_ROMAJI is False:
                model.stopTransliteration()
            config.CONVERT_MESSAGE_TO_HIRAGANA = False
        return {"status":200, "result":config.CONVERT_MESSAGE_TO_HIRAGANA}


    @staticmethod
    def setEnableMainWindowSidebarCompactMode(*args, **kwargs) -> dict:
        if config.MAIN_WINDOW_SIDEBAR_COMPACT_MODE is False:
            config.MAIN_WINDOW_SIDEBAR_COMPACT_MODE = True
        return {"status":200, "result":config.MAIN_WINDOW_SIDEBAR_COMPACT_MODE}

    @staticmethod
    def setDisableMainWindowSidebarCompactMode(*args, **kwargs) -> dict:
        if config.MAIN_WINDOW_SIDEBAR_COMPACT_MODE is True:
            config.MAIN_WINDOW_SIDEBAR_COMPACT_MODE = False
        return {"status":200, "result":config.MAIN_WINDOW_SIDEBAR_COMPACT_MODE}


    @staticmethod
    def setTransparency(data, *args, **kwargs) -> dict:
        try:
            value = int(data)
        except Exception:
            return VRCTError.create_error_response(
                ErrorCode.GENERAL_EXCEPTION,
                data=config.TRANSPARENCY,
                custom_message="Transparency must be a number",
            )
        config.TRANSPARENCY = value
        return {"status":200, "result":config.TRANSPARENCY}


    @staticmethod
    def setUiScaling(data, *args, **kwargs) -> dict:
        try:
            value = int(data)
        except Exception:
            return VRCTError.create_error_response(
                ErrorCode.GENERAL_EXCEPTION,
                data=config.UI_SCALING,
                custom_message="UI scaling must be a number",
            )
        config.UI_SCALING = value
        return {"status":200, "result":config.UI_SCALING}


    @staticmethod
    def setTextboxUiScaling(data, *args, **kwargs) -> dict:
        try:
            value = int(data)
        except Exception:
            return VRCTError.create_error_response(
                ErrorCode.GENERAL_EXCEPTION,
                data=config.TEXTBOX_UI_SCALING,
                custom_message="Textbox UI scaling must be a number",
            )
        config.TEXTBOX_UI_SCALING = value
        return {"status":200, "result":config.TEXTBOX_UI_SCALING}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setMessageBoxRatio(data, *args, **kwargs) -> dict:
        config.MESSAGE_BOX_RATIO = data
        return {"status":200, "result":config.MESSAGE_BOX_RATIO}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setSendMessageButtonType(data, *args, **kwargs) -> dict:
        config.SEND_MESSAGE_BUTTON_TYPE = data
        return {"status":200, "result":config.SEND_MESSAGE_BUTTON_TYPE}


    @staticmethod
    def setEnableShowResendButton(*args, **kwargs) -> dict:
        if config.SHOW_RESEND_BUTTON is False:
            config.SHOW_RESEND_BUTTON = True
        return {"status":200, "result":config.SHOW_RESEND_BUTTON}

    @staticmethod
    def setDisableShowResendButton(*args, **kwargs) -> dict:
        if config.SHOW_RESEND_BUTTON is True:
            config.SHOW_RESEND_BUTTON = False
        return {"status":200, "result":config.SHOW_RESEND_BUTTON}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setFontFamily(data, *args, **kwargs) -> dict:
        config.FONT_FAMILY = data
        return {"status":200, "result":config.FONT_FAMILY}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setUiLanguage(data, *args, **kwargs) -> dict:
        config.UI_LANGUAGE = data
        return {"status":200, "result":config.UI_LANGUAGE}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setMainWindowGeometry(data, *args, **kwargs) -> dict:
        config.MAIN_WINDOW_GEOMETRY = data
        return {"status":200, "result":config.MAIN_WINDOW_GEOMETRY}


    def applyAutoMicSelect(self) -> None:
        with self._audioLock("mic"):
            if not config.AUTO_MIC_SELECT:
                return
            generation = self._audioGeneration("mic")
            device_manager.clearCallbackProcessBeforeUpdateMicDevices()
            device_manager.clearCallbackProcessAfterUpdateMicDevices()
            device_manager.setCallbackDefaultMicDevice(lambda *args: self._queueAudioReconciliation("mic"))
            device_manager.setMicAutoActive(True)
        # Forced enumeration does not dispatch the old split callbacks. Apply
        # its snapshot once, then publish the compatible name list as well.
        device_manager.update()
        self._reconcileAudio("mic", generation)
        self.run(200, self.run_mapping.get("selectable_mic_device_list", "/run/selectable_mic_device_list"), model.getListMicDevice())

    def setEnableAutoMicSelect(self, *args, **kwargs) -> dict:
        with self._audioLock("mic"):
            config.AUTO_MIC_SELECT = True
            self._audioGeneration("mic", advance=True)
        self.applyAutoMicSelect()
        return {"status": 200, "result": config.AUTO_MIC_SELECT}

    def setDisableAutoMicSelect(self, *args, **kwargs) -> dict:
        with self._audioLock("mic"):
            config.AUTO_MIC_SELECT = False
            generation = self._audioGeneration("mic", advance=True)
            device_manager.clearCallbackDefaultMicDevice()
            device_manager.setMicAutoActive(False)
        self._reconcileAudio("mic", generation, follow_default=False)
        return {"status": 200, "result": config.AUTO_MIC_SELECT}


    def setSelectedMicHost(self, data, *args, **kwargs) -> dict:
        with self._audioLock("mic"):
            devices = device_manager.getMicDevices().get(data)
            if devices is None:
                return VRCTError.create_error_response(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=config.SELECTED_MIC_HOST)
            self._audioGeneration("mic", advance=True)
            selected = resolve_device(devices, name=config.SELECTED_MIC_DEVICE)
            if selected is None:
                selected = next((d for d in devices if d.get("name") != "NoDevice"), None)
            self._reconcileAudioLocked("mic", follow_default=False, device=selected or {"name": "NoDevice"})
            self.run(200, self.run_mapping["selectable_mic_device_list"], model.getListMicDevice())
            return {"status": 200, "result": config.SELECTED_MIC_HOST}

    def setSelectedMicDevice(self, data, *args, **kwargs) -> dict:
        with self._audioLock("mic"):
            devices = [d for host, d in self._audioDevices("mic")
                       if host == config.SELECTED_MIC_HOST]
            device = resolve_device(devices, name=data)
            if device is None:
                return VRCTError.create_error_response(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=config.SELECTED_MIC_DEVICE)
            self._audioGeneration("mic", advance=True)
            self._reconcileAudioLocked("mic", follow_default=False, device=device)
            return {"status": 200, "result": config.SELECTED_MIC_DEVICE}

    def getSelectedMicDeviceId(self, *args, **kwargs):
        return {"status": 200, "result": config.SELECTED_MIC_DEVICE_ID}

    def getMicDeviceOptions(self, *args, **kwargs):
        return {"status": 200, "result": self._audioDeviceOptions("mic")}

    def setSelectedMicDeviceId(self, data, *args, **kwargs):
        with self._audioLock("mic"):
            devices = [d for host, d in self._audioDevices("mic")
                       if host == config.SELECTED_MIC_HOST]
            device = resolve_device(devices, endpoint_id=data) if data else None
            if device is None:
                return VRCTError.create_error_response(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=config.SELECTED_MIC_DEVICE_ID)
            self._audioGeneration("mic", advance=True)
            self._reconcileAudioLocked("mic", follow_default=False, device=device)
            return {"status": 200, "result": config.SELECTED_MIC_DEVICE_ID}

    def _reopenMicAudioOnDeviceChange(self) -> None:
        self._reconcileAudio("mic", follow_default=False)

    def _changeMicTranscriptStatusLocked(self) -> None:
        # All mute-sync transitions share the mic start/stop/reconfigure lock.
        with self._audioLock("mic"):
            model.changeMicTranscriptStatus()


    @staticmethod
    def setMicThreshold(data, *args, **kwargs) -> dict:
        try:
            data = int(data)
            if 0 <= data <= config.MAX_MIC_THRESHOLD:
                config.MIC_THRESHOLD = data
                status = 200
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_MIC_THRESHOLD,
                data=config.MIC_THRESHOLD
            )
        else:
            response = {"status":status, "result":config.MIC_THRESHOLD}
        return response


    @staticmethod
    def setEnableMicAutomaticThreshold(*args, **kwargs) -> dict:
        if config.MIC_AUTOMATIC_THRESHOLD is False:
            config.MIC_AUTOMATIC_THRESHOLD = True
        return {"status":200, "result":config.MIC_AUTOMATIC_THRESHOLD}

    @staticmethod
    def setDisableMicAutomaticThreshold(*args, **kwargs) -> dict:
        if config.MIC_AUTOMATIC_THRESHOLD is True:
            config.MIC_AUTOMATIC_THRESHOLD = False
        return {"status":200, "result":config.MIC_AUTOMATIC_THRESHOLD}

    # VAD は録音開始時に recorder を選ぶので、次回の文字起こし開始から効く
    # (設定画面を開いている間は文字起こしが止まり、閉じると再開される)
    @staticmethod
    def setEnableMicVadFilter(*args, **kwargs) -> dict:
        if config.MIC_ENABLE_VAD is False:
            config.MIC_ENABLE_VAD = True
        return {"status":200, "result":config.MIC_ENABLE_VAD}

    @staticmethod
    def setDisableMicVadFilter(*args, **kwargs) -> dict:
        if config.MIC_ENABLE_VAD is True:
            config.MIC_ENABLE_VAD = False
        return {"status":200, "result":config.MIC_ENABLE_VAD}


    @staticmethod
    def setMicRecordTimeout(data, *args, **kwargs) -> dict:
        printLog("Set Mic Record Timeout", data)
        try:
            data = int(data)
            if 0 <= data <= config.MIC_PHRASE_TIMEOUT:
                config.MIC_RECORD_TIMEOUT = data
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_MIC_RECORD_TIMEOUT,
                data=config.MIC_RECORD_TIMEOUT
            )
        else:
            response = {"status":200, "result":config.MIC_RECORD_TIMEOUT}
        return response


    @staticmethod
    def setMicPhraseTimeout(data, *args, **kwargs) -> dict:
        try:
            data = int(data)
            if data >= config.MIC_RECORD_TIMEOUT:
                config.MIC_PHRASE_TIMEOUT = data
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_MIC_PHRASE_TIMEOUT,
                data=config.MIC_PHRASE_TIMEOUT
            )
        else:
            response = {"status":200, "result":config.MIC_PHRASE_TIMEOUT}
        return response


    @staticmethod
    def setMicMaxPhrases(data, *args, **kwargs) -> dict:
        try:
            data = int(data)
            if 0 <= data:
                config.MIC_MAX_PHRASES = data
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_MIC_MAX_PHRASES,
                data=config.MIC_MAX_PHRASES
            )
        else:
            response = {"status":200, "result":config.MIC_MAX_PHRASES}
        return response


    @staticmethod
    def setMicWordFilter(data, *args, **kwargs) -> dict:
        config.MIC_WORD_FILTER = sorted(set(data), key=data.index)
        model.resetKeywordProcessor()
        model.addKeywords()
        return {"status":200, "result":config.MIC_WORD_FILTER}


    @staticmethod
    def setMicAvgLogprob(data, *args, **kwargs) -> dict:
        try:
            if isinstance(data, bool):
                raise ValueError("Boolean is not an ASR threshold")
            value = float(data)
            config.MIC_AVG_LOGPROB = value
        except (TypeError, ValueError, OverflowError, ConfigValidationError):
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.MIC_AVG_LOGPROB,
                custom_message="Mic average logprob must be finite and between -2 and 0",
            )
        return {"status":200, "result":config.MIC_AVG_LOGPROB}


    @staticmethod
    def setMicNoSpeechProb(data, *args, **kwargs) -> dict:
        try:
            if isinstance(data, bool):
                raise ValueError("Boolean is not an ASR threshold")
            value = float(data)
            config.MIC_NO_SPEECH_PROB = value
        except (TypeError, ValueError, OverflowError, ConfigValidationError):
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.MIC_NO_SPEECH_PROB,
                custom_message="Mic no-speech probability must be finite and between 0 and 1",
            )
        return {"status":200, "result":config.MIC_NO_SPEECH_PROB}


    def applyAutoSpeakerSelect(self) -> None:
        with self._audioLock("speaker"):
            if not config.AUTO_SPEAKER_SELECT:
                return
            generation = self._audioGeneration("speaker")
            device_manager.clearCallbackProcessBeforeUpdateSpeakerDevices()
            device_manager.clearCallbackProcessAfterUpdateSpeakerDevices()
            device_manager.setCallbackDefaultSpeakerDevice(lambda *args: self._queueAudioReconciliation("speaker"))
            device_manager.setSpeakerAutoActive(True)
        # Forced enumeration does not dispatch the old split callbacks. Apply
        # its snapshot once, then publish the compatible name list as well.
        device_manager.update()
        self._reconcileAudio("speaker", generation)
        self.run(200, self.run_mapping.get("selectable_speaker_device_list", "/run/selectable_speaker_device_list"), model.getListSpeakerDevice())

    def setEnableAutoSpeakerSelect(self, *args, **kwargs) -> dict:
        with self._audioLock("speaker"):
            config.AUTO_SPEAKER_SELECT = True
            self._audioGeneration("speaker", advance=True)
        self.applyAutoSpeakerSelect()
        return {"status": 200, "result": config.AUTO_SPEAKER_SELECT}

    def setDisableAutoSpeakerSelect(self, *args, **kwargs) -> dict:
        with self._audioLock("speaker"):
            config.AUTO_SPEAKER_SELECT = False
            generation = self._audioGeneration("speaker", advance=True)
            device_manager.clearCallbackDefaultSpeakerDevice()
            device_manager.setSpeakerAutoActive(False)
        self._reconcileAudio("speaker", generation, follow_default=False)
        return {"status": 200, "result": config.AUTO_SPEAKER_SELECT}


    def setSelectedSpeakerDevice(self, data, *args, **kwargs) -> dict:
        with self._audioLock("speaker"):
            devices = [d for _, d in self._audioDevices("speaker")]
            device = resolve_device(devices, name=data)
            if device is None:
                return VRCTError.create_error_response(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=config.SELECTED_SPEAKER_DEVICE)
            self._audioGeneration("speaker", advance=True)
            self._reconcileAudioLocked("speaker", follow_default=False, device=device)
            return {"status": 200, "result": config.SELECTED_SPEAKER_DEVICE}

    def getSelectedSpeakerDeviceId(self, *args, **kwargs):
        return {"status": 200, "result": config.SELECTED_SPEAKER_DEVICE_ID}

    def getSpeakerDeviceOptions(self, *args, **kwargs):
        return {"status": 200, "result": self._audioDeviceOptions("speaker")}

    def setSelectedSpeakerDeviceId(self, data, *args, **kwargs):
        with self._audioLock("speaker"):
            devices = [d for _, d in self._audioDevices("speaker")]
            device = resolve_device(devices, endpoint_id=data) if data else None
            if device is None:
                return VRCTError.create_error_response(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=config.SELECTED_SPEAKER_DEVICE_ID)
            self._audioGeneration("speaker", advance=True)
            self._reconcileAudioLocked("speaker", follow_default=False, device=device)
            return {"status": 200, "result": config.SELECTED_SPEAKER_DEVICE_ID}

    def _reopenSpeakerAudioOnDeviceChange(self) -> None:
        self._reconcileAudio("speaker", follow_default=False)

    def _reconfigureSpeakerDeviceLocked(self) -> None:
        self._reconcileAudio("speaker")

    @staticmethod
    def setSpeakerThreshold(data, *args, **kwargs) -> dict:
        printLog("Set Speaker Energy Threshold", data)
        try:
            data = int(data)
            if 0 <= data <= config.MAX_SPEAKER_THRESHOLD:
                config.SPEAKER_THRESHOLD = data
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_SPEAKER_THRESHOLD,
                data=config.SPEAKER_THRESHOLD
            )
        else:
            response = {"status":200, "result":config.SPEAKER_THRESHOLD}
        return response


    @staticmethod
    def setEnableSpeakerAutomaticThreshold(*args, **kwargs) -> dict:
        if config.SPEAKER_AUTOMATIC_THRESHOLD is False:
            config.SPEAKER_AUTOMATIC_THRESHOLD = True
        return {"status":200, "result":config.SPEAKER_AUTOMATIC_THRESHOLD}

    @staticmethod
    def setDisableSpeakerAutomaticThreshold(*args, **kwargs) -> dict:
        if config.SPEAKER_AUTOMATIC_THRESHOLD is True:
            config.SPEAKER_AUTOMATIC_THRESHOLD = False
        return {"status":200, "result":config.SPEAKER_AUTOMATIC_THRESHOLD}

    @staticmethod
    def setEnableSpeakerVadFilter(*args, **kwargs) -> dict:
        if config.SPEAKER_ENABLE_VAD is False:
            config.SPEAKER_ENABLE_VAD = True
        return {"status":200, "result":config.SPEAKER_ENABLE_VAD}

    @staticmethod
    def setDisableSpeakerVadFilter(*args, **kwargs) -> dict:
        if config.SPEAKER_ENABLE_VAD is True:
            config.SPEAKER_ENABLE_VAD = False
        return {"status":200, "result":config.SPEAKER_ENABLE_VAD}


    @staticmethod
    def setSpeakerRecordTimeout(data, *args, **kwargs) -> dict:
        try:
            data = int(data)
            if 0 <= data <= config.SPEAKER_PHRASE_TIMEOUT:
                config.SPEAKER_RECORD_TIMEOUT = data
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_SPEAKER_RECORD_TIMEOUT,
                data=config.SPEAKER_RECORD_TIMEOUT
            )
        else:
            response = {"status":200, "result":config.SPEAKER_RECORD_TIMEOUT}
        return response


    @staticmethod
    def setSpeakerPhraseTimeout(data, *args, **kwargs) -> dict:
        try:
            data = int(data)
            if 0 <= data and data >= config.SPEAKER_RECORD_TIMEOUT:
                config.SPEAKER_PHRASE_TIMEOUT = data
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_SPEAKER_PHRASE_TIMEOUT,
                data=config.SPEAKER_PHRASE_TIMEOUT
            )
        else:
            response = {"status":200, "result":config.SPEAKER_PHRASE_TIMEOUT}
        return response


    @staticmethod
    def setSpeakerMaxPhrases(data, *args, **kwargs) -> dict:
        printLog("Set Speaker Max Phrases", data)
        try:
            data = int(data)
            if 0 <= data:
                config.SPEAKER_MAX_PHRASES = data
            else:
                raise ValueError()
        except Exception:
            response = VRCTError.create_error_response(
                ErrorCode.VALIDATION_SPEAKER_MAX_PHRASES,
                data=config.SPEAKER_MAX_PHRASES
            )
        else:
            response = {"status":200, "result":config.SPEAKER_MAX_PHRASES}
        return response


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setHotkeys(data, *args, **kwargs) -> dict:
        config.HOTKEYS = data
        return {"status":200, "result":config.HOTKEYS}


    @staticmethod
    def setSpeakerAvgLogprob(data, *args, **kwargs) -> dict:
        try:
            if isinstance(data, bool):
                raise ValueError("Boolean is not an ASR threshold")
            value = float(data)
            config.SPEAKER_AVG_LOGPROB = value
        except (TypeError, ValueError, OverflowError, ConfigValidationError):
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.SPEAKER_AVG_LOGPROB,
                custom_message="Speaker average logprob must be finite and between -2 and 0",
            )
        return {"status":200, "result":config.SPEAKER_AVG_LOGPROB}


    @staticmethod
    def setSpeakerNoSpeechProb(data, *args, **kwargs) -> dict:
        try:
            if isinstance(data, bool):
                raise ValueError("Boolean is not an ASR threshold")
            value = float(data)
            config.SPEAKER_NO_SPEECH_PROB = value
        except (TypeError, ValueError, OverflowError, ConfigValidationError):
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.SPEAKER_NO_SPEECH_PROB,
                custom_message="Speaker no-speech probability must be finite and between 0 and 1",
            )
        return {"status":200, "result":config.SPEAKER_NO_SPEECH_PROB}


    def setOscIpAddress(self, data, *args, **kwargs) -> dict:
        with _OSC_CONTROL_LOCK:
            if isValidIpAddress(data) is False:
                return VRCTError.create_error_response(
                    ErrorCode.VALIDATION_INVALID_IP, data=config.OSC_IP_ADDRESS)
            try:
                model.setOscIpAddress(data)
                config.OSC_IP_ADDRESS = data
                return {"status": 200, "result": config.OSC_IP_ADDRESS}
            except Exception:
                # The handler already attempted rollback under its lifecycle lock.
                return VRCTError.create_error_response(
                    ErrorCode.VALIDATION_CANNOT_SET_IP, data=config.OSC_IP_ADDRESS)
            finally:
                self._publishOscQueryReadiness()


    def setOscPort(self, data, *args, **kwargs) -> dict:
        if not isValidPort(data):
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_OSC_PORT_INVALID, data=config.OSC_PORT,
            )
        port = data
        with _OSC_CONTROL_LOCK:
            try:
                model.setOscPort(port)
                config.OSC_PORT = port
                return {"status":200, "result":config.OSC_PORT}
            finally:
                self._publishOscQueryReadiness()


    @staticmethod
    def setEnableNotificationVrcSfx(*args, **kwargs) -> dict:
        if config.NOTIFICATION_VRC_SFX is False:
            config.NOTIFICATION_VRC_SFX = True
        return {"status":200, "result":config.NOTIFICATION_VRC_SFX}

    @staticmethod
    def setDisableNotificationVrcSfx(*args, **kwargs) -> dict:
        if config.NOTIFICATION_VRC_SFX is True:
            config.NOTIFICATION_VRC_SFX = False
        return {"status":200, "result":config.NOTIFICATION_VRC_SFX}

    # --- フェーズ3項目17: 翻訳エンジンレジストリ (TRANSLATION_PROVIDER_REGISTRY
    # =認証キー型、CONNECTION_PROVIDER_REGISTRY=疎通確認型) 向け共通CRUD実装。
    # エンジン固有の get/set/delXAuthKey・getXModelList・get/setXModel・
    # checkXConnection は全てこれらへの1行委譲になる
    # (詳細は translation_providers.py 参照)。

    def _resolveEngineSpec(self, engine_key: str):
        """`engine_key` がどちらのレジストリに属していても対応するスペックを返す。

        `_getTranslationEngineModelList` 等モデル管理系の3メソッドは
        `selectable_model_list_attr`/`selected_model_attr`/`error_model_invalid`
        という共通フィールド名だけを使うため、どちらのレジストリのスペックでも
        区別せず動く。
        """
        if engine_key in TRANSLATION_PROVIDER_REGISTRY:
            return TRANSLATION_PROVIDER_REGISTRY[engine_key]
        return CONNECTION_PROVIDER_REGISTRY[engine_key]

    def _getTranslationEngineAuthKey(self, engine_key: str) -> dict:
        return {"status":200, "result":config.AUTH_KEYS[engine_key]}

    def _setTranslationEngineAuthKey(self, engine_key: str, data) -> dict:
        spec = TRANSLATION_PROVIDER_REGISTRY[engine_key]
        printLog(f"Set {engine_key} Auth Key")
        try:
            data = str(data)
            if not spec.auth_validate(data):
                return VRCTError.create_error_response(
                    spec.error_auth_invalid, data=config.AUTH_KEYS.get(engine_key),
                )
            previous_model = getattr(config, spec.selected_model_attr)
            candidate = model.prepareTranslatorCredential(engine_key, data, selected_model=previous_model)
        except Exception:
            errorLogging(provider=engine_key)
            return VRCTError.create_error_response(
                spec.error_auth_failed, data=config.AUTH_KEYS.get(engine_key),
            )

        _, model_list, selected_model = candidate
        with config.credential_lock:
            if getattr(config, spec.selected_model_attr) != previous_model:
                return VRCTError.create_error_response(
                    spec.error_auth_failed, data=config.AUTH_KEYS.get(engine_key),
                )
            config.updateCredential("AUTH_KEYS", engine_key, data)
            setattr(config, spec.selectable_model_list_attr, model_list)
            setattr(config, spec.selected_model_attr, selected_model)
            model.commitTranslatorCredential(engine_key, candidate)
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine_key] = True
            self.run(200, self.run_mapping[spec.run_mapping_selectable_key], model_list)
            self.run(200, self.run_mapping[spec.run_mapping_selected_key], selected_model)
            self.updateTranslationEngineAndEngineList()
        return {"status": 200, "result": data}


    def _delTranslationEngineAuthKey(self, engine_key: str) -> dict:
        with config.credential_lock:
            spec = TRANSLATION_PROVIDER_REGISTRY[engine_key]
            config.updateCredential("AUTH_KEYS", engine_key, None)
            setattr(config, spec.selectable_model_list_attr, [])
            setattr(config, spec.selected_model_attr, None)
            self.run(200, self.run_mapping[spec.run_mapping_selectable_key], getattr(config, spec.selectable_model_list_attr))
            self.run(200, self.run_mapping[spec.run_mapping_selected_key], getattr(config, spec.selected_model_attr))
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine_key] = False
            self.updateTranslationEngineAndEngineList()
            return {"status":200, "result":config.AUTH_KEYS[engine_key]}


    def _getTranslationEngineModelList(self, engine_key: str) -> dict:
        spec = self._resolveEngineSpec(engine_key)
        return {"status":200, "result": getattr(config, spec.selectable_model_list_attr)}

    def _getTranslationEngineModel(self, engine_key: str) -> dict:
        spec = self._resolveEngineSpec(engine_key)
        return {"status":200, "result":getattr(config, spec.selected_model_attr)}

    def _setTranslationEngineModel(self, engine_key: str, data) -> dict:
        spec = self._resolveEngineSpec(engine_key)
        bindings = _ENGINE_MODEL_BINDINGS[engine_key]
        display_name = engine_key[:-len("_API")] if engine_key.endswith("_API") else engine_key
        printLog(f"Set {display_name} Model", data)
        try:
            data = str(data)
            result = getattr(model, bindings["set_model"])(model=data)
            if result is True:
                setattr(config, spec.selected_model_attr, data)
                getattr(model, bindings["set_model"])(model=getattr(config, spec.selected_model_attr))
                getattr(model, bindings["update_client"])()
                response = {"status":200, "result":getattr(config, spec.selected_model_attr)}
            else:
                response = VRCTError.create_error_response(
                    spec.error_model_invalid,
                    data=getattr(config, spec.selected_model_attr)
                )
        except Exception:
            errorLogging(provider=engine_key)
            # モデル SDK の例外詳細は UI に露出させず、選択失敗として
            # 現在値を返す。診断ログには例外の種類と発生位置だけを残す。
            response = VRCTError.create_error_response(
                spec.error_model_invalid,
                data=getattr(config, spec.selected_model_attr),
            )
        return response

    def _checkTranslationEngineConnection(self, engine_key: str, connect_kwargs: dict) -> dict:
        """CONNECTION_PROVIDER_REGISTRY 登録エンジン (LMStudio/Ollama) 共通の
        疎通確認処理。`connect_kwargs` は接続呼び出しに渡す追加引数
        (LMStudio: `{"base_url": config.LMSTUDIO_URL}`、Ollama: `{}`)。

        接続 SDK の例外や、接続後に利用可能なモデルが無い場合も、UI には
        `error_connection_failed` を返す。診断ログには例外の種類と発生位置を
        記録し、例外の本文はログにもレスポンスにも含めない。
        """
        spec = CONNECTION_PROVIDER_REGISTRY[engine_key]
        bindings = _ENGINE_MODEL_BINDINGS[engine_key]
        printLog(f"Check Translator {engine_key} Connection")
        try:
            result = getattr(model, bindings["authenticate"])(**connect_kwargs)
            if result is True:
                config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine_key] = True
                model_list = getattr(model, bindings["get_model_list"])()
                setattr(config, spec.selectable_model_list_attr, model_list)
                self.run(200, self.run_mapping[spec.run_mapping_selectable_key], model_list)
                if len(model_list) == 0:
                    raise Exception(f"No {engine_key} models available")
                if getattr(config, spec.selected_model_attr) not in model_list:
                    setattr(config, spec.selected_model_attr, model_list[0])
                getattr(model, bindings["set_model"])(model=getattr(config, spec.selected_model_attr))
                self.run(200, self.run_mapping[spec.run_mapping_selected_key], getattr(config, spec.selected_model_attr))
                getattr(model, bindings["update_client"])()
                self.updateTranslationEngineAndEngineList()
                response = {"status":200, "result":True}
            else:
                config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine_key] = False
                setattr(config, spec.selectable_model_list_attr, [])
                setattr(config, spec.selected_model_attr, None)
                self.run(200, self.run_mapping[spec.run_mapping_selectable_key], getattr(config, spec.selectable_model_list_attr))
                self.run(200, self.run_mapping[spec.run_mapping_selected_key], getattr(config, spec.selected_model_attr))
                self.updateTranslationEngineAndEngineList()
                response = VRCTError.create_error_response(
                    spec.error_connection_failed,
                    data=False
                )
        except Exception:
            errorLogging(provider=engine_key)
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine_key] = False
            setattr(config, spec.selectable_model_list_attr, [])
            setattr(config, spec.selected_model_attr, None)
            self.run(200, self.run_mapping[spec.run_mapping_selectable_key], getattr(config, spec.selectable_model_list_attr))
            self.run(200, self.run_mapping[spec.run_mapping_selected_key], getattr(config, spec.selected_model_attr))
            self.updateTranslationEngineAndEngineList()
            response = VRCTError.create_error_response(
                spec.error_connection_failed,
                data=False,
            )
        return response

    @staticmethod
    def getDeepLAuthKey(*args, **kwargs) -> dict:
        return {"status":200, "result":config.AUTH_KEYS["DeepL_API"]}

    def setDeeplAuthKey(self, data, *args, **kwargs) -> dict:
        printLog("Set DeepL Auth Key")
        engine = "DeepL_API"
        try:
            data = str(data)
            if len(data) not in (36, 39):
                return VRCTError.create_error_response(
                    ErrorCode.AUTH_DEEPL_LENGTH, data=config.AUTH_KEYS[engine],
                )
            candidate = model.prepareTranslatorCredential(engine, data)
        except Exception:
            errorLogging(provider=engine)
            return VRCTError.create_error_response(
                ErrorCode.AUTH_DEEPL_FAILED, data=config.AUTH_KEYS[engine],
            )
        with config.credential_lock:
            config.updateCredential("AUTH_KEYS", engine, data)
            model.commitTranslatorCredential(engine, candidate)
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] = True
            self.updateTranslationEngineAndEngineList()
        return {"status": 200, "result": data}

    def delDeeplAuthKey(self, *args, **kwargs) -> dict:
        with config.credential_lock:
            translator_name = "DeepL_API"
            config.updateCredential("AUTH_KEYS", translator_name, None)
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[translator_name] = False
            self.updateTranslationEngineAndEngineList()
            return {"status":200, "result":config.AUTH_KEYS[translator_name]}


    def getPlamoAuthKey(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineAuthKey("Plamo_API")

    def setPlamoAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineAuthKey("Plamo_API", data)

    def delPlamoAuthKey(self, *args, **kwargs) -> dict:
        return self._delTranslationEngineAuthKey("Plamo_API")

    def getPlamoModelList(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModelList("Plamo_API")

    def getPlamoModel(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModel("Plamo_API")

    def setPlamoModel(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineModel("Plamo_API", data)

    def getGeminiAuthKey(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineAuthKey("Gemini_API")

    def setGeminiAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineAuthKey("Gemini_API", data)

    def delGeminiAuthKey(self, *args, **kwargs) -> dict:
        return self._delTranslationEngineAuthKey("Gemini_API")

    def getGeminiModelList(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModelList("Gemini_API")

    def getGeminiModel(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModel("Gemini_API")

    def setGeminiModel(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineModel("Gemini_API", data)

    def getOpenAIAuthKey(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineAuthKey("OpenAI_API")

    def setOpenAIAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineAuthKey("OpenAI_API", data)

    def delOpenAIAuthKey(self, *args, **kwargs) -> dict:
        return self._delTranslationEngineAuthKey("OpenAI_API")

    def getOpenAIModelList(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModelList("OpenAI_API")

    def getOpenAIModel(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModel("OpenAI_API")

    def setOpenAIModel(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineModel("OpenAI_API", data)

    def getGroqAuthKey(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineAuthKey("Groq_API")

    def setGroqAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineAuthKey("Groq_API", data)

    def delGroqAuthKey(self, *args, **kwargs) -> dict:
        return self._delTranslationEngineAuthKey("Groq_API")

    def getGroqModelList(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModelList("Groq_API")

    def getGroqModel(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModel("Groq_API")

    def setGroqModel(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineModel("Groq_API", data)

    def getOpenRouterAuthKey(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineAuthKey("OpenRouter_API")

    def setOpenRouterAuthKey(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineAuthKey("OpenRouter_API", data)

    def delOpenRouterAuthKey(self, *args, **kwargs) -> dict:
        return self._delTranslationEngineAuthKey("OpenRouter_API")

    def getOpenRouterModelList(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModelList("OpenRouter_API")

    def getOpenRouterModel(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModel("OpenRouter_API")

    def setOpenRouterModel(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineModel("OpenRouter_API", data)

    def getTranslatorLMStudioConnection(self, *args, **kwargs) -> dict:
        return {"status":200, "result":model.getTranslatorLMStudioConnected()}

    def checkTranslatorLMStudioConnection(self, *args, **kwargs) -> dict:
        return self._checkTranslationEngineConnection("LMStudio", connect_kwargs={"base_url": config.LMSTUDIO_URL})


    def setTranslatorLMStudioURL(self, data, *args, **kwargs) -> dict:
        try:
            data = validate_api_url(data.strip() if isinstance(data, str) else data)
        except ValueError:
            return VRCTError.create_error_response(
                ErrorCode.CONNECTION_LMSTUDIO_URL_INVALID, data=config.LMSTUDIO_URL)
        printLog("Set Translator LMStudio URL", data)
        translator_name = "LMStudio"
        try:
            data = str(data)
            result = model.authenticationTranslatorLMStudio(base_url=data)
            if result is True:
                config.LMSTUDIO_URL = data
                config.SELECTABLE_TRANSLATION_ENGINE_STATUS[translator_name] = True
                config.SELECTABLE_LMSTUDIO_MODEL_LIST = model.getTranslatorLMStudioModelList()
                self.run(200, self.run_mapping["selectable_lmstudio_model_list"], config.SELECTABLE_LMSTUDIO_MODEL_LIST)
                if len(config.SELECTABLE_LMSTUDIO_MODEL_LIST) == 0:
                    raise Exception("No LMStudio models available")
                if config.SELECTED_LMSTUDIO_MODEL not in config.SELECTABLE_LMSTUDIO_MODEL_LIST:
                    config.SELECTED_LMSTUDIO_MODEL = config.SELECTABLE_LMSTUDIO_MODEL_LIST[0]
                model.setTranslatorLMStudioModel(model=config.SELECTED_LMSTUDIO_MODEL)
                self.run(200, self.run_mapping["selected_lmstudio_model"], config.SELECTED_LMSTUDIO_MODEL)
                model.updateTranslatorLMStudioClient()
                self.updateTranslationEngineAndEngineList()
                response = {"status":200, "result":config.LMSTUDIO_URL}
            else:
                config.SELECTABLE_TRANSLATION_ENGINE_STATUS[translator_name] = False
                config.SELECTABLE_LMSTUDIO_MODEL_LIST = []
                config.SELECTED_LMSTUDIO_MODEL = None
                self.run(200, self.run_mapping["selectable_lmstudio_model_list"], config.SELECTABLE_LMSTUDIO_MODEL_LIST)
                self.run(200, self.run_mapping["selected_lmstudio_model"], config.SELECTED_LMSTUDIO_MODEL)
                self.updateTranslationEngineAndEngineList()
                response = VRCTError.create_error_response(
                    ErrorCode.CONNECTION_LMSTUDIO_URL_INVALID,
                    data=config.LMSTUDIO_URL
                )
        except Exception:
            errorLogging(provider=translator_name)
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[translator_name] = False
            config.SELECTABLE_LMSTUDIO_MODEL_LIST = []
            config.SELECTED_LMSTUDIO_MODEL = None
            self.run(200, self.run_mapping["selectable_lmstudio_model_list"], config.SELECTABLE_LMSTUDIO_MODEL_LIST)
            self.run(200, self.run_mapping["selected_lmstudio_model"], config.SELECTED_LMSTUDIO_MODEL)
            self.updateTranslationEngineAndEngineList()
            response = VRCTError.create_error_response(
                ErrorCode.CONNECTION_LMSTUDIO_URL_INVALID,
                data=config.LMSTUDIO_URL,
            )
        return response

    def getTranslatorLMStudioModelList(self, *args, **kwargs) -> dict:
        # 認証キー型5エンジンの getXModelList と異なり、ここは config の
        # キャッシュ値ではなく model 経由でクライアントに都度問い合わせる
        # (ローカルサーバーでモデルが動的に増減しうる LMStudio/Ollama 固有の
        # 設計) ため、_getTranslationEngineModelList には委譲せず既存の実装の
        # まま残す。
        model_list = model.getTranslatorLMStudioModelList()
        return {"status":200, "result": model_list}

    def getTranslatorLMStudioModel(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModel("LMStudio")

    def setTranslatorLMStudioModel(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineModel("LMStudio", data)

    # ------------------------------------------------------------------
    # OpenAI-compatible endpoint (URL + Auth Key)
    # ------------------------------------------------------------------
    @staticmethod
    def getOpenAICompatibleAuthKey(*args, **kwargs) -> dict:
        return {"status":200, "result":config.AUTH_KEYS["OpenAI_Compatible"]}

    def setOpenAICompatibleAuthKeyAndURL(self, data, *args, **kwargs) -> dict:
        return self._setEndpointCredential("OpenAI_Compatible", data)

    def _setEndpointCredential(self, engine, data):
        """Authenticate the submitted URL/key pair before publishing either value."""
        translation = engine == "OpenAI_Compatible"
        map_name = "AUTH_KEYS" if translation else "TRANSCRIPTION_AUTH_KEYS"
        url_name = "OPENAI_COMPATIBLE_URL" if translation else "TRANSCRIPTION_CUSTOM_URL"
        prefix = "OPENAI_COMPATIBLE" if translation else "CUSTOM_WHISPER"
        auth_error = ErrorCode.AUTH_OPENAI_COMPATIBLE_FAILED if translation else ErrorCode.TRANSCRIPTION_API_AUTH_FAILED
        url_error = (ErrorCode.CONNECTION_OPENAI_COMPATIBLE_URL_INVALID if translation
                     else ErrorCode.CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID)
        if not isinstance(data, dict) or set(data) != {"url", "auth_key"}:
            return VRCTError.create_error_response(auth_error, data=getattr(config, map_name)[engine])
        try:
            url = validate_api_url(data["url"].strip() if isinstance(data["url"], str) else data["url"])
        except ValueError:
            return VRCTError.create_error_response(url_error, data=getattr(config, url_name))
        key = data["auth_key"]
        if key is not None and not isinstance(key, str):
            return VRCTError.create_error_response(auth_error, data=getattr(config, map_name)[engine])
        key = (key.strip() or None) if isinstance(key, str) else None
        with config.credential_lock:
            previous = (getattr(config, url_name), getattr(config, map_name)[engine],
                        getattr(config, f"SELECTED_{prefix}_MODEL"))
        try:
            if key and translation:
                candidate = model.prepareTranslatorCredential(engine, key, selected_model=previous[2], base_url=url)
            elif key:
                if model.authenticationTranscriptionApiKey(api_key=key, base_url=url) is not True:
                    raise ValueError("Credential authentication failed")
                model_list = model.getTranscriptionApiModelList(api_key=key, base_url=url)
                if not isinstance(model_list, list) or not model_list or any(
                    not isinstance(name, str) or not name.strip() for name in model_list
                ):
                    raise ValueError("No supported models available")
                model_list = list(model_list)
                selected_model = previous[2] if previous[2] in model_list else model_list[0]
        except Exception:
            errorLogging(provider=engine)
            return VRCTError.create_error_response(auth_error, data=getattr(config, map_name)[engine])
        with config.credential_lock:
            if previous != (getattr(config, url_name), getattr(config, map_name)[engine],
                            getattr(config, f"SELECTED_{prefix}_MODEL")):
                return VRCTError.create_error_response(auth_error, data=getattr(config, map_name)[engine])
            setattr(config, url_name, url)
            if key is None:
                if translation:
                    self.delOpenAICompatibleAuthKey()
                else:
                    self.delCustomWhisperAuthKey()
            else:
                config.updateCredential(map_name, engine, key)
                if translation:
                    self._commitOpenAICompatibleCandidate(candidate)
                else:
                    config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST = model_list
                    config.SELECTED_CUSTOM_WHISPER_MODEL = selected_model
                    config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = True
                    self.run(200, self.run_mapping["selectable_custom_whisper_model_list"], model_list)
                    self.run(200, self.run_mapping["selected_custom_whisper_model"], selected_model)
                    self.updateTranscriptionEngine()
        return {"status": 200, "result": {"url": url, "auth_key": key}}

    def setOpenAICompatibleAuthKey(self, data, *args, **kwargs) -> dict:
        printLog("Set OpenAI Compatible Auth Key")
        engine = "OpenAI_Compatible"
        try:
            data = str(data).strip()
            if not data:
                return VRCTError.create_error_response(
                    ErrorCode.AUTH_OPENAI_COMPATIBLE_INVALID, data=config.AUTH_KEYS[engine],
                )
            base_url = config.OPENAI_COMPATIBLE_URL
            previous_model = config.SELECTED_OPENAI_COMPATIBLE_MODEL
            candidate = model.prepareTranslatorCredential(
                engine, data, selected_model=previous_model,
                base_url=base_url,
            )
        except Exception:
            errorLogging(provider=engine)
            return VRCTError.create_error_response(
                ErrorCode.AUTH_OPENAI_COMPATIBLE_FAILED, data=config.AUTH_KEYS[engine],
            )
        with config.credential_lock:
            # A related setting may change while the candidate is being checked.
            if config.OPENAI_COMPATIBLE_URL != base_url or config.SELECTED_OPENAI_COMPATIBLE_MODEL != previous_model:
                return VRCTError.create_error_response(
                    ErrorCode.AUTH_OPENAI_COMPATIBLE_FAILED, data=config.AUTH_KEYS[engine],
                )
            config.updateCredential("AUTH_KEYS", engine, data)
            self._commitOpenAICompatibleCandidate(candidate)
        return {"status": 200, "result": data}

    def _commitOpenAICompatibleCandidate(self, candidate):
        """Publish prepared state while the caller holds credential_lock."""
        _, model_list, selected_model = candidate
        config.SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST = model_list
        config.SELECTED_OPENAI_COMPATIBLE_MODEL = selected_model
        model.commitTranslatorCredential("OpenAI_Compatible", candidate)
        config.SELECTABLE_TRANSLATION_ENGINE_STATUS["OpenAI_Compatible"] = True
        self.run(200, self.run_mapping["selectable_openai_compatible_model_list"], model_list)
        self.run(200, self.run_mapping["selected_openai_compatible_model"], selected_model)
        self.updateTranslationEngineAndEngineList()

    def delOpenAICompatibleAuthKey(self, *args, **kwargs) -> dict:
        with config.credential_lock:
            translator_name = "OpenAI_Compatible"
            config.updateCredential("AUTH_KEYS", translator_name, None)
            config.SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST = []
            config.SELECTED_OPENAI_COMPATIBLE_MODEL = None
            self.run(200, self.run_mapping["selectable_openai_compatible_model_list"], config.SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST)
            self.run(200, self.run_mapping["selected_openai_compatible_model"], config.SELECTED_OPENAI_COMPATIBLE_MODEL)
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[translator_name] = False
            self.updateTranslationEngineAndEngineList()
            return {"status":200, "result":config.AUTH_KEYS[translator_name]}


    def setOpenAICompatibleURL(self, data, *args, **kwargs) -> dict:
        """Require explicit key entry before changing a credential's destination."""
        try:
            data = validate_api_url(data.strip() if isinstance(data, str) else data)
        except ValueError:
            return VRCTError.create_error_response(
                ErrorCode.CONNECTION_OPENAI_COMPATIBLE_URL_INVALID, data=config.OPENAI_COMPATIBLE_URL)
        printLog("Set OpenAI Compatible URL", data)
        with config.credential_lock:
            if data == config.OPENAI_COMPATIBLE_URL:
                return {"status": 200, "result": config.OPENAI_COMPATIBLE_URL}
            if config.AUTH_KEYS["OpenAI_Compatible"]:
                return VRCTError.create_error_response(
                    ErrorCode.CREDENTIAL_REENTRY_REQUIRED, data=config.OPENAI_COMPATIBLE_URL)
            config.OPENAI_COMPATIBLE_URL = data
            return {"status": 200, "result": config.OPENAI_COMPATIBLE_URL}


    def setOpenAICompatibleModel(self, data, *args, **kwargs) -> dict:
        printLog("Set OpenAI Compatible Model", data)
        try:
            data = str(data)
            result = model.setTranslatorOpenAICompatibleModel(model=data)
            if result is True:
                config.SELECTED_OPENAI_COMPATIBLE_MODEL = data
                model.setTranslatorOpenAICompatibleModel(model=config.SELECTED_OPENAI_COMPATIBLE_MODEL)
                model.updateTranslatorOpenAICompatibleClient()
                response = {"status":200, "result":config.SELECTED_OPENAI_COMPATIBLE_MODEL}
            else:
                response = VRCTError.create_error_response(
                    ErrorCode.MODEL_OPENAI_COMPATIBLE_INVALID,
                    data=config.SELECTED_OPENAI_COMPATIBLE_MODEL
                )
        except Exception as e:
            errorLogging(provider="OpenAI_Compatible")
            response = VRCTError.create_exception_error_response(
                e,
                data=config.SELECTED_OPENAI_COMPATIBLE_MODEL,
                provider="OpenAI_Compatible",
            )
        return response

    def getTranslatorOllamaConnection(self, *args, **kwargs) -> dict:
        return {"status":200, "result":model.getTranslatorOllamaConnected()}

    def checkTranslatorOllamaConnection(self, *args, **kwargs) -> dict:
        return self._checkTranslationEngineConnection("Ollama", connect_kwargs={})

    def getTranslatorOllamaModelList(self, *args, **kwargs) -> dict:
        model_list = model.getTranslatorOllamaModelList()
        return {"status":200, "result": model_list}

    def getTranslatorOllamaModel(self, *args, **kwargs) -> dict:
        return self._getTranslationEngineModel("Ollama")

    def setTranslatorOllamaModel(self, data, *args, **kwargs) -> dict:
        return self._setTranslationEngineModel("Ollama", data)


    @staticmethod
    def _parseCtranslate2WeightRequest(data) -> tuple:
        """Parse selection consent; acquisition uses the separate manifest consent."""
        if isinstance(data, dict):
            return str(data.get("weight_type")), data.get("accept_non_commercial_license") is True
        return str(data), False

    @staticmethod
    def _ctranslate2LicenseConsentError(weight_type: str, accepted: bool) -> Optional[dict]:
        """Error response when a non-commercial weight is requested without
        the explicit opt-in, else None.

        Keeping an existing selection is a no-op, including old NLLB defaults.
        This exemption never authorizes acquisition; downloads use their own
        model/manifest consent check.
        """
        if accepted or not isNonCommercialCTranslate2Weight(weight_type):
            return None
        if weight_type == config.CTRANSLATE2_WEIGHT_TYPE:
            return None
        return VRCTError.create_error_response(
            ErrorCode.WEIGHT_CTRANSLATE2_LICENSE_CONSENT_REQUIRED,
            data={"weight_type": weight_type, "selected": config.CTRANSLATE2_WEIGHT_TYPE},
        )

    def setCtranslate2WeightType(self, data, *args, **kwargs) -> dict:
        weight_type, accepted = self._parseCtranslate2WeightRequest(data)
        consent_error = self._ctranslate2LicenseConsentError(weight_type, accepted)
        if consent_error is not None:
            return consent_error
        config.CTRANSLATE2_WEIGHT_TYPE = weight_type
        if accepted and isNonCommercialCTranslate2Weight(config.CTRANSLATE2_WEIGHT_TYPE):
            # The confirmation dialog already showed the license; the
            # one-time startup notice would only repeat it.
            config.CTRANSLATE2_LICENSE_NOTICE_SHOWN = True
        model.setChangedTranslatorParameters(True)
        # Each weight has its own language table (M2M100 lacks e.g. Basque
        # and Telugu, which NLLB has). Re-check the current selection now
        # rather than letting the next translation fail on it.
        self.updateTranslationEngineAndEngineList()
        return {"status":200, "result":config.CTRANSLATE2_WEIGHT_TYPE}


    @staticmethod
    def setSelectedTranslationComputeType(data, *args, **kwargs) -> dict:
        config.SELECTED_TRANSLATION_COMPUTE_TYPE = str(data)
        model.setChangedTranslatorParameters(True)
        return {"status":200, "result":config.SELECTED_TRANSLATION_COMPUTE_TYPE}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setWhisperWeightType(data, *args, **kwargs) -> dict:
        config.WHISPER_WEIGHT_TYPE = str(data)
        return {"status":200, "result": config.WHISPER_WEIGHT_TYPE}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setSelectedTranscriptionComputeType(data, *args, **kwargs) -> dict:
        config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE = str(data)
        return {"status":200, "result":config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setSendMessageFormatParts(data, *args, **kwargs) -> dict:
        config.SEND_MESSAGE_FORMAT_PARTS = dict(data)
        return {"status":200, "result":config.SEND_MESSAGE_FORMAT_PARTS}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setReceivedMessageFormatParts(data, *args, **kwargs) -> dict:
        config.RECEIVED_MESSAGE_FORMAT_PARTS = dict(data)
        return {"status":200, "result":config.RECEIVED_MESSAGE_FORMAT_PARTS}


    @staticmethod
    def setEnableAutoClearMessageBox(*args, **kwargs) -> dict:
        if config.AUTO_CLEAR_MESSAGE_BOX is False:
            config.AUTO_CLEAR_MESSAGE_BOX = True
        return {"status":200, "result":config.AUTO_CLEAR_MESSAGE_BOX}

    @staticmethod
    def setDisableAutoClearMessageBox(*args, **kwargs) -> dict:
        if config.AUTO_CLEAR_MESSAGE_BOX is True:
            config.AUTO_CLEAR_MESSAGE_BOX = False
        return {"status":200, "result":config.AUTO_CLEAR_MESSAGE_BOX}


    @staticmethod
    def setEnableSendOnlyTranslatedMessages(*args, **kwargs) -> dict:
        if config.SEND_ONLY_TRANSLATED_MESSAGES is False:
            config.SEND_ONLY_TRANSLATED_MESSAGES = True
        return {"status":200, "result":config.SEND_ONLY_TRANSLATED_MESSAGES}

    @staticmethod
    def setDisableSendOnlyTranslatedMessages(*args, **kwargs) -> dict:
        if config.SEND_ONLY_TRANSLATED_MESSAGES is True:
            config.SEND_ONLY_TRANSLATED_MESSAGES = False
        return {"status":200, "result":config.SEND_ONLY_TRANSLATED_MESSAGES}


    @staticmethod
    def syncOverlayRunning() -> bool:
        """字幕 (一行 / 複数行) と VR UI のどれかがONならオーバーレイを動かし、全部OFFなら止める。"""
        # VR UI を作れない OS では、保存済みの ON を無視する。作ろうとすると失敗して字幕も止まる。
        vr_panel = config.OVERLAY_VR_PANEL and vrPanelSupported()
        model.setVrPanelEnabled(vr_panel)
        model.setVrPanelLocked(config.OVERLAY_VR_PANEL_LOCKED)
        model.setVrLauncherAutoHide(config.OVERLAY_VR_LAUNCHER_AUTO_HIDE)
        if config.OVERLAY_SMALL_LOG or config.OVERLAY_LARGE_LOG or vr_panel:
            return model.startOverlay()
        else:
            model.shutdownOverlay()
        return True

    @staticmethod
    def setEnableOverlaySmallLog(*args, **kwargs) -> dict:
        if config.OVERLAY_SMALL_LOG is False:
            config.OVERLAY_SMALL_LOG = True
            if Controller.syncOverlayRunning() is False or not config.OVERLAY_SMALL_LOG:
                config.OVERLAY_SMALL_LOG = False
                return VRCTError.create_error_response(ErrorCode.OVERLAY_RUNTIME_FAILED, data=False)
        return {"status":200, "result":config.OVERLAY_SMALL_LOG}

    @staticmethod
    def setDisableOverlaySmallLog(*args, **kwargs) -> dict:
        if config.OVERLAY_SMALL_LOG is True:
            config.OVERLAY_SMALL_LOG = False
            model.clearOverlayImageSmallLog()
            Controller.syncOverlayRunning()
        return {"status":200, "result":config.OVERLAY_SMALL_LOG}


    # The desktop caption overlay is a window of the UI: the backend only keeps
    # the switch and the look, and has nothing to start or stop.
    @staticmethod
    def setEnableOverlayDesktop(*args, **kwargs) -> dict:
        config.OVERLAY_DESKTOP = True
        return {"status":200, "result":config.OVERLAY_DESKTOP}

    @staticmethod
    def setDisableOverlayDesktop(*args, **kwargs) -> dict:
        config.OVERLAY_DESKTOP = False
        return {"status":200, "result":config.OVERLAY_DESKTOP}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOverlayDesktopSettings(data, *args, **kwargs) -> dict:
        config.OVERLAY_DESKTOP_SETTINGS = data
        return {"status":200, "result":config.OVERLAY_DESKTOP_SETTINGS}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setIoFlowOverlaySettings(data, *args, **kwargs) -> dict:
        config.IO_FLOW_OVERLAY_SETTINGS = data
        return {"status":200, "result":config.IO_FLOW_OVERLAY_SETTINGS}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOverlaySmallLogSettings(data, *args, **kwargs) -> dict:
        config.OVERLAY_SMALL_LOG_SETTINGS = data
        model.updateOverlaySmallLogSettings()
        return {"status":200, "result":config.OVERLAY_SMALL_LOG_SETTINGS}


    @staticmethod
    def setEnableOverlayLargeLog(*args, **kwargs) -> dict:
        if config.OVERLAY_LARGE_LOG is False:
            config.OVERLAY_LARGE_LOG = True
            if Controller.syncOverlayRunning() is False or not config.OVERLAY_LARGE_LOG:
                config.OVERLAY_LARGE_LOG = False
                return VRCTError.create_error_response(ErrorCode.OVERLAY_RUNTIME_FAILED, data=False)
        return {"status":200, "result":config.OVERLAY_LARGE_LOG}

    @staticmethod
    def setDisableOverlayLargeLog(*args, **kwargs) -> dict:
        if config.OVERLAY_LARGE_LOG is True:
            config.OVERLAY_LARGE_LOG = False
            model.clearOverlayImageLargeLog()
            Controller.syncOverlayRunning()
        return {"status":200, "result":config.OVERLAY_LARGE_LOG}

    @staticmethod
    def setEnableOverlayVrPanel(*args, **kwargs) -> dict:
        if not vrPanelSupported():
            # 動いている字幕には触れずに断る。
            return VRCTError.create_error_response(ErrorCode.OVERLAY_VR_PANEL_UNSUPPORTED, data=False)
        if config.OVERLAY_VR_PANEL is False:
            config.OVERLAY_VR_PANEL = True
            if Controller.syncOverlayRunning() is False or not config.OVERLAY_VR_PANEL:
                config.OVERLAY_VR_PANEL = False
                return VRCTError.create_error_response(ErrorCode.OVERLAY_RUNTIME_FAILED, data=False)
        return {"status":200, "result":config.OVERLAY_VR_PANEL}

    @staticmethod
    def setEnableOverlayVrPanelLocked(*args, **kwargs) -> dict:
        config.OVERLAY_VR_PANEL_LOCKED = True
        model.setVrPanelLocked(True)
        return {"status":200, "result":config.OVERLAY_VR_PANEL_LOCKED}

    @staticmethod
    def setDisableOverlayVrPanelLocked(*args, **kwargs) -> dict:
        config.OVERLAY_VR_PANEL_LOCKED = False
        model.setVrPanelLocked(False)
        return {"status":200, "result":config.OVERLAY_VR_PANEL_LOCKED}

    @staticmethod
    def setDisableOverlayVrPanel(*args, **kwargs) -> dict:
        if config.OVERLAY_VR_PANEL is True:
            config.OVERLAY_VR_PANEL = False
            Controller.syncOverlayRunning()
        return {"status":200, "result":config.OVERLAY_VR_PANEL}


    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOverlayLargeLogSettings(data, *args, **kwargs) -> dict:
        config.OVERLAY_LARGE_LOG_SETTINGS = data
        model.updateOverlayLargeLogSettings()
        return {"status":200, "result":config.OVERLAY_LARGE_LOG_SETTINGS}


    @staticmethod
    def setEnableOverlayShowOnlyTranslatedMessages(*args, **kwargs) -> dict:
        if config.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES is False:
            config.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES = True
        return {"status":200, "result":config.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES}

    @staticmethod
    def setDisableOverlayShowOnlyTranslatedMessages(*args, **kwargs) -> dict:
        if config.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES is True:
            config.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES = False
        return {"status":200, "result":config.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES}


    @staticmethod
    def setEnableSendMessageToVrc(*args, **kwargs) -> dict:
        with Controller._typing_lock:
            if config.SEND_MESSAGE_TO_VRC is False:
                config.SEND_MESSAGE_TO_VRC = True
            return {"status":200, "result":config.SEND_MESSAGE_TO_VRC}

    @staticmethod
    def setDisableSendMessageToVrc(*args, **kwargs) -> dict:
        with Controller._typing_lock:
            if config.SEND_MESSAGE_TO_VRC is True:
                config.SEND_MESSAGE_TO_VRC = False
            Controller.stopTypingMessageBox()
            return {"status":200, "result":config.SEND_MESSAGE_TO_VRC}


    @staticmethod
    def setEnableSendReceivedMessageToVrc(*args, **kwargs) -> dict:
        if config.SEND_RECEIVED_MESSAGE_TO_VRC is False:
            config.SEND_RECEIVED_MESSAGE_TO_VRC = True
        return {"status":200, "result":config.SEND_RECEIVED_MESSAGE_TO_VRC}

    @staticmethod
    def setDisableSendReceivedMessageToVrc(*args, **kwargs) -> dict:
        if config.SEND_RECEIVED_MESSAGE_TO_VRC is True:
            config.SEND_RECEIVED_MESSAGE_TO_VRC = False
        return {"status":200, "result":config.SEND_RECEIVED_MESSAGE_TO_VRC}


    @staticmethod
    def setEnableLoggerFeature(*args, **kwargs) -> dict:
        if config.LOGGER_FEATURE is False:
            model.startLogger()
            config.LOGGER_FEATURE = True
        return {"status":200, "result":config.LOGGER_FEATURE}

    @staticmethod
    def setDisableLoggerFeature(*args, **kwargs) -> dict:
        if config.LOGGER_FEATURE is True:
            model.stopLogger()
            config.LOGGER_FEATURE = False
        return {"status":200, "result":config.LOGGER_FEATURE}


    def setEnableVrcMicMuteSync(self, *args, **kwargs) -> dict:
        with _OSC_CONTROL_LOCK:
            # Receiver setup may wait on networking. Never hold the mic lock here.
            ready = model.getIsOscQueryEnabled() is True
            with self._audioLock("mic"):
                if not ready:
                    return VRCTError.create_error_response(
                        ErrorCode.VRC_MIC_MUTE_SYNC_OSC_DISABLED, data=config.VRC_MIC_MUTE_SYNC)
                if config.VRC_MIC_MUTE_SYNC is True:
                    return {"status": 200, "result": True}
                config.VRC_MIC_MUTE_SYNC = True
                generation = model.invalidateMuteSelfStatus()
                model.changeMicTranscriptStatus()
        if model.setMuteSelfStatus(generation) is True:
            self._changeMicTranscriptStatusLocked()
        return {"status": 200, "result": config.VRC_MIC_MUTE_SYNC}

    def setDisableVrcMicMuteSync(self, *args, **kwargs) -> dict:
        with self._audioLock("mic"):
            if config.VRC_MIC_MUTE_SYNC is True:
                config.VRC_MIC_MUTE_SYNC = False
                model.invalidateMuteSelfStatus()
                model.changeMicTranscriptStatus()
            return {"status": 200, "result": config.VRC_MIC_MUTE_SYNC}

    def setEnableCheckSpeakerThreshold(self, data=None, *args, **kwargs) -> dict:
        with self._audioLock("speaker"):
            if not config.ENABLE_CHECK_ENERGY_RECEIVE:
                self._audioGeneration("speaker", advance=True)
                config.ENABLE_CHECK_ENERGY_RECEIVE = True
                try:
                    config.ENABLE_CHECK_ENERGY_RECEIVE = self._startCheckSpeakerEnergyLocked()
                except Exception:
                    self._disableTranscriptionAfterPipelineErrorLocked("speaker")
                    errorLogging()
            return {"status": 200, "result": config.ENABLE_CHECK_ENERGY_RECEIVE}

    def setDisableCheckSpeakerThreshold(self, data=None, *args, **kwargs) -> dict:
        with self._audioLock("speaker"):
            self._audioGeneration("speaker", advance=True)
            config.ENABLE_CHECK_ENERGY_RECEIVE = False
            self._stopCheckSpeakerEnergyLocked()
            return {"status": 200, "result": False}


    def setEnableCheckMicThreshold(self, data=None, *args, **kwargs) -> dict:
        with self._audioLock("mic"):
            if not config.ENABLE_CHECK_ENERGY_SEND:
                self._audioGeneration("mic", advance=True)
                config.ENABLE_CHECK_ENERGY_SEND = True
                try:
                    config.ENABLE_CHECK_ENERGY_SEND = self._startCheckMicEnergyLocked()
                except Exception:
                    self._disableTranscriptionAfterPipelineErrorLocked("mic")
                    errorLogging()
            return {"status": 200, "result": config.ENABLE_CHECK_ENERGY_SEND}

    def setDisableCheckMicThreshold(self, data=None, *args, **kwargs) -> dict:
        with self._audioLock("mic"):
            self._audioGeneration("mic", advance=True)
            config.ENABLE_CHECK_ENERGY_SEND = False
            self._stopCheckMicEnergyLocked()
            return {"status": 200, "result": False}


    @staticmethod
    def openFilepathLogs(*args, **kwargs) -> dict:
        Popen(['explorer', config.PATH_LOGS.replace('/', '\\')], shell=False)
        return {"status":200, "result":True}

    @staticmethod
    def openFilepathConfigFile(*args, **kwargs) -> dict:
        Popen(['explorer', config.PATH_LOCAL.replace('/', '\\')], shell=False)
        return {"status":200, "result":True}

    def setEnableTranscriptionSend(self, data=None, *args, **kwargs) -> dict:
        if self._realtimeToggles():
            return self._enableRealtimeToggle("mic", data)
        with self._audioLock("mic"):
            if config.SELECTED_TRANSCRIPTION_ENGINE is None:
                return VRCTError.create_error_response(
                    ErrorCode.TRANSCRIPTION_ENGINE_NOT_SELECTED, data=False)
            if not config.ENABLE_TRANSCRIPTION_SEND:
                self._audioGeneration("mic", advance=True)
                config.ENABLE_TRANSCRIPTION_SEND = True
                try:
                    config.ENABLE_TRANSCRIPTION_SEND = self._startTranscriptionSendMessageLocked()
                except Exception:
                    self._disableTranscriptionAfterPipelineErrorLocked("mic")
                    errorLogging()
            return {"status": 200, "result": config.ENABLE_TRANSCRIPTION_SEND}

    def setDisableTranscriptionSend(self, data=None, *args, **kwargs) -> dict:
        if not (isinstance(data, dict) and data.get("reason") == "settings_pause"):
            model.message_delivery.revoke("mic")
        if self._realtimeToggles():
            self._noteRealtimePause("mic", data)
        # A legacy recorder started before the server choice changed still stops as one.
        if self._realtimeToggles() and not config.ENABLE_TRANSCRIPTION_SEND:
            return self._disableRealtimeToggle("mic")
        with self._audioLock("mic"):
            self._audioGeneration("mic", advance=True)
            config.ENABLE_TRANSCRIPTION_SEND = False
            self._stopTranscriptionSendMessageLocked()
            return {"status": 200, "result": False}


    def setEnableTranscriptionReceive(self, data=None, *args, **kwargs) -> dict:
        if self._realtimeToggles():
            return self._enableRealtimeToggle("speaker", data)
        with self._audioLock("speaker"):
            if config.SELECTED_TRANSCRIPTION_ENGINE is None:
                return VRCTError.create_error_response(
                    ErrorCode.TRANSCRIPTION_ENGINE_NOT_SELECTED, data=False)
            if not config.ENABLE_TRANSCRIPTION_RECEIVE:
                self._audioGeneration("speaker", advance=True)
                config.ENABLE_TRANSCRIPTION_RECEIVE = True
                try:
                    config.ENABLE_TRANSCRIPTION_RECEIVE = self._startTranscriptionReceiveMessageLocked()
                except Exception:
                    self._disableTranscriptionAfterPipelineErrorLocked("speaker")
                    errorLogging()
            return {"status": 200, "result": config.ENABLE_TRANSCRIPTION_RECEIVE}

    def setDisableTranscriptionReceive(self, data=None, *args, **kwargs) -> dict:
        if not (isinstance(data, dict) and data.get("reason") == "settings_pause"):
            model.message_delivery.revoke("speaker")
        if self._realtimeToggles():
            self._noteRealtimePause("speaker", data)
        if self._realtimeToggles() and not config.ENABLE_TRANSCRIPTION_RECEIVE:
            return self._disableRealtimeToggle("speaker")
        with self._audioLock("speaker"):
            self._audioGeneration("speaker", advance=True)
            config.ENABLE_TRANSCRIPTION_RECEIVE = False
            self._stopTranscriptionReceiveMessageLocked()
            return {"status": 200, "result": False}


    def sendMessageBox(self, data, *args, **kwargs) -> dict:
        response = self.chatMessage(data)
        return response

    # Typing endpoints and the output toggle run on different IPC workers.
    _typing_lock = RLock()
    _typing_active = False

    @staticmethod
    def typingMessageBox(*args, **kwargs) -> dict:
        with Controller._typing_lock:
            if config.SEND_MESSAGE_TO_VRC is True:
                model.oscStartSendTyping()
                Controller._typing_active = True
        return {"status":200, "result":True}

    @staticmethod
    def stopTypingMessageBox(*args, **kwargs) -> dict:
        with Controller._typing_lock:
            if Controller._typing_active:
                model.oscStopSendTyping()
                Controller._typing_active = False
        return {"status":200, "result":True}

    @staticmethod
    def sendTextOverlay(data, *args, **kwargs) -> dict:
        if config.OVERLAY_SMALL_LOG is True:
            if model.overlay.initialized is True:
                current = model.overlayPublicationGuard("small")
                overlay_image = model.createOverlayImageSmallMessage(data)
                if config.OVERLAY_SMALL_LOG and current():
                    model.updateOverlaySmallLog(overlay_image, current=current)

        if config.OVERLAY_LARGE_LOG is True:
            if model.overlay.initialized is True:
                current = model.overlayPublicationGuard("large")
                overlay_image = model.createOverlayImageLargeMessage(data)
                if config.OVERLAY_LARGE_LOG and current():
                    model.updateOverlayLargeLog(overlay_image, current=current)
        return {"status":200, "result":data}


    # The notice a user answers once before any usage event is sent. Raise it when what is
    # sent changes, so that everyone is told again.
    TELEMETRY_NOTICE_VERSION = 1

    @staticmethod
    def _telemetryForcedOff() -> bool:
        """VRCT_TELEMETRY=off: no usage event is sent and the notice is not asked, whatever the settings say.

        For automated runs of the real app, and for anyone who wants it off from outside.
        """
        return os_environ.get("VRCT_TELEMETRY", "").strip().lower() == "off"

    @staticmethod
    def _telemetryAllowed() -> bool:
        """Usage events may be sent: the setting is on and the user has answered the notice."""
        return (not Controller._telemetryForcedOff() and config.ENABLE_TELEMETRY is True
                and config.TELEMETRY_NOTICE >= Controller.TELEMETRY_NOTICE_VERSION)

    @staticmethod
    def setEnableTelemetry(*args, **kwargs) -> dict:
        # Turning the setting on or off is an answer of its own: the notice is not asked again.
        config.TELEMETRY_NOTICE = Controller.TELEMETRY_NOTICE_VERSION
        config.ENABLE_TELEMETRY = True
        if Controller._telemetryAllowed():
            model.telemetryInit(enabled=True, app_version=config.VERSION)
        return {"status":200, "result":config.ENABLE_TELEMETRY}

    @staticmethod
    def setDisableTelemetry(*args, **kwargs) -> dict:
        config.TELEMETRY_NOTICE = Controller.TELEMETRY_NOTICE_VERSION
        if config.ENABLE_TELEMETRY is True:
            config.ENABLE_TELEMETRY = False
        model.telemetryShutdown()
        return {"status":200, "result":config.ENABLE_TELEMETRY}

    @staticmethod
    def getTelemetryNotice(*args, **kwargs) -> dict:
        """Whether the notice is still to be answered. Nothing is sent while it is."""
        return {"status": 200, "result": {
            "pending": (not Controller._telemetryForcedOff()
                        and config.TELEMETRY_NOTICE < Controller.TELEMETRY_NOTICE_VERSION),
            "enabled": config.ENABLE_TELEMETRY,
        }}

    @staticmethod
    def getTelemetryPreview(*args, **kwargs) -> dict:
        """What a usage event from this PC holds, for the user to read before and after choosing.

        {"endpoint", "app_started": the event as it would be sent now, "sent": what was sent, oldest first}.
        Answers while the notice is pending and while sending is off; nothing is sent by asking.
        """
        return {"status": 200, "result": model.telemetryPreview(app_version=config.VERSION)}

    @staticmethod
    def setTelemetryNotice(data, *args, **kwargs) -> dict:
        """The user's answer to the notice, {"send": bool}. Sending starts only from here."""
        if not isinstance(data, dict) or set(data) != {"send"} or type(data["send"]) is not bool:
            return {"status": 400, "result": {"error_code": "telemetry_notice_invalid"}}
        config.ENABLE_TELEMETRY = data["send"]
        config.TELEMETRY_NOTICE = Controller.TELEMETRY_NOTICE_VERSION
        if Controller._telemetryAllowed():
            model.telemetryInit(enabled=True, app_version=config.VERSION)
        else:
            model.telemetryShutdown()
        return Controller.getTelemetryNotice()

    @staticmethod
    def setEnableAutoDownloadModels(*args, **kwargs) -> dict:
        config.AUTO_DOWNLOAD_MODELS = True
        return {"status": 200, "result": config.AUTO_DOWNLOAD_MODELS}

    @staticmethod
    def setDisableAutoDownloadModels(*args, **kwargs) -> dict:
        config.AUTO_DOWNLOAD_MODELS = False
        return {"status": 200, "result": config.AUTO_DOWNLOAD_MODELS}

    def swapYourLanguageAndTargetLanguage(self, *args, **kwargs) -> dict:
        with getattr(self, "_voice_settings_lock", nullcontext()), \
                getattr(self, "_language_settings_lock", nullcontext()):
            your_languages = config.SELECTED_YOUR_LANGUAGES
            target_languages = config.SELECTED_TARGET_LANGUAGES
            tab = config.SELECTED_TAB_NO
            your_languages[tab]["1"], target_languages[tab]["1"] = (
                target_languages[tab]["1"], your_languages[tab]["1"]
            )
            config.setSelectedLanguages(your_languages, target_languages)
            self._cancelMicVoice()
            self.updateTranslationEngineAndEngineList()
            return {
                "status":200,
                "result":{
                    "your":config.SELECTED_YOUR_LANGUAGES,
                    "target":config.SELECTED_TARGET_LANGUAGES,
                }
            }

    def _runSoftwareUpdate(self, update: Callable[[Optional[str]], str], endpoint: str, target_version: Optional[str]) -> None:
        """setup.exe を取得してインストーラを起動する。起動すればアプリは終了する。
        戻ってきたら失敗なので、UI へ知らせる (UI は更新中の表示のまま待っている)。
        起動したと確かめられた (SETUP_LAUNCHED) とき以外は、すべて失敗として知らせる。"""
        result = SETUP_DOWNLOAD_FAILED
        try:
            result = update(target_version)
        except Exception:
            errorLogging()
        if result == SETUP_LAUNCHED:
            return
        error_code = ErrorCode.UPDATE_SOFTWARE_VERIFY if result == SETUP_VERIFY_FAILED else ErrorCode.UPDATE_SOFTWARE_DOWNLOAD
        error_response = VRCTError.create_error_response(error_code, data=target_version)
        self.run(error_response["status"], endpoint, error_response["result"])

    def updateSoftware(self, data:Optional[str]=None, *args, **kwargs) -> dict:
        target_version = str(data) if data else None
        th_start_update_software = Thread(target=self._runSoftwareUpdate, args=(model.updateSoftware, self.run_mapping["update_software"], target_version))
        th_start_update_software.daemon = True
        th_start_update_software.start()
        return {"status":200, "result":True}

    def updateCudaSoftware(self, data:Optional[str]=None, *args, **kwargs) -> dict:
        target_version = str(data) if data else None
        th_start_update_cuda_software = Thread(target=self._runSoftwareUpdate, args=(model.updateCudaSoftware, self.run_mapping["update_cuda_software"], target_version))
        th_start_update_cuda_software.daemon = True
        th_start_update_cuda_software.start()
        return {"status":200, "result":True}

    @staticmethod
    def _legacyDownloadConsentError(kind, data):
        if recordLegacyConsent(config, kind, data):
            return None
        weight_type = data.get("weight_type") if isinstance(data, dict) else data
        return VRCTError.create_error_response(
            ErrorCode.WEIGHT_DOWNLOAD_CONSENT_REQUIRED,
            data={"kind": kind, "weight_type": weight_type},
        )

    def _startupLegacyDownloadRequest(self, kind, weight_type):
        request = consentedLegacyRequest(config, kind, weight_type)
        if request is None:
            response = VRCTError.create_error_response(
                ErrorCode.WEIGHT_DOWNLOAD_CONSENT_REQUIRED,
                data={"kind": kind, "weight_type": weight_type, "startup": True},
            )
            self.run(response["status"], self.run_mapping[f"error_{kind}_weight"], response["result"])
        return request

    def _legacyDownloads(self):
        # Lazy fallback also supports model-free controller fixtures.
        with _LEGACY_DOWNLOAD_OWNER_LOCK:
            if getattr(self, "legacy_downloads", None) is None:
                self.legacy_downloads = LegacyDownloads()
            return self.legacy_downloads

    def _downloadLegacyWeight(self, kind, data, asynchronous):
        consent_error = self._legacyDownloadConsentError(kind, data)
        if consent_error is not None:
            return consent_error
        weight_type = data["weight_type"]
        notifier = (self.DownloadWhisper if kind == "whisper" else self.DownloadCTranslate2)(
            self.run_mapping, weight_type, self.run)
        owner = self._legacyDownloads()

        def acquire(control):
            if kind == "whisper":
                downloaded = model.downloadWhisperModelWeight(weight_type, notifier.progressBar, control=control)
                return downloaded is True and model.checkTranscriptionWhisperModelWeight(weight_type) is True
            downloaded = model.downloadCTranslate2ModelWeight(weight_type, notifier.progressBar, control=control)
            return downloaded is True and model.checkTranslatorCTranslate2ModelWeight(weight_type) is True

        try:
            owner.start((kind, weight_type), acquire, notifier.downloaded, job_id=notifier.job_id)
        except Exception as exc:
            # Rejected requests have one identified endpoint result, no worker notification.
            return VRCTError.create_error_response(
                ErrorCode.WEIGHT_WHISPER_DOWNLOAD if kind == "whisper" else ErrorCode.WEIGHT_CTRANSLATE2_DOWNLOAD,
                data={"weight_type": weight_type, "job_id": notifier.job_id,
                      "downloaded": False, "reason": str(exc),
                      "active_job_id": owner.active_job((kind, weight_type))},
            )
        if not asynchronous:
            owner.wait((kind, weight_type))
        return {"status": 200, "result": {"weight_type": weight_type, "job_id": notifier.job_id}}

    def downloadCtranslate2Weight(self, data:Any, asynchronous:bool=True, *args, **kwargs) -> dict:
        return self._downloadLegacyWeight("ctranslate2", data, asynchronous)

    def downloadWhisperWeight(self, data:Any, asynchronous:bool=True, *args, **kwargs) -> dict:
        return self._downloadLegacyWeight("whisper", data, asynchronous)

    @staticmethod
    def messageFormatter(format_type:str, translation:list, message:str, format_parts=None) -> str:
        if format_parts is not None:
            pass
        elif format_type == "RECEIVED":
            format_parts = config.RECEIVED_MESSAGE_FORMAT_PARTS
        elif format_type == "SEND":
            format_parts = config.SEND_MESSAGE_FORMAT_PARTS
        else:
            raise ValueError("format_type is not found", format_type)

        message_part = format_parts["message"]["prefix"] + message + format_parts["message"]["suffix"]
        translation_part = format_parts["translation"]["prefix"] + format_parts["translation"]["separator"].join(translation) + format_parts["translation"]["suffix"]

        if len(translation) > 0 and message != "":
            # 翻訳とメッセージの順序を決定
            if format_parts["translation_first"]:
                osc_message = translation_part + format_parts["separator"] + message_part
            else:
                osc_message = message_part + format_parts["separator"] + translation_part
        elif len(translation) > 0 and message == "":
            osc_message = translation_part
        else:
            osc_message = message_part
        return osc_message

    def changeToCTranslate2Process(self, snapshot=None) -> None:
        with getattr(self, "_voice_settings_lock", nullcontext()), \
                getattr(self, "_language_settings_lock", nullcontext()):
            if snapshot is not None and (
                    config.SELECTED_TAB_NO != snapshot.tab
                    or config.SELECTED_TRANSLATION_ENGINES[snapshot.tab] != snapshot.engine
                    or config.SELECTED_YOUR_LANGUAGES[snapshot.tab] != snapshot.your_languages
                    or config.SELECTED_TARGET_LANGUAGES[snapshot.tab] != snapshot.target_languages):
                # A late failure must not replace a newer language/engine selection.
                return
            selected_engines = config.SELECTED_TRANSLATION_ENGINES[config.SELECTED_TAB_NO]
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[selected_engines] = False
            # SELECTED_TRANSLATION_ENGINES は ValidatedProperty (生参照を返さない) なので
            # read → 変更 → 再代入する必要がある。以前は config.X[...] = ... の直接代入で
            # バリデータを一切通さずに内部状態を書き換えていた (P0-3 の生参照バグに依存していた
            # 唯一の呼び出し箇所)。
            engines = config.SELECTED_TRANSLATION_ENGINES
            engines[config.SELECTED_TAB_NO] = "CTranslate2"
            config.SELECTED_TRANSLATION_ENGINES = engines
            # Same reasoning as updateTranslationEngineAndEngineList(): if the
            # CTranslate2 weight can't translate the current languages either,
            # reset them (with a warning) instead of passing text through
            # untranslated on every following message.
            self.fallbackUnsupportedLanguagesForEngine(config.SELECTED_TAB_NO, "CTranslate2")
            selectable_engines = self.getTranslationEngines()["result"]
            self.run(200, self.run_mapping["selected_translation_engines"], config.SELECTED_TRANSLATION_ENGINES)
            self.run(200, self.run_mapping["translation_engines"], selectable_engines)

    def startTranscriptionSendMessage(self) -> bool:
        with self.mic_lifecycle_lock:
            return self._startTranscriptionSendMessageLocked()

    def _startTranscriptionSendMessageLocked(self) -> bool:
        if not config.ENABLE_TRANSCRIPTION_SEND:
            return False
        self._wireAudioSessionLocked("mic")
        self.stopRealtimeASR({"source": "mic"})
        if not self._drainRealtimeASR("mic"):
            return False
        try:
            started = model.startMicTranscript(self.micMessage)
            if not started:
                config.ENABLE_TRANSCRIPTION_SEND = False
                model.message_delivery.revoke("mic")
            return started
        except TranscriptionStartError as error:
            config.ENABLE_TRANSCRIPTION_SEND = False
            model.message_delivery.revoke("mic")
            response = VRCTError.create_error_response(error.error_code, data=False)
            self.run(response["status"], "/set/enable/transcription_send", response["result"])
            return False
        except Exception as e:
            model.message_delivery.revoke("mic")
            # VRAM不足エラーの検出
            is_vram_error, error_message = model.detectVRAMError(e)
            if is_vram_error:
                response = VRCTError.create_error_response(
                    ErrorCode.TRANSCRIPTION_VRAM_MIC,
                    data=error_message
                )
                self.run(
                    response["status"],
                    self.run_mapping["error_transcription_mic_vram_overflow"],
                    response["result"],
                )
                # ここでマイクの音声認識を停止。mic_lifecycle_lock を既に
                # 保持しているため、ロックを取り直す公開版
                # (stopTranscriptionSendMessage) ではなく内部版を呼ぶ。
                self._stopTranscriptionSendMessageLocked()
                # UI の状態同期は enable 通知ではなく、状態更新用の
                # disable endpoint へ送る。_start() が先に構造化 pipeline
                # error を通知していた場合は、micMessage() が既に config
                # を False にしているため重複通知しない。
                if config.ENABLE_TRANSCRIPTION_SEND is True:
                    self.run(
                        200,
                        self.run_mapping.get(
                            "disable_transcription_send",
                            "/set/disable/transcription_send",
                        ),
                        False,
                    )
                config.ENABLE_TRANSCRIPTION_SEND = False
                return False
            else:
                # その他のエラーは通常通り処理
                errorLogging()
                config.ENABLE_TRANSCRIPTION_SEND = False
                return False

    def _stopTranscriptionSendMessageLocked(self) -> None:
        """mic_lifecycle_lock を既に保持している呼び出し元専用。"""
        self._wireAudioSessionLocked("mic")
        model.stopMicTranscript()

    def stopTranscriptionSendMessage(self) -> None:
        with self.mic_lifecycle_lock:
            self._stopTranscriptionSendMessageLocked()

    def startTranscriptionReceiveMessage(self) -> bool:
        with self.speaker_lifecycle_lock:
            return self._startTranscriptionReceiveMessageLocked()

    def _startTranscriptionReceiveMessageLocked(self) -> bool:
        if not config.ENABLE_TRANSCRIPTION_RECEIVE:
            return False
        self._wireAudioSessionLocked("speaker")
        self.stopRealtimeASR({"source": "speaker"})
        if not self._drainRealtimeASR("speaker"):
            return False
        try:
            started = model.startSpeakerTranscript(self.speakerMessage)
            if not started:
                config.ENABLE_TRANSCRIPTION_RECEIVE = False
                model.message_delivery.revoke("speaker")
            return started
        except TranscriptionStartError as error:
            config.ENABLE_TRANSCRIPTION_RECEIVE = False
            model.message_delivery.revoke("speaker")
            response = VRCTError.create_error_response(error.error_code, data=False)
            self.run(response["status"], "/set/enable/transcription_receive", response["result"])
            return False
        except Exception as e:
            model.message_delivery.revoke("speaker")
            # VRAM不足エラーの検出
            is_vram_error, error_message = model.detectVRAMError(e)
            if is_vram_error:
                response = VRCTError.create_error_response(
                    ErrorCode.TRANSCRIPTION_VRAM_SPEAKER,
                    data=error_message
                )
                self.run(
                    response["status"],
                    self.run_mapping["error_transcription_speaker_vram_overflow"],
                    response["result"],
                )
                # ここでスピーカーの音声認識を停止 (内部版、詳細は
                # startTranscriptionSendMessage 側のコメント参照)
                self._stopTranscriptionReceiveMessageLocked()
                # Mic と同様、UI の状態同期は disable endpoint に送る。
                # pipeline error 経由で既に同期済みなら重複通知しない。
                if config.ENABLE_TRANSCRIPTION_RECEIVE is True:
                    self.run(
                        200,
                        self.run_mapping.get(
                            "disable_transcription_receive",
                            "/set/disable/transcription_receive",
                        ),
                        False,
                    )
                config.ENABLE_TRANSCRIPTION_RECEIVE = False
                return False
            else:
                # その他のエラーは通常通り処理
                errorLogging()
                config.ENABLE_TRANSCRIPTION_RECEIVE = False
                return False

    def _stopTranscriptionReceiveMessageLocked(self) -> None:
        """speaker_lifecycle_lock を既に保持している呼び出し元専用。"""
        self._wireAudioSessionLocked("speaker")
        model.stopSpeakerTranscript()

    def stopTranscriptionReceiveMessage(self) -> None:
        with self.speaker_lifecycle_lock:
            self._stopTranscriptionReceiveMessageLocked()

    def startOcrCapture(self) -> bool:
        """OCRを開始する (モデル読み込みまで済ませて戻る)。

        開始できなければ、翻訳の TRANSLATION_DISABLED_VRAM と同じく
        OCR_DISABLED_* を /run/enable_ocr_capture へ送って False を返す。
        """
        if getattr(self, "_ocr_shutting_down", False):
            return False
        try:
            return model.startOCRCapture(self.ocrMessage, model_root=self._ocrModelRoot())
        except OcrStartError as e:
            error_code = e.error_code
        except Exception:
            errorLogging()
            error_code = ErrorCode.OCR_DISABLED_UNKNOWN
        disable_response = VRCTError.create_error_response(error_code, data=False)
        self.run(
            disable_response["status"],
            self.run_mapping["enable_ocr_capture"],
            disable_response["result"],
        )
        return False

    @staticmethod
    def stopOcrCapture() -> None:
        model.stopOCRCapture()

    def _ocrModelRoot(self):
        downloads = getattr(self, "model_downloads", None)
        return getattr(downloads, "root", None)

    @staticmethod
    def getOcrCaptureStatus(*args, **kwargs) -> dict:
        """Read worker state only; never probe devices or load models for polling."""
        pipeline = getattr(model, "ocr_pipeline", None)
        active = bool(config.ENABLE_OCR_CAPTURE and pipeline is not None and pipeline.is_alive)
        runtime = pipeline.runtimeStatus if active else {
            "state": "stopped", "stage": None, "error_code": None, "detector": None}
        active = active and runtime["state"] != "stopped"
        capture = getattr(pipeline, "_capture", None) if active else None
        return {"status": 200, "result": {
            "active": active,
            "source": getattr(capture, "source", None),
            # Linux: "active" while a window the user shares is read, "ended" once it is gone.
            "shared_window": getattr(capture, "sharedWindow", None),
            "available_sources": ocr_capture.availableCaptureSources(),
            **runtime,
        }}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrPortalRestoreToken(data, *args, **kwargs) -> dict:
        """Remember what restores the shared window (Linux). The page sends what the desktop gave it.

        Saving it starts nothing: the portal is only asked when the user presses the button.
        """
        config.OCR_PORTAL_RESTORE_TOKEN = data
        return {"status": 200, "result": config.OCR_PORTAL_RESTORE_TOKEN}

    @staticmethod
    def getVrchatOscPresence(*args, **kwargs) -> dict:
        """Whether a VRChat with OSC enabled is seen on this PC: "found", "not_found" or "unknown".

        "Sent" in the log only means the message left; VRChat does not answer. This
        is the nearest thing to a receipt, and the VRChat page and the quick settings
        show it in words. "unknown" covers a destination on another machine.
        """
        return {"status": 200, "result": model.getVrchatOscPresence()}

    def getOcrReadiness(self, *args, **kwargs) -> dict:
        """What chat reading still needs before it can start (models, window).

        The Config page shows this next to the download button, and the main
        toggle reports the same reasons as OCR_DISABLED_* when it is turned on.
        Probing the window opens and closes the X11 connection / finds the
        HWND; it never captures a frame.
        """
        language = config.OCR_SOURCE_LANGUAGE
        spec = ocr_languages.resolveModelSpec(language)
        root = self._ocrModelRoot()
        required = list(spec.model_ids) if spec is not None else []
        missing = ocr_models.missingModels(root, spec) if spec is not None else []
        try:
            capture = ocr_capture.probeCapture(config.OCR_WINDOW_TITLE)
        except Exception:
            errorLogging()
            capture = ocr_capture.CAPTURE_UNAVAILABLE
        return {"status": 200, "result": {
            "engine": ocr_engine.isAvailable(),
            "language": language,
            "language_supported": spec is not None,
            "required_models": required,
            "missing_models": missing,
            "capture": capture,
            "window_title": config.OCR_WINDOW_TITLE,
            # Optional: VRCT-VOX's chatbox detector. Never a blocker for reading.
            "detector_model": ocr_chatbox_detector.DETECTOR_MODEL_ID,
            "detector_installed": ocr_chatbox_detector.isDetectorInstalled(root),
            "detector_enabled": config.OCR_USE_CHATBOX_DETECTOR is True,
            "runtime": model.getOCRRuntime(),
        }}

    @staticmethod
    def replaceExclamationsWithRandom(text):
        # ![...] にマッチする正規表現
        pattern = r'!\[(.*?)\]'

        # 乱数と置換部分を保存する辞書
        replacement_dict = {}

        num = 4096
        # マッチした部分を4096から始まる整数に置換する。置換毎に4097, 4098, ... と増える
        def replace(match):
            original = match.group(1)
            nonlocal num
            rand_value = hex(num)
            replacement_dict[rand_value] = original
            num += 1
            return f" ${rand_value} "

        # 文章内の ![] の部分を置換
        replaced_text = re.sub(pattern, replace, text)

        return replaced_text, replacement_dict

    @staticmethod
    def restoreText(escaped_text, escape_dict):
        # 大文字小文字を無視して置換するために、正規表現を使う
        for escape_seq, char in escape_dict.items():
            # escaped_text の部分を pattern で置換
            pattern = re.escape(f"${escape_seq}") + r"|\$\s+" + re.escape(escape_seq)
            escaped_text = re.sub(pattern, char, escaped_text, flags=re.IGNORECASE)
        return escaped_text

    @staticmethod
    def removeExclamations(text):
        # ![...] を [...] に置換する正規表現
        pattern = r'!\[(.*?)\]'
        # ![...] の部分を [] 内のテキストに置換
        cleaned_text = re.sub(pattern, r'\1', text)
        return cleaned_text

    def updateDownloadedCTranslate2ModelWeight(self) -> None:
        # キャッシュされた結果を使用（起動時の重複チェックを回避）
        if hasattr(self, '_ctranslate2_available_cache'):
            # 起動時のキャッシュを使用: 選択中の重みタイプのみ設定
            config.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT[config.CTRANSLATE2_WEIGHT_TYPE] = self._ctranslate2_available_cache
        
        # すべての重みタイプをチェック（キャッシュされていないものだけ）
        for weight_type in config.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT.keys():
            # 選択中のウェイトはキャッシュで設定済みなのでスキップ
            if hasattr(self, '_ctranslate2_available_cache') and weight_type == config.CTRANSLATE2_WEIGHT_TYPE:
                continue
            config.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT[weight_type] = model.checkTranslatorCTranslate2ModelWeight(weight_type)

    def updateTranslationEngineAndEngineList(self):
        with getattr(self, "_language_settings_lock", nullcontext()):
            self._updateTranslationEngineAndEngineListLocked()

    def _updateTranslationEngineAndEngineListLocked(self):
        engines = config.SELECTED_TRANSLATION_ENGINES
        engine = engines[config.SELECTED_TAB_NO]
        selectable_engines = self.getTranslationEngines()["result"]
        if engine not in selectable_engines:
            engine = "CTranslate2"
        engines[config.SELECTED_TAB_NO] = engine
        config.SELECTED_TRANSLATION_ENGINES = engines

        your_language = config.SELECTED_YOUR_LANGUAGES[config.SELECTED_TAB_NO]["1"]
        for target_language in config.SELECTED_TARGET_LANGUAGES[config.SELECTED_TAB_NO].values():
            if your_language["language"] == target_language["language"] and target_language["enable"] is True:
                engine = "CTranslate2"
                engines[config.SELECTED_TAB_NO] = engine
                config.SELECTED_TRANSLATION_ENGINES = engines
                break

        # CTranslate2 is the engine everything above falls back to, but it
        # doesn't support every language either (e.g. Arabic isn't in the
        # nllb-200 weight tables). When even CTranslate2 can't handle the
        # current language selection, there's no further engine to fall
        # back to - reset the language itself instead, or the UI ends up
        # with a selected engine that's simultaneously shown as
        # unavailable/greyed out.
        if self.fallbackUnsupportedLanguagesForEngine(config.SELECTED_TAB_NO, engine):
            selectable_engines = self.getTranslationEngines()["result"]

        self.run(200, self.run_mapping["selected_translation_engines"], config.SELECTED_TRANSLATION_ENGINES)
        self.run(200, self.run_mapping["translation_engines"], selectable_engines)

    def fallbackUnsupportedLanguagesForEngine(self, tab_no: str, engine: str) -> bool:
        """Reset any language on `tab_no` that `engine` doesn't support back
        to a default language `engine` does support (preferring Japanese
        source / English target, the app's own defaults).

        This is the mirror of updateTranslationEngineAndEngineList(), which
        falls the ENGINE back to CTranslate2 when the LANGUAGE changes to
        something the current engine doesn't support. Without this,
        changing the engine first and leaving an unsupported language in
        place goes unnoticed until a translation is actually attempted.

        The default is chosen to avoid the tab's other enabled language
        slots: resetting the source straight to "Japanese" while an enabled
        target is already "Japanese" would make source == target, which
        updateTranslationEngineAndEngineList() treats as a reason to force
        the engine back to CTranslate2 - silently undoing the very engine
        selection this fallback exists to preserve.

        Returns True if any language was reset.
        """
        changed = False

        your_languages = copy.deepcopy(config.SELECTED_YOUR_LANGUAGES)
        target_languages = copy.deepcopy(config.SELECTED_TARGET_LANGUAGES)

        your_language = your_languages[tab_no]["1"]
        enabled_target_languages = {
            target_language["language"]
            for target_language in target_languages[tab_no].values()
            if target_language["enable"] is True
        }
        reset_languages = []
        if not model.isLanguageSupportedByEngine(engine, your_language["language"]):
            default = model.pickDefaultLanguageForEngine(engine, enabled_target_languages)
            if default is not None:
                reset_languages.append(your_language["language"])
                your_languages[tab_no]["1"] = {**default, "enable": True}
                config.SELECTED_YOUR_LANGUAGES = your_languages
                changed = True
                your_language = your_languages[tab_no]["1"]

        target_changed = False
        # Accumulate languages already spoken for as we go, so two
        # simultaneously-unsupported enabled targets can't both get reset
        # to the same default language.
        taken_languages = {your_language["language"]}
        for target_language in target_languages[tab_no].values():
            if target_language["enable"] is not True:
                continue
            if model.isLanguageSupportedByEngine(engine, target_language["language"]):
                taken_languages.add(target_language["language"])
                continue
            default = model.pickDefaultLanguageForEngine(engine, taken_languages)
            if default is not None:
                reset_languages.append(target_language["language"])
                target_language["language"] = default["language"]
                target_language["country"] = default["country"]
                target_changed = True
            taken_languages.add(target_language["language"])
        if target_changed:
            config.SELECTED_TARGET_LANGUAGES = target_languages
            changed = True

        if changed:
            self.run(200, self.run_mapping["selected_your_languages"], config.SELECTED_YOUR_LANGUAGES)
            self.run(200, self.run_mapping["selected_target_languages"], config.SELECTED_TARGET_LANGUAGES)
            self._notifyUnsupportedLanguagesReset(engine, reset_languages)

        return changed

    def _notifyUnsupportedLanguagesReset(self, engine: str, languages: list) -> None:
        """Tell the user which languages were reset and why. Without this
        the language dropdown just changes, which looks like a UI glitch
        (most visibly after switching from an NLLB weight to M2M100)."""
        endpoint = self.run_mapping.get("translation_language_unsupported")
        if endpoint is None or not languages:
            return
        error_response = VRCTError.create_error_response(
            ErrorCode.TRANSLATION_LANGUAGE_UNSUPPORTED,
            data={
                "engine": engine,
                "weight_type": config.CTRANSLATE2_WEIGHT_TYPE if engine == "CTranslate2" else None,
                "languages": list(dict.fromkeys(languages)),
            },
        )
        self.run(error_response["status"], endpoint, error_response["result"])

    def notifyNonCommercialCTranslate2Weight(self) -> None:
        """One-time notice for a non-commercial weight saved by an older
        version. Before M2M100 became the default, every install was given
        nllb-200-distilled-600M (CC-BY-NC-4.0) without being asked, so the
        saved value usually isn't an informed choice. The setting itself is
        kept; this only tells the user and points at Config -> Translation."""
        weight_type = config.CTRANSLATE2_WEIGHT_TYPE
        if config.CTRANSLATE2_LICENSE_NOTICE_SHOWN is True or not isNonCommercialCTranslate2Weight(weight_type):
            return
        error_response = VRCTError.create_error_response(
            ErrorCode.WEIGHT_CTRANSLATE2_NON_COMMERCIAL_NOTICE,
            data={"weight_type": weight_type, "license": ctranslate2_weights[weight_type]["license"]},
        )
        self.run(error_response["status"], self.run_mapping["ctranslate2_license_notice"], error_response["result"])
        config.CTRANSLATE2_LICENSE_NOTICE_SHOWN = True

    def updateDownloadedWhisperModelWeight(self) -> None:
        # キャッシュされた結果を使用（起動時の重複チェックを回避）
        if hasattr(self, '_whisper_available_cache'):
            # 起動時のキャッシュを使用: 選択中の重みタイプのみ設定
            config.SELECTABLE_WHISPER_WEIGHT_TYPE_DICT[config.WHISPER_WEIGHT_TYPE] = self._whisper_available_cache
        
        # すべての重みタイプをチェック（キャッシュされていないものだけ）
        for weight_type in config.SELECTABLE_WHISPER_WEIGHT_TYPE_DICT.keys():
            # 選択中のウェイトはキャッシュで設定済みなのでスキップ
            if hasattr(self, '_whisper_available_cache') and weight_type == config.WHISPER_WEIGHT_TYPE:
                continue
            config.SELECTABLE_WHISPER_WEIGHT_TYPE_DICT[weight_type] = model.checkTranscriptionWhisperModelWeight(weight_type)

    def updateTranscriptionEngine(self, requested_engine: Optional[str] = None) -> None:
        """Apply explicit selections only; availability never changes consent."""
        previous_engine = config.SELECTED_TRANSCRIPTION_ENGINE
        if requested_engine is not None:
            config.SELECTED_TRANSCRIPTION_ENGINE = requested_engine

        if config.SELECTED_TRANSCRIPTION_ENGINE != previous_engine:
            self.fallbackUnsupportedLanguagesForTranscriptionEngine(config.SELECTED_TRANSCRIPTION_ENGINE)
            self.run(200, self.run_mapping["selectable_language_list"], model.getListLanguageAndCountry())

    def startCheckMicEnergy(self) -> bool:
        with self.mic_lifecycle_lock:
            return self._startCheckMicEnergyLocked()

    def _startCheckMicEnergyLocked(self) -> bool:
        if not config.ENABLE_CHECK_ENERGY_SEND:
            return False
        self._wireAudioSessionLocked("mic")
        with self._realtime_lock:
            if self._realtime_requested["mic"]:
                return False
        if not self._drainRealtimeASR("mic"):
            return False
        return model.startCheckMicEnergy(self.progressBarMicEnergy)

    def stopCheckMicEnergy(self) -> None:
        with self.mic_lifecycle_lock:
            return self._stopCheckMicEnergyLocked()

    def _stopCheckMicEnergyLocked(self) -> None:
        self._wireAudioSessionLocked("mic")
        model.stopCheckMicEnergy()

    def startCheckSpeakerEnergy(self) -> bool:
        with self.speaker_lifecycle_lock:
            return self._startCheckSpeakerEnergyLocked()

    def _startCheckSpeakerEnergyLocked(self) -> bool:
        if not config.ENABLE_CHECK_ENERGY_RECEIVE:
            return False
        self._wireAudioSessionLocked("speaker")
        with self._realtime_lock:
            if self._realtime_requested["speaker"]:
                return False
        if not self._drainRealtimeASR("speaker"):
            return False
        return model.startCheckSpeakerEnergy(self.progressBarSpeakerEnergy)

    def stopCheckSpeakerEnergy(self) -> None:
        with self.speaker_lifecycle_lock:
            return self._stopCheckSpeakerEnergyLocked()

    def _stopCheckSpeakerEnergyLocked(self) -> None:
        self._wireAudioSessionLocked("speaker")
        model.stopCheckSpeakerEnergy()

    @staticmethod
    def startWatchdog(*args, **kwargs) -> dict:
        model.startWatchdog()
        return {"status":200, "result":True}

    @staticmethod
    def feedWatchdog(*args, **kwargs) -> dict:
        model.feedWatchdog()
        return {"status":200, "result":True}

    @staticmethod
    def setWatchdogCallback(callback) -> dict:
        model.setWatchdogCallback(callback)
        return {"status":200, "result":True}

    @staticmethod
    def stopWatchdog(*args, **kwargs) -> dict:
        model.stopWatchdog()
        return {"status":200, "result":True}


    @staticmethod
    def _restoreWebSocketServer(*, restore_obs: bool = False) -> None:
        """ホストやポートの変更に失敗したあと、元のアドレスでサーバーを立て直す。

        止めている間に元のポートをほかのプロセスが取ると、立て直しも失敗する。そのときは
        WebSocket と、それに頼る OBS ブラウザソースをオフにする。オンのまま残すと、
        有効と表示されたまま何も配信しない。UI はエラーを受けてこの2つを読み直す。
        """
        if model.startWebSocketServer(config.WEBSOCKET_HOST, config.WEBSOCKET_PORT):
            if restore_obs:
                Controller._restoreObsBrowserSourceServer()
            return
        printLog("WebSocket server could not be restored on its previous address")
        if config.OBS_BROWSER_SOURCE is True:
            config.OBS_BROWSER_SOURCE = False
            model.stopObsBrowserSourceServer()
        config.WEBSOCKET_SERVER = False

    @staticmethod
    def _restoreObsBrowserSourceServer() -> None:
        """Restore the saved OBS address, or expose the failed restore as off."""
        if not model.startObsBrowserSourceServer(config.WEBSOCKET_HOST, config.OBS_BROWSER_SOURCE_PORT):
            model.stopObsBrowserSourceServer()
            config.OBS_BROWSER_SOURCE = False

    @staticmethod
    def setWebSocketHost(data, *args, **kwargs) -> dict:
        # 0.0.0.0/:: (ワイルドカードアドレス) は「マシンが持つ全インター
        # フェースで listen する」ことを意味し、WebSocket サーバーは
        # 認証 (token) を導入済みとはいえ、同一 LAN 上の第三者からの
        # 到達性まで許してしまう。特定の LAN IP を明示的に選ぶのとは
        # リスクの性質が異なるため、他の IP 検証と分けて拒否する。
        try:
            if not isValidWebSocketHost(data):
                response = VRCTError.create_error_response(
                    ErrorCode.VALIDATION_INVALID_IP,
                    data=config.WEBSOCKET_HOST
                )
            else:
                if model.checkWebSocketServerAlive() is False:
                    # Also cancel an attempt still binding the previous address.
                    model.stopWebSocketServer()
                    config.WEBSOCKET_HOST = data
                    response = {"status":200, "result":config.WEBSOCKET_HOST}
                else:
                    if data == config.WEBSOCKET_HOST:
                        response = {"status":200, "result":config.WEBSOCKET_HOST}
                    elif isAvailableWebSocketServer(data, config.WEBSOCKET_PORT):
                        model.stopWebSocketServer()
                        if not model.startWebSocketServer(data, config.WEBSOCKET_PORT):
                            # 新しいアドレスで bind できなかった。元のアドレスで立て直す
                            Controller._restoreWebSocketServer()
                            return VRCTError.create_error_response(
                                ErrorCode.WEBSOCKET_HOST_INVALID,
                                data=config.WEBSOCKET_HOST
                            )
                        # The OBS overlay's HTTP server must stay bound to the
                        # same host the WebSocket server now listens on, or the
                        # overlay page it serves will point at a dead address.
                        if config.OBS_BROWSER_SOURCE is True:
                            model.stopObsBrowserSourceServer()
                            if not model.startObsBrowserSourceServer(data, int(config.OBS_BROWSER_SOURCE_PORT)):
                                model.stopObsBrowserSourceServer()
                                model.stopWebSocketServer()
                                Controller._restoreWebSocketServer(restore_obs=True)
                                return VRCTError.create_error_response(
                                    ErrorCode.OBS_BROWSER_SOURCE_HOST_UNAVAILABLE,
                                    data=config.WEBSOCKET_HOST,
                                )
                        # Commit only once both listeners are ready. Rollback
                        # above uses the unchanged, previously saved address.
                        config.WEBSOCKET_HOST = data
                        response = {"status":200, "result":config.WEBSOCKET_HOST}
                    else:
                        response = VRCTError.create_error_response(
                            ErrorCode.WEBSOCKET_HOST_INVALID,
                            data=config.WEBSOCKET_HOST
                        )
        except Exception:
            errorLogging()
            response = VRCTError.create_error_response(
                ErrorCode.WEBSOCKET_HOST_INVALID,
                data=config.WEBSOCKET_HOST,
            )

        return response


    @staticmethod
    def setWebSocketPort(data, *args, **kwargs) -> dict:
        if not isValidPort(data):
            return VRCTError.create_error_response(
                ErrorCode.WEBSOCKET_PORT_INVALID,
                data=config.WEBSOCKET_PORT,
            )
        port = data

        try:
            if model.checkWebSocketServerAlive() is False:
                model.stopWebSocketServer()
                config.WEBSOCKET_PORT = port
                response = {"status":200, "result":config.WEBSOCKET_PORT}
            else:
                if port == config.WEBSOCKET_PORT:
                    return {"status":200, "result":config.WEBSOCKET_PORT}
                elif isAvailableWebSocketServer(config.WEBSOCKET_HOST, port) is True:
                    model.stopWebSocketServer()
                    if model.startWebSocketServer(config.WEBSOCKET_HOST, port):
                        config.WEBSOCKET_PORT = port
                        response = {"status":200, "result":config.WEBSOCKET_PORT}
                    else:
                        # 新しいポートで bind できなかった。元のポートで立て直す
                        Controller._restoreWebSocketServer()
                        response = VRCTError.create_error_response(
                            ErrorCode.WEBSOCKET_PORT_UNAVAILABLE,
                            data=config.WEBSOCKET_PORT
                        )
                else:
                    response = VRCTError.create_error_response(
                        ErrorCode.WEBSOCKET_PORT_UNAVAILABLE,
                        data=config.WEBSOCKET_PORT
                    )
        except Exception:
            errorLogging()
            response = VRCTError.create_error_response(
                ErrorCode.WEBSOCKET_PORT_UNAVAILABLE,
                data=config.WEBSOCKET_PORT,
            )
        return response

    @staticmethod
    def getWebSocketAuthToken(*args, **kwargs) -> dict:
        """WebSocket サーバーへの接続に必要なトークンを返す。

        OBS Browser Source はサーバー側が生成するページに自動で埋め込むため
        これを直接使う必要はないが、VRCT-TTS のように接続 URL をユーザーが
        手動入力する外部連携ツール向けに、UI 側で
        `ws://{host}:{port}/?token={token}` をコピーできるようにするために
        公開する。
        """
        return {"status":200, "result":config.WEBSOCKET_AUTH_TOKEN}


    @staticmethod
    def setEnableWebSocketServer(*args, **kwargs) -> dict:
        try:
            if config.WEBSOCKET_SERVER is False:
                if (
                    isAvailableWebSocketServer(config.WEBSOCKET_HOST, config.WEBSOCKET_PORT) is True
                    and model.startWebSocketServer(config.WEBSOCKET_HOST, config.WEBSOCKET_PORT)
                ):
                    config.WEBSOCKET_SERVER = True
                    response = {"status":200, "result":config.WEBSOCKET_SERVER}
                else:
                    response = VRCTError.create_error_response(
                        ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE,
                        data=config.WEBSOCKET_SERVER
                    )
            else:
                response = {"status":200, "result":config.WEBSOCKET_SERVER}
        except Exception:
            errorLogging()
            response = VRCTError.create_error_response(
                ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE,
                data=config.WEBSOCKET_SERVER,
            )
        return response

    @staticmethod
    def setDisableWebSocketServer(*args, **kwargs) -> dict:
        if config.WEBSOCKET_SERVER is True:
            # OBS Browser Source overlay receives its messages through this
            # WebSocket server; stopping the server without also disabling
            # OBS Browser Source would leave config.OBS_BROWSER_SOURCE stuck
            # at True while the overlay silently stops updating.
            if config.OBS_BROWSER_SOURCE is True:
                config.OBS_BROWSER_SOURCE = False
                model.stopObsBrowserSourceServer()
            config.WEBSOCKET_SERVER = False
        # The config remains False until startup succeeds. Stop must reach an
        # in-flight enable too (including one requested by OBS).
        model.stopWebSocketServer()
        return {"status":200, "result":config.WEBSOCKET_SERVER}

    # OBS Browser Source (local overlay for OBS)

    @staticmethod
    def setEnableObsBrowserSource(*args, **kwargs) -> dict:
        if config.OBS_BROWSER_SOURCE is True:
            return {"status":200, "result":config.OBS_BROWSER_SOURCE}

        # The dispatcher holds the shared OBS/WebSocket lifecycle lock. No
        # other IPC operation can acquire this attempt's WebSocket before its
        # cleanup; an already running WebSocket remains independently owned.
        started_websocket = False
        obs_attempted = False
        try:
            if model.checkWebSocketServerAlive() is False:
                if (
                    isAvailableWebSocketServer(config.WEBSOCKET_HOST, config.WEBSOCKET_PORT) is not True
                    or not model.startWebSocketServer(config.WEBSOCKET_HOST, config.WEBSOCKET_PORT)
                ):
                    return VRCTError.create_error_response(
                        ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE,
                        data=config.OBS_BROWSER_SOURCE,
                    )
                started_websocket = True

            obs_host = config.WEBSOCKET_HOST
            obs_port = int(config.OBS_BROWSER_SOURCE_PORT)

            if isAvailableWebSocketServer(obs_host, obs_port) is not True:
                return VRCTError.create_error_response(
                    ErrorCode.OBS_BROWSER_SOURCE_PORT_UNAVAILABLE,
                    data=config.OBS_BROWSER_SOURCE,
                )

            obs_attempted = True
            if not model.startObsBrowserSourceServer(obs_host, obs_port):
                return VRCTError.create_error_response(
                    ErrorCode.OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE,
                    data=config.OBS_BROWSER_SOURCE,
                )

            config.WEBSOCKET_SERVER = True
            config.OBS_BROWSER_SOURCE = True
            return {"status":200, "result":config.OBS_BROWSER_SOURCE}
        except Exception:
            errorLogging()
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE,
                data=config.OBS_BROWSER_SOURCE,
            )
        finally:
            if config.OBS_BROWSER_SOURCE is not True:
                if obs_attempted:
                    model.stopObsBrowserSourceServer()
                if started_websocket:
                    model.stopWebSocketServer()
                    config.WEBSOCKET_SERVER = False

    @staticmethod
    def setDisableObsBrowserSource(*args, **kwargs) -> dict:
        if config.OBS_BROWSER_SOURCE is True:
            config.OBS_BROWSER_SOURCE = False
            model.stopObsBrowserSourceServer()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE}


    @staticmethod
    def setObsBrowserSourcePort(data, *args, **kwargs) -> dict:
        if not isValidPort(data):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_PORT_INVALID,
                data=config.OBS_BROWSER_SOURCE_PORT,
            )
        port = data

        if model.checkObsBrowserSourceServerAlive() is not True:
            config.OBS_BROWSER_SOURCE_PORT = port
            return {"status":200, "result":config.OBS_BROWSER_SOURCE_PORT}

        if port == config.OBS_BROWSER_SOURCE_PORT:
            return {"status":200, "result":config.OBS_BROWSER_SOURCE_PORT}

        if isAvailableWebSocketServer(config.WEBSOCKET_HOST, port) is not True:
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_PORT_UNAVAILABLE,
                data=config.OBS_BROWSER_SOURCE_PORT
            )

        model.stopObsBrowserSourceServer()
        if not model.startObsBrowserSourceServer(config.WEBSOCKET_HOST, port):
            model.stopObsBrowserSourceServer()
            Controller._restoreObsBrowserSourceServer()
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE,
                data=config.OBS_BROWSER_SOURCE_PORT,
            )

        config.OBS_BROWSER_SOURCE_PORT = port
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_PORT}

    def _pushObsBrowserSourceSettings(self) -> None:
        """Notify any already-open OBS overlay pages that display settings
        changed, so they can apply them live instead of waiting for the
        next page load (OBS Browser Sources normally cache the page and
        never refetch it on their own).
        """
        if config.OBS_BROWSER_SOURCE is not True:
            return
        if model.checkWebSocketServerAlive() is not True:
            return
        model.websocketSendMessage({
            "type": "SETTINGS_UPDATED",
            "settings": {
                "maxMessages": config.OBS_BROWSER_SOURCE_MAX_MESSAGES,
                "displayDuration": config.OBS_BROWSER_SOURCE_DISPLAY_DURATION,
                "fadeoutDuration": config.OBS_BROWSER_SOURCE_FADEOUT_DURATION,
                "fontSize": config.OBS_BROWSER_SOURCE_FONT_SIZE,
                "fontColor": config.OBS_BROWSER_SOURCE_FONT_COLOR,
                "outlineThickness": config.OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS,
                "outlineColor": config.OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR,
            },
        })


    def setObsBrowserSourceMaxMessages(self, data, *args, **kwargs) -> dict:
        try:
            value = parse_numeric_setting("MAX_MESSAGES", data)
        except (ValueError, TypeError):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_MAX_MESSAGES_INVALID,
                data=config.OBS_BROWSER_SOURCE_MAX_MESSAGES,
                custom_message="Enter a whole number from 1 to 50",
            )
        config.OBS_BROWSER_SOURCE_MAX_MESSAGES = value
        self._pushObsBrowserSourceSettings()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_MAX_MESSAGES}


    def setObsBrowserSourceDisplayDuration(self, data, *args, **kwargs) -> dict:
        try:
            value = parse_numeric_setting("DISPLAY_DURATION", data)
        except (ValueError, TypeError):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_DISPLAY_DURATION_INVALID,
                data=config.OBS_BROWSER_SOURCE_DISPLAY_DURATION,
                custom_message="Enter a whole number from 1 to 120",
            )
        config.OBS_BROWSER_SOURCE_DISPLAY_DURATION = value
        self._pushObsBrowserSourceSettings()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_DISPLAY_DURATION}


    def setObsBrowserSourceFadeoutDuration(self, data, *args, **kwargs) -> dict:
        try:
            value = parse_numeric_setting("FADEOUT_DURATION", data)
        except (ValueError, TypeError):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_FADEOUT_DURATION_INVALID,
                data=config.OBS_BROWSER_SOURCE_FADEOUT_DURATION,
                custom_message="Enter a whole number from 0 to 120",
            )
        config.OBS_BROWSER_SOURCE_FADEOUT_DURATION = value
        self._pushObsBrowserSourceSettings()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_FADEOUT_DURATION}


    def setObsBrowserSourceFontSize(self, data, *args, **kwargs) -> dict:
        try:
            value = parse_numeric_setting("FONT_SIZE", data)
        except (ValueError, TypeError):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_FONT_SIZE_INVALID,
                data=config.OBS_BROWSER_SOURCE_FONT_SIZE,
                custom_message="Enter a whole number from 10 to 200",
            )
        config.OBS_BROWSER_SOURCE_FONT_SIZE = value
        self._pushObsBrowserSourceSettings()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_FONT_SIZE}


    def setObsBrowserSourceFontColor(self, data, *args, **kwargs) -> dict:
        color = str(data).strip()
        if not _HEX_COLOR_RE.match(color):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_FONT_COLOR_INVALID,
                data=config.OBS_BROWSER_SOURCE_FONT_COLOR,
            )
        config.OBS_BROWSER_SOURCE_FONT_COLOR = color.upper()
        self._pushObsBrowserSourceSettings()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_FONT_COLOR}


    def setObsBrowserSourceFontOutlineThickness(self, data, *args, **kwargs) -> dict:
        try:
            value = parse_numeric_setting("FONT_OUTLINE_THICKNESS", data)
        except (ValueError, TypeError):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS_INVALID,
                data=config.OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS,
                custom_message="Enter a whole number from 0 to 20",
            )
        config.OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS = value
        self._pushObsBrowserSourceSettings()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS}


    def setObsBrowserSourceFontOutlineColor(self, data, *args, **kwargs) -> dict:
        color = str(data).strip()
        if not _HEX_COLOR_RE.match(color):
            return VRCTError.create_error_response(
                ErrorCode.OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR_INVALID,
                data=config.OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR,
            )
        config.OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR = color.upper()
        self._pushObsBrowserSourceSettings()
        return {"status":200, "result":config.OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR}

    # Clipboard control

    @staticmethod
    def setEnableClipboard(*args, **kwargs) -> dict:
        if config.ENABLE_CLIPBOARD is False:
            config.ENABLE_CLIPBOARD = True
        return {"status":200, "result":config.ENABLE_CLIPBOARD}

    @staticmethod
    def setDisableClipboard(*args, **kwargs) -> dict:
        if config.ENABLE_CLIPBOARD is True:
            config.ENABLE_CLIPBOARD = False
        return {"status":200, "result":config.ENABLE_CLIPBOARD}

    # ---------- VRChat chat-bubble OCR settings ----------

    def setEnableOcrCapture(self, *args, **kwargs) -> dict:
        with _OCR_CONTROL_LOCK:
            if getattr(self, "_ocr_shutting_down", False):
                return {"status": 200, "result": False}
            enabled = config.ENABLE_OCR_CAPTURE
        if enabled is False:
            started = self.startOcrCapture()
            with _OCR_CONTROL_LOCK:
                config.ENABLE_OCR_CAPTURE = started and not getattr(self, "_ocr_shutting_down", False)
        return {"status": 200, "result": config.ENABLE_OCR_CAPTURE}

    def setDisableOcrCapture(self, *args, **kwargs) -> dict:
        model.message_delivery.revoke("ocr")
        if config.ENABLE_OCR_CAPTURE is True:
            config.ENABLE_OCR_CAPTURE = False
            self.stopOcrCapture()
        return {"status": 200, "result": config.ENABLE_OCR_CAPTURE}

    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrSourceLanguage(self, data, *args, **kwargs) -> dict:
        previous = config.OCR_SOURCE_LANGUAGE
        language = str(data)
        if language not in ocr_languages.SELECTABLE_LANGUAGES:
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=previous)
        try:
            if not model.setOCRSourceLanguage(language, model_root=self._ocrModelRoot()):
                return {"status": 423, "result": previous}
        except OcrStartError as exc:
            return VRCTError.create_error_response(
                exc.error_code, data=previous,
                details={"requested_language": language, "previous_language": previous})
        return {"status":200, "result":config.OCR_SOURCE_LANGUAGE}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrWindowTitle(data, *args, **kwargs) -> dict:
        config.OCR_WINDOW_TITLE = str(data).strip()
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_WINDOW_TITLE}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrPollIntervalMs(data, *args, **kwargs) -> dict:
        config.OCR_POLL_INTERVAL_MS = data
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_POLL_INTERVAL_MS}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrMinConfidence(data, *args, **kwargs) -> dict:
        config.OCR_MIN_CONFIDENCE = data
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_MIN_CONFIDENCE}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrBubbleMinTextLength(data, *args, **kwargs) -> dict:
        config.OCR_BUBBLE_MIN_TEXT_LENGTH = data
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_BUBBLE_MIN_TEXT_LENGTH}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrCaptureRegion(data, *args, **kwargs) -> dict:
        # Round so slider jitter does not produce 17-digit values in config.json.
        if isinstance(data, dict):
            data = {k: round(v, 4) if isinstance(v, float) else v for k, v in data.items()}
        config.OCR_CAPTURE_REGION = data
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_CAPTURE_REGION}

    @staticmethod
    @_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)
    def setOcrVrCaptureRegion(data, *args, **kwargs) -> dict:
        if isinstance(data, dict):
            data = {k: round(v, 4) if isinstance(v, float) else v for k, v in data.items()}
        config.OCR_VR_CAPTURE_REGION = data
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_VR_CAPTURE_REGION}

    @staticmethod
    def setEnableOcrChatboxFilter(*args, **kwargs) -> dict:
        config.OCR_CHATBOX_FILTER = True
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_CHATBOX_FILTER}

    @staticmethod
    def setDisableOcrChatboxFilter(*args, **kwargs) -> dict:
        config.OCR_CHATBOX_FILTER = False
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_CHATBOX_FILTER}

    @staticmethod
    def setEnableOcrUseChatboxDetector(*args, **kwargs) -> dict:
        config.OCR_USE_CHATBOX_DETECTOR = True
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_USE_CHATBOX_DETECTOR}

    @staticmethod
    def setDisableOcrUseChatboxDetector(*args, **kwargs) -> dict:
        config.OCR_USE_CHATBOX_DETECTOR = False
        model.updateOCRCaptureSettings()
        return {"status":200, "result":config.OCR_USE_CHATBOX_DETECTOR}

    def initializationProgress(self, progress):
        self.run(200, self.run_mapping["initialization_progress"], progress)

    def enableOscQuery(self):
        self.run(
            200,
            self.run_mapping["enable_osc_query"],
            {
                "data": True,
                "disabled_functions": []
            }
        )

    def disableOscQuery(self, mute_sync_info:bool=False, *, reason:str="setup_failed", microphone_stopped:bool=False):
        """受信と公開が使えないことを UI へ知らせる。

        reason は、送信先が別のマシン ("remote_destination") か、この PC 宛てなのに準備に失敗したか
        ("setup_failed")。microphone_stopped は、同期がオンだったのでマイク入力を止めたかどうか。
        UI はこの 2 つで文言を選ぶ。以前は 1 つの文言で、別のマシン宛ての人にも「ローカルの OSC 設定を
        保存し直してください」と案内し、何も止めていなくても「マイク入力も停止しています」と書いていた。
        """
        disabled_functions = []
        if mute_sync_info is True:
            disabled_functions.append("vrc_mic_mute_sync")
        self.run(200, self.run_mapping["enable_osc_query"], {
            "data": False,
            "disabled_functions": disabled_functions,
            "reason": reason,
            "microphone_stopped": microphone_stopped,
        })

    def _publishOscQueryReadiness(self, *, startup: bool = False):
        # A cancelled background startup must not rewrite saved user intent.
        if getattr(model, "_osc_shutdown", False) is True:
            return
        if model.getIsOscQueryEnabled() is True:
            self.enableOscQuery()
            return
        # 起動しただけで、何も止めておらず、送信先が別のマシン (設定で選んだ状態) なら、知らせない。
        # 単体のヘッドセットへ送っている人には、毎回の起動で同じ警告が 10 秒出ていた。同期の欄には
        # 使えない理由が出ているし、同期をオンにしようとすれば VRC_MIC_MUTE_SYNC_OSC_DISABLED で断る。
        # 同期を止めたとき、設定を変えた直後、この PC 宛てなのに準備に失敗したときは、これまでどおり知らせる。
        notify = True
        stopped = False
        remote = model.usesOscQuery(config.OSC_IP_ADDRESS) is False
        try:
            with self._audioLock("mic"):
                if config.VRC_MIC_MUTE_SYNC is True:
                    stopped = True
                    # Losing sync must not resume a private microphone. Turn input off
                    # before disabling sync; restarting input remains a user action.
                    model.invalidateMuteSelfStatus()
                    model.changeMicTranscriptStatus()
                    self.setDisableTranscriptionSend()
                    self.run(200, "/set/disable/transcription_send", False)
                    config.VRC_MIC_MUTE_SYNC = False
                    model.invalidateMuteSelfStatus()
                    self.run(200, "/set/disable/vrc_mic_mute_sync", False)
                elif startup and remote:
                    notify = False
        finally:
            self.disableOscQuery(mute_sync_info=notify, reason="remote_destination" if remote else "setup_failed",
                                 microphone_stopped=stopped)

    def _initVrcMicMuteSync(self) -> None:
        with self._audioLock("mic"):
            if config.VRC_MIC_MUTE_SYNC is not True:
                return
            generation = model.invalidateMuteSelfStatus()
            model.changeMicTranscriptStatus()
        if model.setMuteSelfStatus(generation) is True:
            self._changeMicTranscriptStatusLocked()

    def _initOscReceive(self):
        with _OSC_CONTROL_LOCK:
            try:
                model.startReceiveOSC()
            except Exception:
                printLog("OSC: receive/advertisement setup failed")
            finally:
                self._publishOscQueryReadiness(startup=True)
        if model.getIsOscQueryEnabled() is True:
            self._initVrcMicMuteSync()

    def _bootstrapModel(self) -> None:
        """`model.init()` + ミュート同期コールバック登録 (フェーズ3項目22)。

        以前は `Controller.__init__` (`Controller()` 構築時、本番では
        mainloop.py のモジュールimport時) に前倒しで実行していたが、
        `model.init()` 自身が「import時には呼ばない、ensure_initialized()
        で遅延初期化する」設計であることに合わせて `init()` 側に移動した。

        経緯: 一度この移動を実装した際、実機検証で「VRCTをVRChatより先に
        起動するとOSCQueryが接続されずミュート同期が壊れる」回帰が見つかり
        タイミングを一旦元に戻した。その後の調査で、この回帰は今回の
        タイミング変更とは無関係の既存バグ (起動時1回きりの
        `model.setMuteSelfStatus()` がVRChat未起動時に失敗すると
        `model.mic_mute_status` が `None` のまま二度と回復しない構造的な
        問題) と判明し、別修正で解決済み (現在は VRChat のアバター読み込み時の
        `/avatar/change` で読み直す。`_initVrcMicMuteSync` 参照)。タイミング変更自体は
        無罪と確認できたため、改めてここに移動した。

        `init()` 本体から切り出したのは、この2行だけを (残り400行超の
        ネットワーク確認・重みダウンロード等を実行せずに) 単体テストで
        検証できるようにするため。

        順序が重要: `model.init()` は
        `model.mic_mute_status_change_callback` を `None` にリセットする
        ため、先に `model.init()` を終わらせてからコールバックを登録しないと
        登録した値が消えてしまう。
        """
        try:
            self._model.init()
        except Exception:
            # In test or headless environments initialization may fail; log and continue.
            errorLogging()
        try:
            # OSC ミュート同期 (Model.changeHandlerMute, 任意の OSC 受信
            # スレッドで走る) が pause()/resume() を mic_lifecycle_lock 配下
            # で実行できるよう、ロック付きラッパーを Model 側のコールバック
            # スロットへ登録する。
            self._model.setMicMuteStatusChangeCallback(self._changeMicTranscriptStatusLocked)
        except Exception:
            errorLogging()
        try:
            self._model.setOverlayFailureCallback(self._onOverlayFailure)
            self._model.setOverlayPositionChangedCallback(self._onOverlayPositionChanged)
            self._model.setOverlayPointerCallback(self._onVrPanelPointer)
            self._model.setOverlayPanelOutOfViewCallback(self._onVrPanelLogOutOfView)
            self._model.setOverlayLauncherIntroCallback(self._onVrPanelLauncherIntro)
            self._model.setOverlayLayoutCallback(self._onVrPanelLayout)
        except Exception:
            errorLogging()

    def _onOverlayFailure(self, reason):
        """Report asynchronous owner/capture failure through the existing error route."""
        if reason == "runtime":
            config.OVERLAY_SMALL_LOG = False
            config.OVERLAY_LARGE_LOG = False
        config.OVERLAY_VR_PANEL = False
        self._model.setVrPanelEnabled(False)
        if not (config.OVERLAY_SMALL_LOG or config.OVERLAY_LARGE_LOG or config.OVERLAY_VR_PANEL):
            self._model.shutdownOverlay()
        response = VRCTError.create_error_response(ErrorCode.OVERLAY_RUNTIME_FAILED,
                                                  data={"reason": reason})
        self.run(response["status"], self.run_mapping.get("message_output_error", "/run/message_output_error"),
                 response["result"])

    @staticmethod
    def setVrPanelWindows(data, *args, **kwargs) -> dict:
        """VR UI (VR画面) が決めたウィンドウの開閉をオーバーレイに反映する。

        data: {"log": bool, "popup": bool}。送り手はVR画面だけなので、bool 以外は False として扱う。
        """
        data = data if isinstance(data, dict) else {}
        windows = {"log": data.get("log") is True, "popup": data.get("popup") is True}
        model.setVrPanelWindows(windows["log"], windows["popup"])
        return {"status": 200, "result": windows}

    @staticmethod
    def recallVrPanelLog(*args, **kwargs) -> dict:
        """VR UIのログウィンドウを目の前へ呼び戻す (見失ったとき、ランチャーのボタンから)。"""
        model.recallVrPanelLog()
        return {"status": 200, "result": True}

    def resetVrLauncher(self, *args, **kwargs) -> dict:
        """VR UIのランチャーの位置・向き・大きさ・手を初期 (左手) に戻す。見失って戻せなくなったときの手段 (PC側の設定から)。"""
        with _VR_WINDOW_SETTINGS_LOCK:
            config.OVERLAY_VR_LAUNCHER_SETTINGS = dict(DEFAULT_OVERLAY_VR_LAUNCHER_SETTINGS)
        model.resetVrLauncher()  # VR につながっていれば、手首へ吸い寄せて戻る
        self.run(200, self.run_mapping["overlay_vr_launcher_hand"], config.OVERLAY_VR_LAUNCHER_SETTINGS["tracker"])
        return {"status": 200, "result": True}

    @staticmethod
    def getOverlayVrPanelAnchor(*args, **kwargs) -> dict:
        return {"status": 200, "result": config.OVERLAY_VR_PANEL_SETTINGS["tracker"]}

    @staticmethod
    def setOverlayVrPanelAnchor(data, *args, **kwargs) -> dict:
        """VR UIのログウィンドウの固定先 (Playspace / LeftHand / RightHand / HMD) を切り替える。

        見えている位置を保ったまま付け替えるので、オーバーレイのスレッドで行う。
        確定した値は _onOverlayPositionChanged が /run/overlay_vr_panel_anchor で知らせる。
        """
        if data not in PANEL_ANCHORS:
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.OVERLAY_VR_PANEL_SETTINGS["tracker"],
            )
        model.requestVrPanelAnchor(data)
        return {"status": 200, "result": data}

    @staticmethod
    def getOverlayVrLauncherHand(*args, **kwargs) -> dict:
        return {"status": 200, "result": config.OVERLAY_VR_LAUNCHER_SETTINGS["tracker"]}

    @staticmethod
    def setOverlayVrLauncherHand(data, *args, **kwargs) -> dict:
        """VR UIのランチャーを付ける手 (LeftHand / RightHand)。手首に対する位置を左右反転して引き継ぐ。"""
        if data not in ("LeftHand", "RightHand"):
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.OVERLAY_VR_LAUNCHER_SETTINGS["tracker"],
            )
        with _VR_WINDOW_SETTINGS_LOCK:
            current = config.OVERLAY_VR_LAUNCHER_SETTINGS
            changed = current["tracker"] != data
            if changed:
                # 反転した位置に、指定された手を明示する (今の固定先が手以外の不正な値でも取り違えないように)
                config.OVERLAY_VR_LAUNCHER_SETTINGS = {**current, **mirrorHandPosition(current), "tracker": data}
        if changed:
            model.updateVrLauncherPosition()
        return {"status": 200, "result": config.OVERLAY_VR_LAUNCHER_SETTINGS["tracker"]}

    @staticmethod
    def setEnableOverlayVrLauncherAutoHide(*args, **kwargs) -> dict:
        config.OVERLAY_VR_LAUNCHER_AUTO_HIDE = True
        model.setVrLauncherAutoHide(True)
        return {"status": 200, "result": config.OVERLAY_VR_LAUNCHER_AUTO_HIDE}

    @staticmethod
    def setDisableOverlayVrLauncherAutoHide(*args, **kwargs) -> dict:
        config.OVERLAY_VR_LAUNCHER_AUTO_HIDE = False
        model.setVrLauncherAutoHide(False)
        return {"status": 200, "result": config.OVERLAY_VR_LAUNCHER_AUTO_HIDE}

    @staticmethod
    def setEnableOverlayVrTooltip(*args, **kwargs) -> dict:
        # 吹き出しを出すかどうかは VR画面 (UI) が決める。ここは保存だけ
        config.OVERLAY_VR_TOOLTIP = True
        return {"status": 200, "result": config.OVERLAY_VR_TOOLTIP}

    @staticmethod
    def setDisableOverlayVrTooltip(*args, **kwargs) -> dict:
        config.OVERLAY_VR_TOOLTIP = False
        return {"status": 200, "result": config.OVERLAY_VR_TOOLTIP}

    @staticmethod
    def setOverlayVrPanelFontSize(data, *args, **kwargs) -> dict:
        """VR UIのログの文字の大きさ (14〜28px)。表示は VR画面だけで決まり、オーバーレイは関わらない。"""
        if isinstance(data, bool) or not isinstance(data, int) or not 14 <= data <= 28:
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.OVERLAY_VR_PANEL_FONT_SIZE,
            )
        config.OVERLAY_VR_PANEL_FONT_SIZE = data
        return {"status": 200, "result": config.OVERLAY_VR_PANEL_FONT_SIZE}

    @staticmethod
    def getOverlayVrPanelOpacity(*args, **kwargs) -> dict:
        return {"status": 200, "result": config.OVERLAY_VR_PANEL_SETTINGS["opacity"]}

    @staticmethod
    def setOverlayVrPanelOpacity(data, *args, **kwargs) -> dict:
        """VR UIのログウィンドウの不透明度 (0.2〜1.0)。

        0 に近いと見えなくなり、VR内で見つけて戻す手段がなくなるので下限を設ける。
        """
        try:
            opacity = float(data)
            if not 0.2 <= opacity <= 1.0:
                raise ValueError()
        except (TypeError, ValueError):
            return VRCTError.create_error_response(
                ErrorCode.VALIDATION_CONFIG_VALUE_INVALID,
                data=config.OVERLAY_VR_PANEL_SETTINGS["opacity"],
            )
        with _VR_WINDOW_SETTINGS_LOCK:
            config.OVERLAY_VR_PANEL_SETTINGS = {**config.OVERLAY_VR_PANEL_SETTINGS, "opacity": round(opacity, 2)}
        model.updateOverlayVrPanelOpacity()
        return {"status": 200, "result": config.OVERLAY_VR_PANEL_SETTINGS["opacity"]}

    def _onVrPanelPointer(self, xy) -> None:
        """VR UI上のポインタの位置をUIへ送る (オーバーレイスレッドから呼ばれる)。外れたら None。"""
        self.run(200, self.run_mapping["vr_panel_pointer"], None if xy is None else {"x": xy[0], "y": xy[1]})

    @staticmethod
    def getVrPanelLayout(*args, **kwargs) -> dict:
        """VR画面の並び (ログの大きさで変わる)。VR画面 (React) はこれに従って各ウィンドウを描く。"""
        s = config.OVERLAY_VR_PANEL_SETTINGS
        overlay = getattr(model, "overlay", None)
        layout = overlay.getVrLayout() if overlay is not None else {**computeVrLayout(*clampPanelSize(s["width"], s["height"])), "tooltip_epoch": 0}
        return {"status": 200, "result": vrLayoutToJson(layout)}

    @staticmethod
    def setVrPanelTooltip(data, *args, **kwargs) -> dict:
        """Queue the tooltip rendering generation from the VR view."""
        try:
            payload = validate_tooltip(data)
        except ValueError:
            return VRCTError.create_error_response(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=None)
        model.setVrPanelTooltip(payload)
        return {"status": 200, "result": data}

    @staticmethod
    def setVrPanelLayoutRendered(data, *args, **kwargs) -> dict:
        """VR画面が新しい並びで描き終えた (その並びのログの [幅, 高さ])。送り手は VR画面だけ。"""
        if not (isinstance(data, list) and len(data) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in data)):
            return VRCTError.create_error_response(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID, data=None)
        model.setVrPanelLayoutRendered(data)
        return {"status": 200, "result": data}

    def _onVrPanelLayout(self, layout: dict) -> None:
        """VR画面の並びが変わったことを UI へ送る (オーバーレイスレッドから呼ばれる)。"""
        self.run(200, self.run_mapping["vr_panel_layout"], vrLayoutToJson(layout))

    def _onVrPanelLogOutOfView(self, out_of_view: bool) -> None:
        """ログウィンドウが視線から外れた・戻ったことをUIへ送る (オーバーレイスレッドから呼ばれる)。"""
        self.run(200, self.run_mapping["vr_panel_log_out_of_view"], out_of_view)

    def _onVrPanelLauncherIntro(self, state: str) -> None:
        """ランチャーの起動演出の状態 (idle/pending/playing) をUIへ送る (オーバーレイスレッドから呼ばれる)。"""
        self.run(200, self.run_mapping["vr_panel_launcher_intro"], state)

    def _onOverlayPositionChanged(self, size: str, position: dict) -> None:
        """VR内の掴み移動・拡大縮小で確定した位置と大きさを保存し、UIへ通知する (オーバーレイスレッドから呼ばれる)。

        position["ui_scaling"] は保存する設定値。small と large ではオーバーレイの幅(m) に対応し、
        small は幅=設定値、large は幅=設定値*0.25 (Model.init参照)。ランチャーは旧来の帯の幅で
        保存するので実際の幅とは異なる (regionWidthM参照)。設定画面のスライダーの範囲 (src-ui/logics/ui_configs.js の
        ui_scaling: 40〜200%) に収めてから保存し、収めた値をオーバーレイにも戻す。
        """
        def clamp(value: float) -> float:
            return round(min(max(value, 0.4), 2.0), 2)

        if size == "small":
            position["ui_scaling"] = clamp(position["ui_scaling"])
            config.OVERLAY_SMALL_LOG_SETTINGS = {**config.OVERLAY_SMALL_LOG_SETTINGS, **position}
            self._model.updateOverlaySmallLogSettings()
            self.run(200, self.run_mapping["overlay_small_log_settings"], config.OVERLAY_SMALL_LOG_SETTINGS)
        elif size == "large":
            position["ui_scaling"] = clamp(position["ui_scaling"] / 0.25)
            config.OVERLAY_LARGE_LOG_SETTINGS = {**config.OVERLAY_LARGE_LOG_SETTINGS, **position}
            self._model.updateOverlayLargeLogSettings()
            self.run(200, self.run_mapping["overlay_large_log_settings"], config.OVERLAY_LARGE_LOG_SETTINGS)
        elif size == "panel":
            with _VR_WINDOW_SETTINGS_LOCK:
                config.OVERLAY_VR_PANEL_SETTINGS = {**config.OVERLAY_VR_PANEL_SETTINGS, **position}
            # 固定先は操作バーでも、呼び戻し (空間固定になる) でも変わるので毎回知らせる
            self.run(200, self.run_mapping["overlay_vr_panel_anchor"], position["tracker"])
        elif size == "launcher":
            with _VR_WINDOW_SETTINGS_LOCK:
                config.OVERLAY_VR_LAUNCHER_SETTINGS = {**config.OVERLAY_VR_LAUNCHER_SETTINGS, **position}
            # 初期に戻したときなど、付ける手が変わることがあるので UI へ知らせる
            self.run(200, self.run_mapping["overlay_vr_launcher_hand"], position["tracker"])

    def init(self, *args, **kwargs) -> None:
        removeLog()
        printLog("Start Initialization")
        init_started = time.monotonic()

        self._bootstrapModel()

        # watchdog を初期化処理の先頭で起動する。以前は init() の最終行に
        # あったため、モデル重みのダウンロードや外部 API 呼び出しが
        # (バグ等で) 無期限にハングした場合、watchdog 自体がまだ起動して
        # おらず自動復旧が一切効かなかった。フロントエンドは Python
        # プロセスを spawn した直後から 20s 間隔で /run/feed_watchdog を
        # 送り続けており (StartPythonController.jsx)、このエンドポイントは
        # 初期化中でも処理可能 (mainloop.py の "status": True) なため、
        # init() をメインスレッドで実行している間も 3 本のハンドラワーカー
        # がフィードを処理できる。よってここで起動しても安全。
        self.startWatchdog()

        # Unknown until an actual consented download/probe has an outcome.
        connected_network = None
        self.run(200, self.run_mapping["connected_network"], None)

        self.initializationProgress(1)

        # Download weights
        # 事前チェックの結果（Noneは「未実施」、True/Falseは「ロード検証済み」）。
        # ダウンロードが発生しなかった場合はこの結果をそのまま使い、後続の
        # availabilityチェックで同じ重みを二重にロードして検証するのを避ける。
        ctranslate2_pre_available: Optional[bool] = None
        whisper_pre_available: Optional[bool] = None
        ctranslate2_request = None
        whisper_request = None
        # Migration is local and preserves conflicts, including offline startup.
        model.backwardCompatibleTranslatorCTranslate2ModelRenameWeightsDir()
        if config.AUTO_DOWNLOAD_MODELS is True:
            ctranslate2_pre_available = model.checkTranslatorCTranslate2ModelWeight(config.CTRANSLATE2_WEIGHT_TYPE)
            whisper_pre_available = model.checkTranscriptionWhisperModelWeight(config.WHISPER_WEIGHT_TYPE)
            if ctranslate2_pre_available is False:
                ctranslate2_request = self._startupLegacyDownloadRequest("ctranslate2", config.CTRANSLATE2_WEIGHT_TYPE)
            if whisper_pre_available is False:
                whisper_request = self._startupLegacyDownloadRequest("whisper", config.WHISPER_WEIGHT_TYPE)
            if ctranslate2_request is not None or whisper_request is not None:
                connected_network = isConnectedNetwork()
                self.run(200, self.run_mapping["connected_network"], connected_network)
            if connected_network is True:
                if ctranslate2_request is not None:
                    self.downloadCtranslate2Weight(ctranslate2_request, False)
                    ctranslate2_pre_available = None
                if whisper_request is not None:
                    self.downloadWhisperWeight(whisper_request, False)
                    whisper_pre_available = None

        # Check and disable/enable AI models (parallel)
        # 上の事前チェックで「ロード検証済みかつダウンロード不要」と分かっている場合は
        # 同じ重みファイルをもう一度ロードして検証するのを避け、その結果を再利用する。

        def check_ctranslate2() -> bool:
            if ctranslate2_pre_available is True:
                return True
            return model.checkTranslatorCTranslate2ModelWeight(config.CTRANSLATE2_WEIGHT_TYPE) is True

        def check_whisper() -> bool:
            if whisper_pre_available is True:
                return True
            return model.checkTranscriptionWhisperModelWeight(config.WHISPER_WEIGHT_TYPE) is True

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_ctranslate2 = executor.submit(check_ctranslate2)
            future_whisper = executor.submit(check_whisper)
            ctranslate2_available = future_ctranslate2.result()
            whisper_available = future_whisper.result()

        # 同意済みで、前回のworkerを停止・joinできた重みだけ1回再試行する。
        # 取消がまだ完了していなければ重ねて取得せず、取得済みとは扱わない。
        if (connected_network is True and config.AUTO_DOWNLOAD_MODELS is True
                and (not ctranslate2_available or not whisper_available)):
            if (not ctranslate2_available and ctranslate2_request is not None
                    and self._legacyDownloads().stop(("ctranslate2", config.CTRANSLATE2_WEIGHT_TYPE))):
                printLog("CTranslate2 weight unavailable after first download; retrying once")
                self.downloadCtranslate2Weight(ctranslate2_request, False)
            if (not whisper_available and whisper_request is not None
                    and self._legacyDownloads().stop(("whisper", config.WHISPER_WEIGHT_TYPE))):
                printLog("Whisper weight unavailable after first download; retrying once")
                self.downloadWhisperWeight(whisper_request, False)

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_ctranslate2 = executor.submit(
                    lambda: ctranslate2_available or model.checkTranslatorCTranslate2ModelWeight(config.CTRANSLATE2_WEIGHT_TYPE) is True
                )
                future_whisper = executor.submit(
                    lambda: whisper_available or model.checkTranscriptionWhisperModelWeight(config.WHISPER_WEIGHT_TYPE) is True
                )
                ctranslate2_available = future_ctranslate2.result()
                whisper_available = future_whisper.result()

        # インスタンス変数にキャッシュ（後続の処理で再利用）
        self._ctranslate2_available_cache = ctranslate2_available
        self._whisper_available_cache = whisper_available

        if self._missingBuiltInModelInUse(ctranslate2_available, whisper_available):
            self.disableAiModels()
        else:
            self.enableAiModels()

        # Init Translation Engine Status (with parallel processing)
        printLog("Init Translation Engine Status")
        translation_phase_started = time.monotonic()
        # エンジンごとの確認にかかった時間 (秒)。起動が遅いとき、どのエンジンが待たせているかを見る。
        engine_check_elapsed: dict = {}

        def check_translation_engine(engine: str) -> tuple:
            """翻訳エンジンのステータスをチェック（並列実行用）"""
            status = False
            auth_key_invalid = False
            model_list = None
            selected_model = None
            check_started = time.monotonic()

            try:
                match engine:
                    case "CTranslate2":
                        # 既に前のステップでチェック済み、結果を再利用
                        status = ctranslate2_available
                    case "DeepL_API":
                        if config.AUTH_KEYS[engine] is None:
                            status = False
                        else:
                            if model.authenticationTranslatorDeepLAuthKey(auth_key=config.AUTH_KEYS[engine]) is True:
                                status = True
                            else:
                                auth_key_invalid = True
                    case "Plamo_API":
                        if config.AUTH_KEYS[engine] is None:
                            status = False
                        else:
                            if model.authenticationTranslatorPlamoAuthKey(auth_key=config.AUTH_KEYS[engine]) is True:
                                model_list = model.getTranslatorPlamoModelList()
                                selected_model = config.SELECTED_PLAMO_MODEL if config.SELECTED_PLAMO_MODEL in model_list else model_list[0]
                                status = True
                            else:
                                auth_key_invalid = True
                    case "Gemini_API":
                        if config.AUTH_KEYS[engine] is None:
                            status = False
                        else:
                            if model.authenticationTranslatorGeminiAuthKey(auth_key=config.AUTH_KEYS[engine]) is True:
                                model_list = model.getTranslatorGeminiModelList()
                                selected_model = config.SELECTED_GEMINI_MODEL if config.SELECTED_GEMINI_MODEL in model_list else model_list[0]
                                status = True
                            else:
                                auth_key_invalid = True
                    case "OpenAI_API":
                        if config.AUTH_KEYS[engine] is None:
                            status = False
                        else:
                            if model.authenticationTranslatorOpenAIAuthKey(auth_key=config.AUTH_KEYS[engine]) is True:
                                model_list = model.getTranslatorOpenAIModelList()
                                selected_model = config.SELECTED_OPENAI_MODEL if config.SELECTED_OPENAI_MODEL in model_list else model_list[0]
                                status = True
                            else:
                                auth_key_invalid = True
                    case "Groq_API":
                        if config.AUTH_KEYS[engine] is None:
                            status = False
                        else:
                            if model.authenticationTranslatorGroqAuthKey(auth_key=config.AUTH_KEYS[engine]) is True:
                                model_list = model.getTranslatorGroqModelList()
                                selected_model = config.SELECTED_GROQ_MODEL if config.SELECTED_GROQ_MODEL in model_list else model_list[0]
                                status = True
                            else:
                                auth_key_invalid = True
                    case "OpenRouter_API":
                        if config.AUTH_KEYS[engine] is None:
                            status = False
                        else:
                            if model.authenticationTranslatorOpenRouterAuthKey(auth_key=config.AUTH_KEYS[engine]) is True:
                                model_list = model.getTranslatorOpenRouterModelList()
                                selected_model = config.SELECTED_OPENROUTER_MODEL if config.SELECTED_OPENROUTER_MODEL in model_list else model_list[0]
                                status = True
                            else:
                                auth_key_invalid = True
                    case "LMStudio":
                        if config.LMSTUDIO_URL:
                            if model.authenticationTranslatorLMStudio(base_url=config.LMSTUDIO_URL) is True:
                                model_list = model.getTranslatorLMStudioModelList()
                                if len(model_list) > 0:
                                    selected_model = config.SELECTED_LMSTUDIO_MODEL if config.SELECTED_LMSTUDIO_MODEL in model_list else model_list[0]
                                    status = True
                    case "OpenAI_Compatible":
                        auth_key = config.AUTH_KEYS.get("OpenAI_Compatible")
                        if auth_key and config.OPENAI_COMPATIBLE_URL:
                            if model.authenticationTranslatorOpenAICompatibleAuthKey(
                                auth_key=auth_key,
                                base_url=config.OPENAI_COMPATIBLE_URL,
                            ) is True:
                                model_list = model.getTranslatorOpenAICompatibleModelList()
                                if len(model_list) > 0:
                                    selected_model = config.SELECTED_OPENAI_COMPATIBLE_MODEL if config.SELECTED_OPENAI_COMPATIBLE_MODEL in model_list else model_list[0]
                                    status = True
                            else:
                                auth_key_invalid = True
                    case "Ollama":
                        if model.authenticationTranslatorOllama() is True:
                            model_list = model.getTranslatorOllamaModelList()
                            if len(model_list) > 0:
                                selected_model = config.SELECTED_OLLAMA_MODEL if config.SELECTED_OLLAMA_MODEL in model_list else model_list[0]
                                status = True
                    case _:
                        status = True  # Availability is established by real requests, not a global probe.
            except Exception:
                errorLogging(provider=engine)
                status = False

            if status and model_list is not None and engine in _ENGINE_MODEL_CLIENT_CALLS:
                # 選んだモデルの設定とクライアントの生成 (ChatOpenAI は接続先ごとに HTTP クライアントと
                # SSL 証明書を作り、約0.4秒かかる)。結果を順に反映するループ (直列) に置くと、エンジンの数だけ
                # 待ちが積み上がる。ここなら、ほかのエンジンのネットワーク待ちと重なる。クライアントは
                # エンジンごとに独立している。config への書き込みは、反映するループに残す
                set_model, update_client = _ENGINE_MODEL_CLIENT_CALLS[engine]
                try:
                    getattr(model, set_model)(selected_model)
                    getattr(model, update_client)()
                except Exception:
                    errorLogging(provider=engine)
                    status = False

            engine_check_elapsed[engine] = time.monotonic() - check_started
            return engine, status, auth_key_invalid, model_list, selected_model

        engine_results = {}
        engines_to_check = list(config.SELECTABLE_TRANSLATION_ENGINE_LIST)

        # 確認は主にネットワーク待ち (認証・モデル一覧の取得)。エンジンの数 (13) より少ない並列数では、
        # 先に遅いエンジンが枠を埋めて、後ろのエンジンが待たされる (実機で、最大の確認が 1.53 秒なのに
        # 全体が 2.3 秒かかった)。エンジンごとに独立したクライアントなので、全部を同時に確認する。
        engine_results = _runEngineChecks(check_translation_engine, engines_to_check, "Translation engine")

        # 結果を順番に適用（メインスレッドで実行）
        for engine in engines_to_check:
            if engine not in engine_results:
                # 時間内に確認できなかった
                config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] = False
                continue

            status, auth_key_invalid, model_list, selected_model = engine_results[engine]
            apply_started = time.monotonic()

            # ログ出力
            printLog(f"Start check {engine}")

            # ステータス設定
            config.SELECTABLE_TRANSLATION_ENGINE_STATUS[engine] = status

            # 確認に失敗してもキーは消さない。認証の関数は、オフライン、タイムアウト、429、5xx でも
            # False を返すので、キーが拒否されたのか一時的に届かなかったのかを区別できない。消すと、
            # ネットワークのない起動のたびに保存したキーを失う。エンジンを使えない状態にするだけにする
            if auth_key_invalid:
                printLog(f"{engine} auth key could not be verified; keeping it")
            elif status:
                printLog(f"{engine} is valid/available")

            if engine == "LMStudio" and not status:
                config.SELECTABLE_LMSTUDIO_MODEL_LIST = []
                config.SELECTED_LMSTUDIO_MODEL = None
            if engine == "OpenAI_Compatible" and not status:
                config.SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST = []
                config.SELECTED_OPENAI_COMPATIBLE_MODEL = None
            if engine == "Ollama" and not status:
                config.SELECTABLE_OLLAMA_MODEL_LIST = []
                config.SELECTED_OLLAMA_MODEL = None

            # モデルリストと選択モデルの設定
            if model_list is not None and status:
                match engine:
                    case "Plamo_API":
                        config.SELECTABLE_PLAMO_MODEL_LIST = model_list
                        config.SELECTED_PLAMO_MODEL = selected_model
                    case "Gemini_API":
                        config.SELECTABLE_GEMINI_MODEL_LIST = model_list
                        config.SELECTED_GEMINI_MODEL = selected_model
                    case "OpenAI_API":
                        config.SELECTABLE_OPENAI_MODEL_LIST = model_list
                        config.SELECTED_OPENAI_MODEL = selected_model
                    case "Groq_API":
                        config.SELECTABLE_GROQ_MODEL_LIST = model_list
                        config.SELECTED_GROQ_MODEL = selected_model
                    case "OpenRouter_API":
                        config.SELECTABLE_OPENROUTER_MODEL_LIST = model_list
                        config.SELECTED_OPENROUTER_MODEL = selected_model
                    case "LMStudio":
                        config.SELECTABLE_LMSTUDIO_MODEL_LIST = model_list
                        config.SELECTED_LMSTUDIO_MODEL = selected_model
                    case "OpenAI_Compatible":
                        config.SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST = model_list
                        config.SELECTED_OPENAI_COMPATIBLE_MODEL = selected_model
                    case "Ollama":
                        config.SELECTABLE_OLLAMA_MODEL_LIST = model_list
                        config.SELECTED_OLLAMA_MODEL = selected_model

            printLog(
                f"{engine} check completed "
                f"(check {engine_check_elapsed.get(engine, 0.0):.2f}s, apply {time.monotonic() - apply_started:.2f}s)"
            )

        printLog(f"Translation Engine Status Init completed ({time.monotonic() - translation_phase_started:.2f}s)")

        # Init Transcription Engine Status
        printLog("Init Transcription Engine Status")
        transcription_phase_started = time.monotonic()
        transcription_check_elapsed: dict = {}

        # Deepgram のモデル名 -> 対応言語一覧。check_transcription_engine() は
        # 全エンジン共通の戻り値シェイプ (model_list は list[str]) を持つため、
        # Deepgram だけが持つ追加メタデータ (言語一覧) はここに直接書き込む
        # (Deepgram のケースはスレッドプール中で高々1回しか実行されないため
        # 競合の心配はない)。
        deepgram_model_languages: dict = {}

        def check_transcription_engine(engine: str) -> tuple:
            """文字起こしエンジンのステータスをチェック（並列実行用）。

            Groq/OpenAI/カスタムサーバーは翻訳側の OpenAI互換エンジンと同じ
            「認証キーでモデル一覧が取得できるか」で可用性を判定する。
            実際に文字起こしを1回試すより軽量で、起動時の検証に向く。
            """
            status = False
            auth_key_invalid = False
            model_list = None
            selected_model = None
            check_started = time.monotonic()

            try:
                match engine:
                    case "Whisper":
                        # キャッシュされた結果を使用（重複チェックを回避）
                        status = self._whisper_available_cache
                    case "Groq_Whisper":
                        api_key = config.TRANSCRIPTION_AUTH_KEYS.get(engine)
                        if not api_key:
                            status = False
                        else:
                            base_url = config.GROQ_WHISPER_BASE_URL
                            if model.authenticationTranscriptionApiKey(api_key=api_key, base_url=base_url) is True:
                                model_list = model.getTranscriptionApiModelList(
                                    api_key=api_key, base_url=base_url, keyword_filter=TRANSCRIPTION_MODEL_KEYWORDS,
                                )
                                if len(model_list) > 0:
                                    selected_model = config.SELECTED_GROQ_WHISPER_MODEL if config.SELECTED_GROQ_WHISPER_MODEL in model_list else model_list[0]
                                    status = True
                            else:
                                auth_key_invalid = True
                    case "OpenAI_Whisper":
                        api_key = config.TRANSCRIPTION_AUTH_KEYS.get(engine)
                        if not api_key:
                            status = False
                        else:
                            base_url = config.OPENAI_WHISPER_BASE_URL
                            if model.authenticationTranscriptionApiKey(api_key=api_key, base_url=base_url) is True:
                                model_list = model.getTranscriptionApiModelList(
                                    api_key=api_key, base_url=base_url, keyword_filter=TRANSCRIPTION_MODEL_KEYWORDS,
                                )
                                if len(model_list) > 0:
                                    selected_model = config.SELECTED_OPENAI_WHISPER_MODEL if config.SELECTED_OPENAI_WHISPER_MODEL in model_list else model_list[0]
                                    status = True
                            else:
                                auth_key_invalid = True
                    case "Custom_Whisper":
                        api_key = config.TRANSCRIPTION_AUTH_KEYS.get(engine)
                        base_url = config.TRANSCRIPTION_CUSTOM_URL
                        if not api_key or not base_url:
                            status = False
                        else:
                            if model.authenticationTranscriptionApiKey(api_key=api_key, base_url=base_url) is True:
                                # カスタムサーバーはどんなモデル名を使っているか分からないため絞り込まない
                                model_list = model.getTranscriptionApiModelList(api_key=api_key, base_url=base_url)
                                if len(model_list) > 0:
                                    selected_model = config.SELECTED_CUSTOM_WHISPER_MODEL if config.SELECTED_CUSTOM_WHISPER_MODEL in model_list else model_list[0]
                                    status = True
                            else:
                                auth_key_invalid = True
                    case "Deepgram":
                        api_key = config.TRANSCRIPTION_AUTH_KEYS.get(engine)
                        if not api_key:
                            status = False
                        else:
                            if model.authenticationDeepgramApiKey(api_key=api_key) is True:
                                models_detailed = model.getDeepgramModelListDetailed(api_key=api_key)
                                model_list = [m["name"] for m in models_detailed]
                                deepgram_model_languages.update({m["name"]: m["languages"] for m in models_detailed})
                                if len(model_list) > 0:
                                    selected_model = config.SELECTED_DEEPGRAM_MODEL if config.SELECTED_DEEPGRAM_MODEL in model_list else model_list[0]
                                    status = True
                            else:
                                auth_key_invalid = True
                    case _:
                        # Google 等、ネットワーク接続のみが条件のエンジン
                        status = True  # Availability is established by real requests, not a global probe.
            except Exception:
                errorLogging(provider=engine)
                status = False

            transcription_check_elapsed[engine] = time.monotonic() - check_started
            return engine, status, auth_key_invalid, model_list, selected_model

        transcription_engine_results = {}
        transcription_engines_to_check = list(config.SELECTABLE_TRANSCRIPTION_ENGINE_LIST)

        # 翻訳エンジンの確認と同じ理由で、エンジンの数だけ同時に確認する
        transcription_engine_results = _runEngineChecks(
            check_transcription_engine, transcription_engines_to_check, "Transcription engine")

        for engine in transcription_engines_to_check:
            if engine not in transcription_engine_results:
                # 時間内に確認できなかった
                config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = False
                continue

            status, auth_key_invalid, model_list, selected_model = transcription_engine_results[engine]

            config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS[engine] = status

            # 翻訳と同じく、確認に失敗してもキーは消さない
            if auth_key_invalid:
                printLog(f"{engine} transcription auth key could not be verified; keeping it")
            elif status:
                printLog(
                    f"{engine} transcription engine is valid/available "
                    f"(check {transcription_check_elapsed.get(engine, 0.0):.2f}s)"
                )

            if engine == "Groq_Whisper" and not status:
                config.SELECTABLE_GROQ_WHISPER_MODEL_LIST = []
                config.SELECTED_GROQ_WHISPER_MODEL = None
            if engine == "OpenAI_Whisper" and not status:
                config.SELECTABLE_OPENAI_WHISPER_MODEL_LIST = []
                config.SELECTED_OPENAI_WHISPER_MODEL = None
            if engine == "Custom_Whisper" and not status:
                config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST = []
                config.SELECTED_CUSTOM_WHISPER_MODEL = None
            if engine == "Deepgram" and not status:
                config.SELECTABLE_DEEPGRAM_MODEL_LIST = []
                config.DEEPGRAM_MODEL_LANGUAGES = {}
                config.SELECTED_DEEPGRAM_MODEL = None

            if model_list is not None and status:
                match engine:
                    case "Groq_Whisper":
                        config.SELECTABLE_GROQ_WHISPER_MODEL_LIST = model_list
                        config.SELECTED_GROQ_WHISPER_MODEL = selected_model
                    case "OpenAI_Whisper":
                        config.SELECTABLE_OPENAI_WHISPER_MODEL_LIST = model_list
                        config.SELECTED_OPENAI_WHISPER_MODEL = selected_model
                    case "Deepgram":
                        config.SELECTABLE_DEEPGRAM_MODEL_LIST = model_list
                        config.DEEPGRAM_MODEL_LANGUAGES = deepgram_model_languages
                        config.SELECTED_DEEPGRAM_MODEL = selected_model
                    case "Custom_Whisper":
                        config.SELECTABLE_CUSTOM_WHISPER_MODEL_LIST = model_list
                        config.SELECTED_CUSTOM_WHISPER_MODEL = selected_model

        printLog(f"Transcription Engine Status Init completed ({time.monotonic() - transcription_phase_started:.2f}s)")
        self.initializationProgress(2)

        # Set Translation Engine
        printLog("Set Translation Engine")
        self.updateDownloadedCTranslate2ModelWeight()
        self.updateTranslationEngineAndEngineList()

        # Set Transcription Engine
        printLog("Set Transcription Engine")
        self.updateDownloadedWhisperModelWeight()
        self.updateTranscriptionEngine()

        # Set Transliteration
        printLog("Set Transliteration")
        if config.CONVERT_MESSAGE_TO_ROMAJI is True or config.CONVERT_MESSAGE_TO_HIRAGANA is True:
            model.startTransliteration()

        self.initializationProgress(3)

        # Set Word Filter
        printLog("Set Word Filter")
        model.addKeywords()

        # Check Software Updated (Background)
        printLog("Check Software Updated (Background)")

        def check_software_updated_background():
            """ソフトウェア更新チェックをバックグラウンドで実行"""
            try:
                self.checkSoftwareUpdated()
                printLog("[Background] Software update check completed")
            except Exception:
                errorLogging()
                printLog("[Background] Software update check failed")

        bg_thread = Thread(target=check_software_updated_background)
        bg_thread.daemon = True
        bg_thread.start()

        # Init Logger
        printLog("Init Logger")
        if config.LOGGER_FEATURE is True:
            model.startLogger()

        self.initializationProgress(4)

        # Init OSC Receive (Background)
        printLog("Init OSC Receive (Background)")

        bg_thread = Thread(target=self._initOscReceive)
        bg_thread.daemon = True
        bg_thread.start()

        # Init Device Manager
        printLog("Init Device Manager")
        device_manager.setCallbackHostList(self.updateMicHostList)
        device_manager.setCallbackMicDeviceList(self.updateMicDeviceList)
        device_manager.setCallbackSpeakerDeviceList(self.updateSpeakerDeviceList)
        # 一覧更新は Auto Select とは独立させる。Auto Select が両方 OFF でも
        # デバイス再接続を検出して UI の選択肢を更新できるようにする。
        device_manager.setDeviceListMonitoringActive(True)

        printLog("Init Auto Device Selection")
        if config.AUTO_MIC_SELECT is True:
            self.applyAutoMicSelect()
        if config.AUTO_SPEAKER_SELECT is True:
            self.applyAutoSpeakerSelect()

        # Init Overlay
        printLog("Init Overlay")
        self.syncOverlayRunning()

        # Init WebSocket Server
        printLog("Init WebSocket Server")
        # OBS Browser Source depends on WebSocket Server to receive messages.
        if config.OBS_BROWSER_SOURCE is True and config.WEBSOCKET_SERVER is False:
            config.WEBSOCKET_SERVER = True

        if config.WEBSOCKET_SERVER is True:
            if not (
                isAvailableWebSocketServer(config.WEBSOCKET_HOST, config.WEBSOCKET_PORT) is True
                and model.startWebSocketServer(config.WEBSOCKET_HOST, config.WEBSOCKET_PORT)
            ):
                config.WEBSOCKET_SERVER = False
                model.stopWebSocketServer()
                printLog("WebSocket server host or port is not available")

        # Init OBS Browser Source Server
        printLog("Init OBS Browser Source Server")
        obs_startup_error = None
        if config.OBS_BROWSER_SOURCE is True:
            if config.WEBSOCKET_SERVER is not True:
                config.OBS_BROWSER_SOURCE = False
                model.stopObsBrowserSourceServer()
                printLog("OBS Browser Source requires WebSocket Server")
            else:
                try:
                    if isAvailableWebSocketServer(config.WEBSOCKET_HOST, config.OBS_BROWSER_SOURCE_PORT) is not True:
                        obs_startup_error = ErrorCode.OBS_BROWSER_SOURCE_PORT_UNAVAILABLE
                    elif not model.startObsBrowserSourceServer(config.WEBSOCKET_HOST, config.OBS_BROWSER_SOURCE_PORT):
                        obs_startup_error = ErrorCode.OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE
                except Exception:
                    errorLogging()
                    obs_startup_error = ErrorCode.OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE
                if obs_startup_error is not None:
                    config.OBS_BROWSER_SOURCE = False
                    model.stopObsBrowserSourceServer()
                    printLog("OBS Browser Source server could not start")

        # Revalidate Selected Models
        printLog("Revalidate Selected Models")
        config.revalidate_selected_models()

        # telemetry Init
        # Not before the user has answered the notice: a settings file from an older
        # version, or a first start, sends nothing until then.
        printLog("Telemetry Init")
        if Controller._telemetryAllowed():
            model.telemetryInit(enabled=True, app_version=config.VERSION)

        # Update Settings
        printLog("Update settings")
        self.updateConfigSettings()
        if obs_startup_error is not None:
            response = VRCTError.create_error_response(obs_startup_error, data=False)
            self.run(response["status"], "/set/enable/obs_browser_source", response["result"])
        # After initialization_complete so the UI is ready to show it.
        self.notifyNonCommercialCTranslate2Weight()
        for key in getattr(config, "INVALID_SAVED_API_URLS", []):
            endpoint, error_code = {
                "LMSTUDIO_URL": ("/set/data/lmstudio_url", ErrorCode.CONNECTION_LMSTUDIO_URL_INVALID),
                "OPENAI_COMPATIBLE_URL": ("/set/data/openai_compatible_url", ErrorCode.CONNECTION_OPENAI_COMPATIBLE_URL_INVALID),
                "TRANSCRIPTION_CUSTOM_URL": ("/set/data/custom_whisper_url", ErrorCode.CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID),
            }[key]
            response = VRCTError.create_error_response(error_code, data="")
            self.run(response["status"], endpoint, response["result"])
        if getattr(config, "UNREADABLE_CONFIG_BACKUP", None):
            self.run(200, self.run_mapping["config_file_unreadable"], {"backup": config.UNREADABLE_CONFIG_BACKUP})

        # 設定を書き込めなかったら知らせる (書き直せたら、それも知らせる)
        config.setSaveCallbacks(
            lambda reason, path: self.run(200, self.run_mapping["config_save_failed"], {"reason": reason, "path": path}),
            lambda: self.run(200, self.run_mapping["config_save_recovered"], True),
        )

        printLog(f"End Initialization ({time.monotonic() - init_started:.2f}s)")


def _makeSimpleConfigGetter(attr_name: str):
    """`_SIMPLE_CONFIG_GETTERS` の1エントリから、単純なgetterを生成する
    (フェーズ3項目23)。以前はこの形の94個のメソッドが`controller.py`に
    個別の`def`として並んでいた:

        @staticmethod
        def getUiLanguage(*args, **kwargs) -> dict:
            return {"status":200, "result":config.UI_LANGUAGE}

    ロジックが完全に同一な94個の関数定義を、1個のジェネレータ+
    テーブルへ集約する。生成したメソッドは通常の`def`と同じ名前で
    `Controller`クラスへ登録するため (`_registerSimpleConfigGetters()`
    参照)、`mainloop.py`のルーティング (`controller.getUiLanguage`) や
    既存テストからの直接呼び出しは一切変更不要。
    """
    def getter(*args, **kwargs) -> dict:
        return {"status": 200, "result": getattr(config, attr_name)}
    return getter


def _registerSimpleConfigGetters() -> None:
    for method_name, attr_name in _SIMPLE_CONFIG_GETTERS.items():
        getter = _makeSimpleConfigGetter(attr_name)
        getter.__name__ = method_name
        getter.__qualname__ = f"Controller.{method_name}"
        setattr(Controller, method_name, staticmethod(getter))


_registerSimpleConfigGetters()
