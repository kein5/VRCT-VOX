import atexit
import copy
import faulthandler
import hashlib
import json
from subprocess import Popen
from os import makedirs as os_makedirs
from os import path as os_path
from os import getppid as os_getppid
from os import _exit as os_exit
from os import remove as os_remove
from os import stat as os_stat
from psutil import Process as psutil_Process
from datetime import datetime
from time import sleep
from queue import Queue, Empty
from threading import Thread, Lock, RLock, Event, current_thread
from concurrent.futures import ThreadPoolExecutor
from requests import get as requests_get
from typing import Callable, Optional, cast
from packaging.version import parse
from dataclasses import dataclass

from flashtext import KeywordProcessor

from device_manager import device_manager
from audio_device_identity import capture_key, resolve_device
from config import config, DEFAULT_OVERLAY_VR_LAUNCHER_SETTINGS

from models.translation.translation_translator import Translator
from models.message_delivery import ChatboxOrder, DeliveryEpochs
from models.osc.osc import OSCHandler
from models.transcription.transcription_recorder import (
    AudioOpenBusy,
    audioOpenOutstanding,
    SelectedMicEnergyAndAudioRecorder,
    SelectedSpeakerEnergyAndAudioRecorder,
    SelectedMicVadRecorder,
    SelectedSpeakerVadRecorder,
)
from models.transcription.transcription_transcriber import AudioTranscriber
from models.transcription.utterance_diagnostics import utterance_diagnostics
from models.translation.translation_languages import translation_lang
from models.transcription.transcription_languages import transcription_lang
from models.translation.translation_utils import checkCTranslate2Weight, hasCTranslate2WeightFile, downloadCTranslate2Weight, downloadCTranslate2Tokenizer, backwardCompatibleRenameWeightsDir, MissingCTranslate2Tokenizer
from models.transcription.transcription_whisper import checkWhisperWeight, downloadWhisperWeight
from models.transcription.transcription_openai_compatible import checkTranscriptionApiKey, getAvailableTranscriptionModels
from models.transcription.transcription_deepgram import (
    checkDeepgramApiKey,
    getAvailableDeepgramModels,
    getAvailableDeepgramModelsDetailed,
    isLanguageSupportedByDeepgramModel,
)
from models.transliteration.transliteration_transliterator import Transliterator
from models.overlay.overlay import LAUNCHER, PANEL, POPUP, Overlay, launcherNearestInReach, launcherOutOfReach
from models.overlay.overlay_image import OverlayImage
from models.watchdog.watchdog import Watchdog
from models.websocket.websocket_server import WebSocketServer
from models.obs.obs_browser_source_server import ObsBrowserSourceServer
from models.clipboard.clipboard import Clipboard
from models.ocr import OcrPipeline
from models.ocr.ocr_chatbox_detector import buildChatboxDetector
from models.ocr.ocr_languages import isSupported as isSupportedOcrLanguage
from models.ocr.ocr_languages import resolveModelSpec
from models.ocr.ocr_models import resolveModelFiles, OcrModelsMissing
from models.ocr import ocr_engine_rapidocr as ocr_engine
from models.telemetry import Telemetry
from utils import ConversationLogger, errorLogging, printLog, openTraceLog
from errors import AudioPipelineError, AudioPipelineFailure, ERROR_METADATA, ErrorCode, OcrStartError

TRANSCRIPT_STOP_JOIN_TIMEOUT = 15

# GitHub API 呼び出し / setup.exe ダウンロードの (connect, read) タイムアウト。
# 無指定だと「接続はするが応答しない」相手に requests が無期限にブロック
# しうる。checkSoftwareUpdated()/listAvailableReleases() は
# Controller.init() から呼ばれるため、これが起きると初期化そのものが
# 固まる。translation_utils.py/transcription_whisper.py の
# _DOWNLOAD_TIMEOUT と同じ値を使う (大きめの read 側はモデル重みと同様、
# setup.exe のダウンロードにも余裕を持たせるため)。
_HTTP_TIMEOUT = (10, 60)

# フリーズ調査用の恒久計装。mainloop.py の faulthandler.enable() は
# ネイティブフォルト (access violation 等) 発生時にしか全スレッドの
# コールスタックを記録しない。今回問題になっている「クラッシュではなく
# 無応答のまま固まる」ケースはネイティブフォルトを伴わないため、それとは
# 別に dump_traceback_later でタイムアウト検知のスタックダンプを取る。
# feedWatchdog() が呼ばれるたびにタイマーを再武装し (呼び出しは
# フロントエンドから ~WATCHDOG_INTERVAL 秒ごとに来る)、その周期を超えて
# 次の feed が来なければ、その時点の全スレッドスタックを
# freeze_trace.log に書き出す (exit=False なのでプロセスは落とさない)。
# faulthandler は enable/dump_traceback_later 時点で fd を掴むため
# 遅延 open できず、フリーズ無しの通常終了でも 0 バイトのファイルが
# 残る。運用上のゴミ化を避けるため atexit で「書き込みが無ければ削除」する。
_freeze_trace_path, _freeze_trace_file = openTraceLog("freeze_trace.log")
_FREEZE_DUMP_MARGIN_SEC = 15
# watchdog スレッドの join 上限。Watchdog.start() 末尾の
# time.sleep(interval) (既定20秒) は中断できないため、ここを無期限にすると
# shutdown() が最大 interval 秒待たされる。daemon thread なので待ちきれ
# なくても実害はない (stopWatchdog のコメント参照)。
_WATCHDOG_JOIN_TIMEOUT_SEC = 1.0

# WebSocket の起動全体の待ち時間。時間切れ後のキャンセルと join は別枠（最大2秒）。
_WEBSOCKET_START_TIMEOUT = 6.0


def _cleanupFreezeTraceIfEmpty() -> None:
    try:
        _freeze_trace_file.close()
    except Exception:
        pass
    try:
        if os_path.exists(_freeze_trace_path) and os_stat(_freeze_trace_path).st_size == 0:
            os_remove(_freeze_trace_path)
    except Exception:
        pass


atexit.register(_cleanupFreezeTraceIfEmpty)


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    is_prerelease: bool
    published_at: str


class SetupSha256Unavailable(Exception):
    """setup.exe の ".sha256" サイドカーアセットが GitHub Release に存在する
    のに、その中身をリトライしても取得/パースできなかったことを表す。

    ".sha256" アセットがそもそも無い古い Release (この検証より前に公開された
    もの) は「検証対象が無い」だけなのでサイズチェックのみへフォールバック
    してよい。一方こちらは「チェックサムが公開されているのに入手できな
    かった」状態であり、配布物がすり替えられている可能性を排除できない。
    呼び出し側はサイズチェックへ格下げせず、更新自体を中止する。
    """


# updateSoftware()/updateCudaSoftware() の結果。インストーラを起動すれば
# アプリは終了するので、呼び出し側が実際に受け取るのは失敗の2種類。
SETUP_LAUNCHED = "launched"
SETUP_DOWNLOAD_FAILED = "download_failed"
# ハッシュ不一致など。再試行しても直らず、改ざんの疑いがあるので通信エラーと分ける
SETUP_VERIFY_FAILED = "verify_failed"


# audio_queue の有界化 (フェーズ3項目20)。文字起こしが実時間に追いつけ
# ない状況 (例: CPUでWhisper large-v3) で無制限に溜まると、drain時に
# last_sample がまとめて連結されて音声が長くなり、推論がさらに遅くなって
# もっと溜まる、という正のフィードバックループになる
# (transcription_transcriber.py 側の last_sample 長上限とあわせて対応)。
# 1チャンクは最大 record_timeout 秒 (UI 設定上限30秒) なので、理論上の
# 最悪ケースでは 20 チャンク × 30秒 = 最大600秒分の生音声をキュー自体が
# 保持しうる (last_sample 側の安全マージンより大きい)。ただしこれに
# 到達するには単発の推論呼び出しが10分近く返らない必要があり非現実的
# なため、値はそのまま維持する (レビューで指摘・検討済み)。20 は
# 「文字起こしが実時間の何倍も遅れた」状態のみで発動する余裕を持たせた値。
_AUDIO_QUEUE_MAXSIZE = 20

# 2026-09-07: Google (無料/非公式エンドポイント) に限り VadSegmenter の
# max_speech_frames を3秒 (v3.5.0のRECORD_TIMEOUT相当) に短縮する対策を
# 一度試したが、実機検証で「処理が悪化した」(呼び出し頻度が上がり過ぎ、
# 無料/非公式エンドポイント側で暗黙のスロットリング等が起きている
# 可能性がある) と判明したため撤回した。BaseVadAndAudioRecorder /
# SelectedMic・SpeakerVadRecorder の max_speech_seconds 引数自体は
# 汎用の上書き機構として残しているが、model.py からは既定値 (7秒、
# PuriPuly-heart 参考値) を上書きしない。


class _DiscardQueue(Queue):
    """Queue that silently drops everything put into it.

    Energy-meter-only recording uses SelectedMic/SpeakerEnergyAndAudioRecorder,
    whose listener always pushes audio chunks into the audio_queue argument
    even when nobody wants the audio (only the energy_queue is consumed).
    Passing this instead of a real Queue avoids an unbounded memory leak
    from chunks nobody ever drains.
    """

    def put(self, *args, **kwargs) -> None:
        pass


class _AudioQueueEvent(Event):
    """録音エラーを記録し、入力待ちの文字起こしも起こす。"""

    def __init__(self, queue) -> None:
        super().__init__()
        self._queue = queue
        self.on_error = None

    def set(self) -> None:
        with self._queue.not_empty:
            super().set()
            self._queue.not_empty.notify_all()
        if self.on_error is not None:
            self.on_error()


class _AudioQueue(Queue):
    """入力・フレーズ期限・停止・録音エラーまで待つ有界キュー。"""

    def __init__(self) -> None:
        super().__init__(maxsize=_AUDIO_QUEUE_MAXSIZE)
        self._stopped = False
        self.device_error_event = _AudioQueueEvent(self)

    def waitForWork(self, timeout: Optional[float]) -> bool:
        with self.not_empty:
            self.not_empty.wait_for(
                lambda: self._stopped or self._qsize() or self.device_error_event.is_set(),
                timeout=timeout,
            )
            return not self._stopped

    def stop(self) -> None:
        # 終端値は drop-oldest で失われるため、停止状態はキューの外に持つ。
        with self.not_empty:
            self._stopped = True
            self.not_empty.notify_all()


class _EnergyQueue(Queue):
    """最新の未読み取り値を保持し、停止でも待機中の consumer を起こす。"""

    def __init__(self) -> None:
        super().__init__(maxsize=1)
        self._stopped = False

    def getUntilStopped(self) -> Optional[float]:
        with self.not_empty:
            self.not_empty.wait_for(lambda: self._stopped or self._qsize())
            if self._stopped:
                return None
            value = self._get()
            self.not_full.notify()
            return value

    def stop(self) -> None:
        # 終端値をキューへ積むと producer の古い値を捨てる処理と競合するため、
        # 停止状態はキューの外に持ち、同じ条件変数で通知する。
        with self.not_empty:
            self._stopped = True
            self.not_empty.notify_all()


class threadFnc(Thread):
    """A tiny Thread wrapper that repeatedly calls a function.

    Usage: threadFnc(fnc, end_fnc=None, daemon=True, *args, **kwargs)
    The target function will be called repeatedly inside run().
    """
    def __init__(self, fnc, end_fnc=None, daemon: bool = True, *args, **kwargs):
        # Do not pass target to super; manage call explicitly so we can
        # store args/kwargs on the instance for later use.
        super(threadFnc, self).__init__(daemon=daemon)
        self.fnc = fnc
        self.end_fnc = end_fnc
        self.loop = True
        self._args = args
        self._kwargs = kwargs

    def stop(self) -> None:
        self.loop = False

    def run(self) -> None:
        try:
            while self.loop:
                try:
                    self.fnc(*self._args, **self._kwargs)
                except Exception:
                    # Protect the thread from terminating on user exceptions
                    errorLogging()
        finally:
            if callable(self.end_fnc):
                try:
                    self.end_fnc()
                except Exception:
                    errorLogging()
        return


class AudioLifecycleWorker:
    """Serialize each source's device reconciliation away from enumeration.

    Pending work with the same coalesce_key is skipped. Callers carrying an
    intent generation include it in that key, so a newer request cannot be
    swallowed by a pending job that OFF has invalidated. The job checks its
    generation again under the source lifecycle lock before touching capture.
    """

    _STOP_SENTINEL = object()

    def __init__(self) -> None:
        self._queue: "Queue[tuple]" = Queue()
        self._pending_keys: set = set()
        self._lock = Lock()
        self._stopped = False
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, fn: Callable[[], None], coalesce_key: Optional[str] = None) -> bool:
        """fn を専用スレッドで実行するようキューに積む。

        coalesce_key を指定した場合、まだ実行開始していない同じ key の
        項目が既にキューにあれば新規投入をスキップする (クラスの
        docstring 参照。fn は引数を持たず常に現在の状態を読む冪等な
        処理であること)。

        Returns:
            実際にキューへ積んだ場合は True。stop() 済み、または
            coalesce_key が示す重複が既に保留中でスキップした場合は
            False。
        """
        with self._lock:
            if self._stopped:
                return False
            if coalesce_key is not None:
                if coalesce_key in self._pending_keys:
                    return False
                self._pending_keys.add(coalesce_key)
            self._queue.put((coalesce_key, fn))
            return True

    def stop(self, timeout: Optional[float] = None) -> None:
        """新規 enqueue を以後無視し、専用スレッドを止める。

        シャットダウン中に古いデバイス通知やミュート同期の再送が届いて
        リソース解放と競合するのを防ぐために呼ぶ。enqueue() と同じ
        ロックの下でフラグを立てて sentinel を積むため、「enqueue() が
        stop() 済みでないことを確認した直後に stop() が完了してしまい、
        その後に積んだ項目を誰も処理しない」という競合が起きない
        (どちらか一方が先にロックを取り、その時点の状態で結果が
        確定する)。
        """
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._queue.put((None, self._STOP_SENTINEL))
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            coalesce_key, fn = self._queue.get()
            if fn is self._STOP_SENTINEL:
                return
            if coalesce_key is not None:
                with self._lock:
                    self._pending_keys.discard(coalesce_key)
            try:
                fn()
            except Exception:
                errorLogging()


class _AudioDeviceSession:
    """1つの物理デバイス (マイクまたはスピーカー) に対する Recorder の
    ライフサイクルを、features ("transcript"/"energy") 単位で統合管理する。

    以前は文字起こし用と音量メーター用でそれぞれ独立に
    SelectedMic/SpeakerEnergyAndAudioRecorder (= 独立した PyAudio
    Microphone) を生成・破棄しており、Config パネルで音量メーターを
    表示しながら文字起こしを ON にすると、同一物理デバイスに 2 つの
    Microphone が並立し得た。ここでは常に features の和集合に対して
    単一の Recorder を保持することでこれを防ぐ。

    このクラスは抽象基底で、マイク/スピーカー固有の設定 (config キー・
    Recorder クラス・AudioTranscriber の speaker フラグ) はサブクラスで
    _config / _recorder_cls 等として与える。

    Controller serializes entry points with the source lifecycle lock; this
    session also owns _stop_lock for cleanup. Synchronous start callbacks run
    under the caller's lock. Runtime error callbacks enter the controller on a
    separate thread without holding _stop_lock, so it can decide whether to
    continue capture or revoke delivery before cleanup.
    """

    _kind: str = ""  # "mic" / "speaker" — ログ・エラーメッセージ用

    def __init__(self) -> None:
        self.features: set[str] = set()
        self._recorder = None
        self._transcriber: Optional[AudioTranscriber] = None
        self._audio_queue: Optional[Queue] = None
        self._energy_queue: Optional[_EnergyQueue] = None
        self._print_transcript: Optional[threadFnc] = None
        self._energy_progressbar: Optional[threadFnc] = None
        self.transcript_fnc: Optional[Callable[[dict], None]] = None
        self.energy_fnc: Callable[[float], None] = lambda v: None
        self.error_fnc = None
        self.runtime_error_fnc = None
        self.terminal_failure_fnc = None
        self.device_fnc = None
        self._stop_lock = RLock()
        self._cleanup_workers = []
        self._cleanup_failed = Event()
        self._pipeline_error_lock = Lock()
        self._pipeline_error_started = False
        self._pipeline_error_notified = False
        # 現在 Recorder が開いているデバイス (dict) を保持し、
        # reconfigure() で「同一デバイスかつ features 変化なし」なら no-op
        # にするために使う。
        self._active_device: Optional[dict] = None

    @staticmethod
    def _device_key(device: Optional[dict]) -> Optional[tuple]:
        return capture_key(device)

    # --- サブクラスが実装するフック -------------------------------------

    def _resolve_device(self, override: Optional[dict] = None) -> Optional[dict]:
        raise NotImplementedError

    def _create_recorder(self, device: dict):
        raise NotImplementedError

    def _create_transcriber(self) -> AudioTranscriber:
        raise NotImplementedError

    def _transcribe(self, transcriber: AudioTranscriber, queue: Queue) -> bool:
        raise NotImplementedError

    @staticmethod
    def _resolve_api_transcription_kwargs() -> dict:
        """Groq/OpenAI/カスタムサーバー選択時のみ、対応する認証キー/URL/
        モデルを config から解決して `AudioTranscriber` へ渡す kwargs を
        作る。Google/ローカル Whisper 選択時は空の dict を返す (それらの
        引数は `AudioTranscriber` 側で None がデフォルトのため無視される)。
        """
        engine = config.SELECTED_TRANSCRIPTION_ENGINE
        if engine == "Groq_Whisper":
            return {
                "api_key": config.TRANSCRIPTION_AUTH_KEYS.get("Groq_Whisper"),
                "base_url": config.GROQ_WHISPER_BASE_URL,
                "api_model": config.SELECTED_GROQ_WHISPER_MODEL,
            }
        if engine == "OpenAI_Whisper":
            return {
                "api_key": config.TRANSCRIPTION_AUTH_KEYS.get("OpenAI_Whisper"),
                "base_url": config.OPENAI_WHISPER_BASE_URL,
                "api_model": config.SELECTED_OPENAI_WHISPER_MODEL,
            }
        if engine == "Custom_Whisper":
            return {
                "api_key": config.TRANSCRIPTION_AUTH_KEYS.get("Custom_Whisper"),
                "base_url": config.TRANSCRIPTION_CUSTOM_URL,
                "api_model": config.SELECTED_CUSTOM_WHISPER_MODEL,
            }
        if engine == "Deepgram":
            # Deepgram はエンドポイントが固定 (base_url入力欄が無い) ため
            # base_urlは渡さない。api_model_languagesは、選択中モデルが
            # 実際に対応していると申告している言語コード一覧
            # (DeepgramProvider が候補言語1つに確定している場合に、
            # 自動検出の代わりに明示的な language= を解決するために使う)。
            return {
                "api_key": config.TRANSCRIPTION_AUTH_KEYS.get("Deepgram"),
                "api_model": config.SELECTED_DEEPGRAM_MODEL,
                "api_model_languages": config.DEEPGRAM_MODEL_LANGUAGES.get(config.SELECTED_DEEPGRAM_MODEL, []),
            }
        return {}

    # --- 公開 API ---------------------------------------------------------

    def reconfigure(
        self,
        *,
        transcript: Optional[bool] = None,
        energy: Optional[bool] = None,
        device: Optional[dict] = None,
        previous_device: Optional[dict] = None,
    ) -> None:
        """transcript/energy を True で有効化、False で無効化、None で現状維持。

        device を明示指定すると config を読まずそれを使う (Auto 選択で
        「実使用中エンドポイント」を渡すユースケース)。指定しなければ
        従来通り config (SELECTED_MIC_HOST/DEVICE 等) から解決する。

        差分検知: 「新 features == 現 features」かつ「解決したデバイス ==
        _active_device」なら no-op で早期 return。デバイスまたは features
        が変化した場合のみ stop→start する。これにより device 切替時に
        Recorder が二重に close/open されることを防ぐ。
        """
        with self._stop_lock:
            new_features = set(self.features)
            if transcript is True:
                new_features.add("transcript")
            elif transcript is False:
                new_features.discard("transcript")
            if energy is True:
                new_features.add("energy")
            elif energy is False:
                new_features.discard("energy")

            # override が指定されなければ config から解決 (下位互換)
            resolved_device = self._resolve_device(override=device)

            same_features = new_features == self.features
            same_device = self._device_key(resolved_device) == self._device_key(self._active_device)
            # `_recorder is not None` だけでは、_start() が Recorder を生成した
            # 直後 (listener 起動前) に例外で失敗したケースを "起動済み" と誤認
            # してしまう (P0-2)。_start() は失敗時に必ず _recorder を None へ
            # 巻き戻すので通常はこの2つの判定は同じ結果になるが、"listener が
            # 実際に走っているか" という本来知りたい条件をそのまま書いておく。
            already_running = (not new_features) or (
                self._recorder is not None and self._recorder.stop is not None
                and not self._pipeline_error_started
            )
            if same_features and same_device and already_running:
                return

            previous_device = self._active_device or previous_device
            if new_features and resolved_device is None and callable(self.terminal_failure_fnc):
                self.terminal_failure_fnc()
            self._stop()
            # A bounded join is not permission to reopen the device. Keep all old
            # workers reachable, including recorder cleanup, until they have exited.
            # _cleanup_failed (stop raised) only blocks the exclusive realtime
            # handoff, as before; it never clears, so it must not lock out an
            # ordinary restart for the rest of the session.
            if self._cleanup_workers:
                if new_features and callable(self.terminal_failure_fnc):
                    self.terminal_failure_fnc()
                return
            self.features = new_features
            if self.features:
                try:
                    self._start(device=resolved_device, previous_device=previous_device)
                except Exception:
                    if self._recorder is not None or self.features:
                        self._stop()
                    raise

    def pause(self) -> None:
        if self._recorder is not None and callable(self._recorder.pause):
            self._recorder.pause()

    def resume(self) -> None:
        # 以前は while not empty(): get() という non-atomic な
        # チェック→ブロッキングgetだったため、_print_transcript
        # スレッド (transcribeAudioQueue) が同時に同じキューを
        # drainしていると、resume() が empty()==False を見た直後に
        # その最後の1件を向こうに取られてしまい、後続のブロッキング
        # get() が (もう誰も put しないため) 永久に返らずハングし、
        # self._recorder.resume() が一生呼ばれなくなるバグがあった
        # (レビューで指摘、実機ではVRChatの素早いミュート/アンミュート
        # 切り替えで再現しうる)。get_nowait() のみを使えば、他スレッド
        # と競合しても即座に Empty を返すだけでブロックし得ない。
        if isinstance(self._audio_queue, Queue):
            while True:
                try:
                    self._audio_queue.get_nowait()
                except Empty:
                    break
        if self._recorder is not None and callable(self._recorder.resume):
            self._recorder.resume()

    @property
    def device_error_event(self):
        return self._recorder.device_error_event if self._recorder is not None else None

    def _make_pipeline_failure(
        self,
        error_code: ErrorCode,
        stage: str,
        error: Optional[Exception] = None,
    ) -> AudioPipelineFailure:
        if error is not None:
            errorLogging()
        return AudioPipelineFailure(
            error_code=error_code,
            stage=stage,
            source=self._kind,
            message=ERROR_METADATA[error_code]["message"],
            exception_type=type(error).__name__ if error is not None else None,
        )

    def _notify_pipeline_error(self, failure: AudioPipelineFailure, callback=None) -> None:
        with self._pipeline_error_lock:
            if self._pipeline_error_notified:
                return
            self._pipeline_error_notified = True
        callback = callback or self.error_fnc or self.transcript_fnc
        if callable(callback):
            try:
                callback(failure.to_notification())
            except Exception:
                errorLogging()

    def _handle_pipeline_error(self, failure: AudioPipelineFailure, recorder=None) -> None:
        """録音ワーカーからの異常を一度だけ停止・通知する。"""
        with self._pipeline_error_lock:
            if recorder is not None and self._recorder is not recorder:
                return
            if self._pipeline_error_started:
                return
            self._pipeline_error_started = True

        # 自分自身を join できないため、現在の worker は先にループを
        # 終了させ、停止・後始末・通知は別スレッドで行う。
        worker = self._print_transcript
        if worker is not None and worker is current_thread():
            worker.stop()

        error_callback = self.error_fnc or self.transcript_fnc
        failed_device = self._active_device
        runtime_callback = self.runtime_error_fnc

        def cleanup_and_notify() -> None:
            if callable(runtime_callback):
                # The controller decides continuation vs terminal failure under
                # its source lock, then owns cleanup. Do not hold the session
                # lock while crossing that boundary or stop before revocation.
                self._notify_pipeline_error(failure, lambda data: runtime_callback(
                    {**data, "failed_device": failed_device}))
                return
            with self._stop_lock:
                if recorder is not None and self._recorder is not recorder:
                    return
                cleanup_timed_out = self._stop()
                if cleanup_timed_out:
                    failure_to_notify = self._make_pipeline_failure(
                        ErrorCode.CLEANUP_TIMEOUT, "cleanup"
                    )
                else:
                    failure_to_notify = failure
            if self.error_fnc is not None and error_callback is not None:
                callback = lambda data: error_callback({**data, "failed_device": failed_device})
            else:
                callback = error_callback
            self._notify_pipeline_error(failure_to_notify, callback)

        Thread(
            target=cleanup_and_notify,
            daemon=True,
            name=f"{self._kind}-transcription-error-cleanup",
        ).start()

    # --- 内部実装 ---------------------------------------------------------

    def _start(self, *, device: Optional[dict], previous_device=None) -> None:
        # 呼び出し元 (reconfigure) が _resolve_device で解決済みの
        # デバイスを渡す。None は「使用可能なデバイス無し」を意味し、
        # ここで再解決はしない (再解決すると reconfigure の意図した
        # None → 停止のセマンティクスが壊れる)。
        if device is None:
            if "transcript" in self.features and callable(self.transcript_fnc):
                self.transcript_fnc({"text": False, "language": None})
            if "energy" in self.features:
                self.energy_fnc(False)
            self.features = set()
            self._active_device = None
            return

        requested_device = device

        with self._pipeline_error_lock:
            self._pipeline_error_started = False
            self._pipeline_error_notified = False

        start_failure: Optional[AudioPipelineFailure] = None
        try:
            try:
                candidates = [device]
                if self._kind == "mic":
                    default = device_manager.getDefaultMicDevice().get("device")
                    available = [d for devices in device_manager.getMicDevices().values() for d in devices]
                else:
                    default = device_manager.getDefaultSpeakerDevice().get("device")
                    available = device_manager.getSpeakerDevices()
                for candidate in [default, *available]:
                    if (candidate and candidate.get("name") != "NoDevice"
                            and "node_name" not in candidate
                            and capture_key(candidate) not in [capture_key(d) for d in candidates]):
                        candidates.append(candidate)
                for candidate in candidates:
                    try:
                        self._recorder = self._create_recorder(candidate)
                        device = candidate
                        break
                    except AudioOpenBusy:
                        raise
                    except OSError:
                        if candidate is candidates[-1]:
                            raise
            except Exception as error:  # noqa: BLE001 - convert to safe UI error
                start_failure = self._make_pipeline_failure(
                    ErrorCode.AUDIO_OPEN_ERROR,
                    "recording",
                    error,
                )
                raise

            audio_queue = _AudioQueue() if "transcript" in self.features else _DiscardQueue()
            # energy_queue はメーター表示用で直近の値のみ意味を持つため、
            # audio_queue と同じ理由 (レビュー指摘、フェーズ3項目20) で
            # 有界化する。maxsize=1 で「最新の未読み取り値のみ保持」にする。
            energy_queue = _EnergyQueue() if "energy" in self.features else None
            self._audio_queue = audio_queue
            self._energy_queue = energy_queue
            recorder = self._recorder
            error_event = audio_queue.device_error_event if isinstance(audio_queue, _AudioQueue) else _AudioQueueEvent(audio_queue)
            error_event.on_error = lambda: self._handle_pipeline_error(
                getattr(recorder, "device_error_info", None)
                or self._make_pipeline_failure(ErrorCode.AUDIO_READ_ERROR, "recording"), recorder)
            had_error = recorder.device_error_event.is_set()
            recorder.device_error_event = error_event
            if had_error is True:
                error_event.set()
            self._recorder.recordIntoQueue(audio_queue, energy_queue)
            if error_event.is_set():
                raise OSError("Audio listener failed to start")
            if "transcript" in self.features:
                try:
                    self._transcriber = self._create_transcriber()
                except Exception as error:  # noqa: BLE001 - initialization failure
                    start_failure = self._make_pipeline_failure(
                        ErrorCode.TRANSCRIBER_INIT_ERROR,
                        "asr",
                        error,
                    )
                    raise
        except Exception:
            # Recorder open/listener または Transcriber 初期化が失敗した場合も、
            # 開始済みのリソースを同じ停止経路で回収してから UI へ通知する。
            if start_failure is None:
                start_failure = getattr(self._recorder, "device_error_info", None)
            if start_failure is None:
                start_failure = self._make_pipeline_failure(
                    ErrorCode.AUDIO_READ_ERROR,
                    "recording",
                )
            if callable(self.terminal_failure_fnc):
                self.terminal_failure_fnc()
            cleanup_timed_out = self._stop()
            if cleanup_timed_out:
                start_failure = self._make_pipeline_failure(ErrorCode.CLEANUP_TIMEOUT, "cleanup")
            if start_failure is not None:
                self._notify_pipeline_error(start_failure)
            raise

        self._active_device = dict(device)
        if callable(self.device_fnc):
            self.device_fnc(self._active_device, previous_device or requested_device)

        if "transcript" in self.features:
            transcriber = self._transcriber
            recorder = self._recorder

            def sendTranscript() -> None:
                if not audio_queue.waitForWork(transcriber.getAudioWaitTimeout()):
                    return
                if self._recorder is not recorder:
                    return
                if recorder.device_error_event.is_set():
                    failure = getattr(recorder, "device_error_info", None)
                    if failure is None:
                        failure = self._make_pipeline_failure(
                            ErrorCode.AUDIO_READ_ERROR,
                            "recording",
                        )
                    self._handle_pipeline_error(failure, recorder)
                    return
                try:
                    self._transcribe(transcriber, audio_queue)
                    if self._transcriber is not transcriber:
                        return
                    # 溜まっている分を全て配信する。1回の transcribeAudioQueue()
                    # が複数件を積むことがある (Google の interim_send は
                    # キューから取り出したチャンクごとに走る) のに対し、
                    # 以前はここで1件しか取り出しておらず、残りは「次に ASR が
                    # 成功した時」まで配信されなかった。発話が止まるとそのまま
                    # 埋もれ、max_phrases を超えると古い順に無言で捨てられて
                    # いた (実機ログで ASR 成功4件に対し配信1件を確認)。
                    # _transcribe の戻り値で分岐しないのは、前回の呼び出しが
                    # 残した分もここで確実に吐き出すため。
                    if callable(self.transcript_fnc):
                        while transcriber.hasTranscript():
                            result = transcriber.getTranscript()
                            result["recognition_error"] = transcriber.last_recognition_error
                            self.transcript_fnc(result)
                except AudioPipelineError as error:
                    if self._transcriber is transcriber:
                        self._handle_pipeline_error(error.failure, recorder)
                except Exception as error:  # noqa: BLE001 - fail closed at ASR boundary
                    failure = self._make_pipeline_failure(ErrorCode.ASR_ERROR, "asr", error)
                    if self._transcriber is transcriber:
                        self._handle_pipeline_error(failure, recorder)

            def endTranscript() -> None:
                utterance_diagnostics.flush(self._kind)
                while True:
                    try:
                        audio_queue.get_nowait()
                    except Empty:
                        break
                # A timed-out old worker may finish after reconfigure() has
                # already installed a new transcriber. Only clear the object
                # owned by this worker; otherwise the late cleanup can make
                # the new transcription pipeline fail with None.
                if self._transcriber is transcriber:
                    self._transcriber = None
                # 明示 gc.collect() は呼ばない: ActiveEndpointTracker が別スレッド
                # (CoInitialize 済み apartment) で保持している comtypes の COM
                # ポインタが、この _print_transcript スレッド (CoInitialize
                # していない) 上で __del__ → Release() されて access violation
                # を起こすことを crash_trace.log で 2026-08-19 に確認した。
                # 参照が実際に不要になれば通常の GC が回収する。

            self._print_transcript = threadFnc(sendTranscript, end_fnc=endTranscript)
            self._print_transcript.daemon = True
            self._print_transcript.start()

        if "energy" in self.features:
            energy_recorder = self._recorder
            def sendEnergy() -> None:
                energy = energy_queue.getUntilStopped()
                if (energy is None or self._recorder is not energy_recorder
                        or energy_recorder.device_error_event.is_set()):
                    return
                try:
                    self.energy_fnc(energy)
                except Exception:
                    errorLogging()

            self._energy_progressbar = threadFnc(sendEnergy)
            self._energy_progressbar.daemon = True
            self._energy_progressbar.start()

    def _stop(self) -> bool:
        """停止とリソース解放を行い、完了できなければ True を返す。"""
        cleanup_timed_out = False
        with self._stop_lock:
            self._cleanup_workers = [worker for worker in self._cleanup_workers if worker.is_alive()]
            cleanup_timed_out = bool(self._cleanup_workers)
            source = getattr(self._recorder, "source", None)
            cancel = getattr(source, "cancel", None)
            if callable(cancel):
                cancel()
            transcript_thread = self._print_transcript
            if isinstance(transcript_thread, threadFnc):
                transcript_thread.stop()
                if isinstance(self._audio_queue, _AudioQueue):
                    self._audio_queue.stop()
                if transcript_thread is not current_thread():
                    transcript_thread.join(timeout=TRANSCRIPT_STOP_JOIN_TIMEOUT)
                    if transcript_thread.is_alive():
                        cleanup_timed_out = True
                        printLog(
                            f"{self._kind.capitalize()} transcription thread did not terminate within timeout"
                        )
                if transcript_thread.is_alive():
                    self._cleanup_workers.append(transcript_thread)
                self._print_transcript = None

            energy_thread = self._energy_progressbar
            if isinstance(energy_thread, threadFnc):
                energy_thread.stop()
                if self._energy_queue is not None:
                    self._energy_queue.stop()
                if energy_thread is not current_thread():
                    energy_thread.join(timeout=TRANSCRIPT_STOP_JOIN_TIMEOUT)
                    if energy_thread.is_alive():
                        cleanup_timed_out = True
                        printLog(
                            f"{self._kind.capitalize()} energy thread did not terminate within timeout"
                        )
                if energy_thread.is_alive():
                    self._cleanup_workers.append(energy_thread)
                self._energy_progressbar = None

            recorder = self._recorder
            if recorder is not None:
                # stop() 内部の listener join が予期せず長引いても、UI 操作や
                # エラー通知を無期限にブロックしないよう別スレッドで待つ。
                try:
                    if callable(recorder.resume):
                        recorder.resume()
                except Exception:
                    errorLogging()

                if callable(recorder.stop) or callable(getattr(source, "close", None)):
                    def stop_recorder():
                        try:
                            if callable(recorder.stop):
                                recorder.stop(wait_for_stop=True)
                            elif callable(getattr(source, "close", None)):
                                source.close()
                        except Exception:
                            # A dead cleanup thread is not proof that the device
                            # was released. Keep handoff blocked until restart.
                            self._cleanup_failed.set()

                    stop_thread = Thread(
                        target=stop_recorder,
                        daemon=True,
                        name=f"{self._kind}-recorder-stop",
                    )
                    stop_thread.start()
                    stop_thread.join(timeout=TRANSCRIPT_STOP_JOIN_TIMEOUT)
                    if stop_thread.is_alive():
                        cleanup_timed_out = True
                        self._cleanup_workers.append(stop_thread)
                        printLog(
                            f"{self._kind.capitalize()} recorder did not stop within timeout"
                        )
                self._recorder = None

            if isinstance(self._audio_queue, Queue):
                while True:
                    try:
                        self._audio_queue.get_nowait()
                    except Empty:
                        break
            self._transcriber = None
            self._audio_queue = None
            self._active_device = None
            self.features = set()
        utterance_diagnostics.flush(self._kind)
        return cleanup_timed_out

    def stop_for_handoff(self) -> bool:
        """Stop all legacy features, retaining incomplete cleanup across retries."""
        self._stop()
        with self._stop_lock:
            self._cleanup_workers = [worker for worker in self._cleanup_workers if worker.is_alive()]
            return (not self._cleanup_workers and not self._cleanup_failed.is_set()
                    and not audioOpenOutstanding(self._kind))


class MicSession(_AudioDeviceSession):
    _kind = "mic"

    def _resolve_device(self, override: Optional[dict] = None) -> Optional[dict]:
        if override is not None:
            # NoDevice が明示的に渡された場合は None (デバイス無し) 扱い
            if override.get("name") == "NoDevice":
                return None
            return override
        mic_host_name = config.SELECTED_MIC_HOST
        mic_device_name = config.SELECTED_MIC_DEVICE
        mic_device_list = device_manager.getMicDevices().get(mic_host_name, [{"name": "NoDevice"}])
        device = resolve_device(mic_device_list, config.SELECTED_MIC_DEVICE_ID, mic_device_name)
        if device is None or "node_name" in device:
            return None
        return device

    def _create_recorder(self, device: dict):
        record_timeout = config.MIC_RECORD_TIMEOUT
        phrase_timeout = config.MIC_PHRASE_TIMEOUT
        if record_timeout > phrase_timeout:
            record_timeout = phrase_timeout
        if config.MIC_ENABLE_VAD is True:
            return SelectedMicVadRecorder(device=device, record_timeout=record_timeout)
        return SelectedMicEnergyAndAudioRecorder(
            device=device,
            energy_threshold=config.MIC_THRESHOLD,
            dynamic_energy_threshold=config.MIC_AUTOMATIC_THRESHOLD,
            phrase_time_limit=record_timeout,
            record_timeout=record_timeout,
        )

    def _create_transcriber(self) -> AudioTranscriber:
        phrase_timeout = config.MIC_PHRASE_TIMEOUT
        return AudioTranscriber(
            speaker=False,
            source=self._recorder,
            phrase_timeout=phrase_timeout,
            max_phrases=config.MIC_MAX_PHRASES,
            transcription_engine=config.SELECTED_TRANSCRIPTION_ENGINE,
            root=config.PATH_DATA,
            whisper_weight_type=config.WHISPER_WEIGHT_TYPE,
            device=config.SELECTED_TRANSCRIPTION_COMPUTE_DEVICE["device"],
            device_index=config.SELECTED_TRANSCRIPTION_COMPUTE_DEVICE["device_index"],
            compute_type=config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE,
            vad_segmented=config.MIC_ENABLE_VAD is True,
            source_label="mic",
            **self._resolve_api_transcription_kwargs(),
        )

    def _transcribe(self, transcriber: AudioTranscriber, queue: Queue) -> bool:
        selected_your_languages = config.SELECTED_YOUR_LANGUAGES[config.SELECTED_TAB_NO]
        languages = [d["language"] for d in selected_your_languages.values() if d["enable"] is True]
        countries = [d["country"] for d in selected_your_languages.values() if d["enable"] is True]
        return transcriber.transcribeAudioQueue(
            queue,
            languages,
            countries,
            config.MIC_AVG_LOGPROB,
            config.MIC_NO_SPEECH_PROB,
            config.MIC_NO_REPEAT_NGRAM_SIZE,
        )


class SpeakerSession(_AudioDeviceSession):
    _kind = "speaker"

    def _resolve_device(self, override: Optional[dict] = None) -> Optional[dict]:
        if override is not None:
            if override.get("name") == "NoDevice":
                return None
            return override
        speaker_device_name = config.SELECTED_SPEAKER_DEVICE
        speaker_device_list = device_manager.getSpeakerDevices()
        return resolve_device(speaker_device_list, config.SELECTED_SPEAKER_DEVICE_ID, speaker_device_name)

    def _create_recorder(self, device: dict):
        record_timeout = config.SPEAKER_RECORD_TIMEOUT
        phrase_timeout = config.SPEAKER_PHRASE_TIMEOUT
        if record_timeout > phrase_timeout:
            record_timeout = phrase_timeout
        if config.SPEAKER_ENABLE_VAD is True:
            return SelectedSpeakerVadRecorder(device=device, record_timeout=record_timeout)
        return SelectedSpeakerEnergyAndAudioRecorder(
            device=device,
            energy_threshold=config.SPEAKER_THRESHOLD,
            dynamic_energy_threshold=config.SPEAKER_AUTOMATIC_THRESHOLD,
            phrase_time_limit=record_timeout,
            record_timeout=record_timeout,
        )

    def _create_transcriber(self) -> AudioTranscriber:
        phrase_timeout = config.SPEAKER_PHRASE_TIMEOUT
        return AudioTranscriber(
            speaker=True,
            source=self._recorder,
            phrase_timeout=phrase_timeout,
            max_phrases=config.SPEAKER_MAX_PHRASES,
            transcription_engine=config.SELECTED_TRANSCRIPTION_ENGINE,
            root=config.PATH_DATA,
            whisper_weight_type=config.WHISPER_WEIGHT_TYPE,
            device=config.SELECTED_TRANSCRIPTION_COMPUTE_DEVICE["device"],
            device_index=config.SELECTED_TRANSCRIPTION_COMPUTE_DEVICE["device_index"],
            compute_type=config.SELECTED_TRANSCRIPTION_COMPUTE_TYPE,
            vad_segmented=config.SPEAKER_ENABLE_VAD is True,
            source_label="speaker",
            **self._resolve_api_transcription_kwargs(),
        )

    def _transcribe(self, transcriber: AudioTranscriber, queue: Queue) -> bool:
        selected_target_languages = config.SELECTED_TARGET_LANGUAGES[config.SELECTED_TAB_NO]
        languages = [d["language"] for d in selected_target_languages.values() if d["enable"] is True]
        countries = [d["country"] for d in selected_target_languages.values() if d["enable"] is True]
        return transcriber.transcribeAudioQueue(
            queue,
            languages,
            countries,
            config.SPEAKER_AVG_LOGPROB,
            config.SPEAKER_NO_SPEECH_PROB,
            config.SPEAKER_NO_REPEAT_NGRAM_SIZE,
        )


class Model:
    _instance = None
    # 停止時に None にせず、メッセージ処理から常に安全に参照できるようにする。
    logger = ConversationLogger()
    message_delivery = DeliveryEpochs()
    chatbox_order = ChatboxOrder()
    # Model is a singleton. Serialize feature ownership even when start/stop
    # arrive on different IPC handler threads.
    _watchdog_lifecycle_lock = Lock()
    _ocr_lifecycle_lock = Lock()
    _ocr_shutdown_requested = False
    _obs_lifecycle_lock = RLock()
    # OSC 受信と OSCQuery の結果を反映するスレッドの間で、確認と更新を一度に行う。
    _mute_status_lock = Lock()
    _mute_status_generation = 0
    # 確認待ちの最後の false が届いた世代。複数の通知でキューを増やさない。
    _mute_verification_pending: Optional[int] = None
    # /avatar/change とミュート解除の確認を行う。OSCHandler が問い合わせの待ち時間を制限する。
    # OSC 受信スレッドとマイク操作のキューは、HTTP の待ちで止めない。
    _avatar_query_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="osc_avatar_query")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Model, cls).__new__(cls)
            # Do NOT call init() here to avoid heavy import-time work.
            # Callers should call `model.init()` explicitly or rely on
            # `ensure_initialized()` which will lazy-initialize on demand.
            cls._instance._inited = False
            cls._instance._init_failed = False
        return cls._instance

    def init(self):
        """Perform full initialization of resources.

        This method performs heavy construction (models, overlay, threads)
        and is intentionally not called at import time. Call explicitly
        or let `ensure_initialized()` call it lazily.
        """
        if getattr(self, '_inited', False) or getattr(self, '_init_failed', False):
            return

        # 「成功が証明されるまで失敗扱い」にしておく。init() は途中で
        # AudioLifecycleWorker (コンストラクタが即 daemon thread を起動する)
        # や Clipboard / Telemetry を生成するため、後半で例外が出たときに
        # 再実行を許すと、そのたびに新しいスレッドが生成され、前回分は
        # 誰からも参照されないまま生き残る。ensure_initialized() は
        # 例外を握りつぶして続行するので、public メソッドが呼ばれるたびに
        # これが繰り返されスレッドが際限なく増える。shutdown() が停止
        # できるのは最新の 1 組だけなので、終了時に古いワーカーが
        # PyAudio 操作の途中でプロセス終了に巻き込まれる経路も残る。
        # 壊れたインストールや SteamVR 異常で OverlayImage/Clipboard の
        # 生成が失敗するケースは再試行しても直らないため、1 回で諦める。
        self._init_failed = True

        self.th_check_device = None
        # startWatchdog() より前に shutdown() が走る経路 (init 失敗時など) で
        # stopWatchdog() の isinstance チェックが AttributeError にならないよう
        # ここで宣言しておく。
        self.th_watchdog = None
        # watchdog は init() の先頭で作る。フロントエンドは spawn 直後から
        # /run/feed_watchdog を送り続け、ハンドラワーカーは init() の実行中でも
        # feedWatchdog() を処理する。ensure_initialized() は _init_failed
        # のため init() を再実行せず素通りするので、ここより後 (Overlay や
        # オーディオ初期化の後) で作ると、遅い環境 (ビルド版) で
        # 'Model' object has no attribute 'watchdog' になる。
        self.watchdog = Watchdog(config.WATCHDOG_TIMEOUT, config.WATCHDOG_INTERVAL)
        # マイク/スピーカーそれぞれの文字起こし・エナジー計測は
        # _AudioDeviceSession (MicSession/SpeakerSession) に集約されている。
        # 1 物理デバイスにつき Recorder (= PyAudio Microphone) が常に
        # 1 つだけになるよう、features (transcript/energy) の和集合を
        # session が管理する。
        self._mic_session = MicSession()
        self._speaker_session = SpeakerSession()
        # mic/speaker で別インスタンスにする理由は AudioLifecycleWorker の
        # docstring 参照 (フェーズ3項目21)。
        self.mic_lifecycle_worker = AudioLifecycleWorker()
        self.speaker_lifecycle_worker = AudioLifecycleWorker()

        self.previous_send_message = ""
        self.previous_receive_message = ""
        # getInputTranslate() がターゲット言語ごとの翻訳を並列化するための
        # 常設プール。使い捨てにすると、translators 側のスレッドローカルな
        # セッションが毎回作り直され、ウォームアップ (ホストGET + 言語マップ
        # 取得) のコストを毎回払うことになる。ワーカー数はターゲット言語の
        # スロット数 (SELECTED_TAB_TARGET_LANGUAGES_NO_LIST) が上限。
        self._translation_executor = ThreadPoolExecutor(
            max_workers=len(config.SELECTED_TAB_TARGET_LANGUAGES_NO_LIST),
            thread_name_prefix="vrct-translate",
        )
        self.translator = Translator()
        self.keyword_processor = KeywordProcessor()
        self.translation_history: list[dict] = []
        self.translation_history_max_items = 20
        overlay_small_log_settings = copy.deepcopy(config.OVERLAY_SMALL_LOG_SETTINGS)
        overlay_large_log_settings = copy.deepcopy(config.OVERLAY_LARGE_LOG_SETTINGS)
        overlay_large_log_settings["ui_scaling"] = overlay_large_log_settings["ui_scaling"] * 0.25
        if launcherOutOfReach(config.OVERLAY_VR_LAUNCHER_SETTINGS):
            # 保存されたランチャーが手首から遠すぎる、または小さすぎ・大きすぎて、見失う
            printLog("overlay: ランチャーの位置か大きさが範囲の外だったので、手首の近くへ寄せます")
            # 初期には戻さず、手首から一番近い限度の内側へ寄せる (向き・付ける手は変えない)
            config.OVERLAY_VR_LAUNCHER_SETTINGS = {**config.OVERLAY_VR_LAUNCHER_SETTINGS,
                                                   **launcherNearestInReach(config.OVERLAY_VR_LAUNCHER_SETTINGS)}
        overlay_settings = {
            "small": overlay_small_log_settings,
            "large": overlay_large_log_settings,
            PANEL: copy.deepcopy(config.OVERLAY_VR_PANEL_SETTINGS),
            LAUNCHER: copy.deepcopy(config.OVERLAY_VR_LAUNCHER_SETTINGS),
            # 一時ウィンドウ (言語 / VR設定)。開くたびにランチャーの近くに置き直すので保存しない
            POPUP: {
                "x_pos": 0.0, "y_pos": 0.0, "z_pos": 0.0,
                "x_rotation": 0.0, "y_rotation": 0.0, "z_rotation": 0.0,
                "display_duration": 5, "fadeout_duration": 0, "opacity": 1.0,
                "ui_scaling": 0.36, "tracker": "Playspace",
            },
        }
        self.overlay = Overlay(overlay_settings)
        self.overlay.launcher_defaults = dict(DEFAULT_OVERLAY_VR_LAUNCHER_SETTINGS)
        self.overlay_image = OverlayImage(config.PATH_LOCAL)
        self.mic_mute_status = None
        # OSC ミュート同期 (changeHandlerMute) が実行する pause()/resume() を
        # Controller.mic_lifecycle_lock 配下で行うためのフック。
        # Controller.__init__ が setMicMuteStatusChangeCallback() で
        # 自身のロック付きラッパーを登録する。Model は Controller を知らない
        # ままこの間接呼び出しだけを持つ (transcript_fnc/energy_fnc と同じ
        # コールバック注入パターン)。未登録時は changeMicTranscriptStatus() を
        # 直接使うフォールバックとする。
        self.mic_mute_status_change_callback: Optional[Callable[[], None]] = None
        self.transliterator = None
        self.osc_handler = OSCHandler(config.OSC_IP_ADDRESS, config.OSC_PORT)
        self.websocket_server = None
        # Publish each server under the lock, then wait outside it so a stop
        # can cancel startup. The server object is the attempt's identity.
        self._websocket_lifecycle_lock = Lock()
        self.obs_browser_source_server = None
        self.clipboard = Clipboard()
        self.ocr_pipeline: Optional[OcrPipeline] = None
        self._ocr_model_root = None
        self._ocr_detector_path: Optional[str] = None
        self.telemetry = Telemetry()

        self._inited = True
        self._init_failed = False

    def ensure_initialized(self) -> None:
        """Ensure the model has been initialized. This is safe to call from
        public methods that require initialized resources.
        """
        if not getattr(self, '_inited', False):
            try:
                self.init()
            except Exception:
                # Log and continue; callers should handle missing features.
                errorLogging()

    def backwardCompatibleTranslatorCTranslate2ModelRenameWeightsDir(self):
        return backwardCompatibleRenameWeightsDir(config.PATH_DATA)
        
    def checkTranslatorCTranslate2ModelWeight(self, weight_type:str):
        if not checkCTranslate2Weight(config.PATH_DATA, weight_type):
            return False
        try:
            downloadCTranslate2Tokenizer(config.PATH_DATA, weight_type, local_files_only=True)
            return True
        except MissingCTranslate2Tokenizer:
            return False

    def hasTranslatorCTranslate2ModelWeightFile(self, weight_type:str):
        return hasCTranslate2WeightFile(config.PATH_DATA, weight_type)

    def changeTranslatorCTranslate2Model(self):
        self.ensure_initialized()
        self.translator.changeCTranslate2Model(
            path=config.PATH_DATA,
            model_type=config.CTRANSLATE2_WEIGHT_TYPE,
            device=config.SELECTED_TRANSLATION_COMPUTE_DEVICE["device"],
            device_index=config.SELECTED_TRANSLATION_COMPUTE_DEVICE["device_index"],
            compute_type=config.SELECTED_TRANSLATION_COMPUTE_TYPE
            )

    def downloadCTranslate2ModelWeight(self, weight_type, callback=None, end_callback=None, *, control=None):
        return downloadCTranslate2Weight(config.PATH_DATA, weight_type, callback, end_callback, control=control)

    def downloadCTranslate2ModelTokenizer(self, weight_type):
        return downloadCTranslate2Tokenizer(config.PATH_DATA, weight_type, local_files_only=True)

    def isLoadedCTranslate2Model(self):
        self.ensure_initialized()
        return self.translator.isLoadedCTranslate2Model()

    def isChangedTranslatorParameters(self):
        self.ensure_initialized()
        return self.translator.isChangedTranslatorParameters()

    def setChangedTranslatorParameters(self, is_changed):
        self.ensure_initialized()
        self.translator.setChangedTranslatorParameters(is_changed)

    def checkTranscriptionWhisperModelWeight(self, weight_type:str):
        return checkWhisperWeight(config.PATH_DATA, weight_type)

    def downloadWhisperModelWeight(self, weight_type, callback=None, end_callback=None, *, control=None):
        return downloadWhisperWeight(config.PATH_DATA, weight_type, callback, end_callback, control=control)

    def authenticationTranscriptionApiKey(self, api_key: str, base_url: str) -> bool:
        return checkTranscriptionApiKey(api_key, base_url)

    def getTranscriptionApiModelList(self, api_key: str, base_url: str, keyword_filter: Optional[list[str]] = None) -> list[str]:
        return getAvailableTranscriptionModels(api_key, base_url, keyword_filter=keyword_filter)

    def authenticationDeepgramApiKey(self, api_key: str) -> bool:
        return checkDeepgramApiKey(api_key)

    def getDeepgramModelList(self, api_key: str) -> list[str]:
        return getAvailableDeepgramModels(api_key)

    def getDeepgramModelListDetailed(self, api_key: str) -> list[dict]:
        """モデル名と対応言語コード一覧つきで返す (UI向けメタデータ)。"""
        return getAvailableDeepgramModelsDetailed(api_key)

    def resetKeywordProcessor(self):
        self.ensure_initialized()
        del self.keyword_processor
        self.keyword_processor = KeywordProcessor()

    def prepareTranslatorCredential(self, engine_key: str, auth_key: str,
                                    selected_model=None, base_url=None):
        self.ensure_initialized()
        return self.translator.prepareCredential(
            engine_key, auth_key, selected_model=selected_model,
            root_path=config.PATH_LOCAL, base_url=base_url,
        )

    def commitTranslatorCredential(self, engine_key: str, candidate) -> None:
        self.translator.commitCredential(engine_key, candidate)

    def authenticationTranslatorDeepLAuthKey(self, auth_key: str) -> bool:
        self.ensure_initialized()
        result = self.translator.authenticationDeepLAuthKey(auth_key)
        return result

    def authenticationTranslatorPlamoAuthKey(self, auth_key: str) -> bool:
        result = self.translator.authenticationPlamoAuthKey(auth_key, root_path=config.PATH_LOCAL)
        return result

    def getTranslatorPlamoModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getPlamoModelList()

    def setTranslatorPlamoModel(self, model: str) -> bool:
        self.ensure_initialized()
        result = self.translator.setPlamoModel(model=model)
        return result

    def updateTranslatorPlamoClient(self) -> None:
        self.ensure_initialized()
        self.translator.updatePlamoClient()

    def authenticationTranslatorGeminiAuthKey(self, auth_key: str) -> bool:
        result = self.translator.authenticationGeminiAuthKey(auth_key, root_path=config.PATH_LOCAL)
        return result

    def getTranslatorGeminiModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getGeminiModelList()

    def setTranslatorGeminiModel(self, model: str) -> bool:
        self.ensure_initialized()
        result = self.translator.setGeminiModel(model=model)
        return result

    def updateTranslatorGeminiClient(self) -> None:
        self.ensure_initialized()
        self.translator.updateGeminiClient()

    def authenticationTranslatorOpenAIAuthKey(self, auth_key: str, base_url: Optional[str] = None) -> bool:
        result = self.translator.authenticationOpenAIAuthKey(auth_key, base_url=base_url, root_path=config.PATH_LOCAL)
        return result

    def getTranslatorOpenAIModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getOpenAIModelList()

    def setTranslatorOpenAIModel(self, model: str) -> bool:
        self.ensure_initialized()
        result = self.translator.setOpenAIModel(model=model)
        return result

    def updateTranslatorOpenAIClient(self) -> None:
        self.ensure_initialized()
        self.translator.updateOpenAIClient()

    def authenticationTranslatorOpenAICompatibleAuthKey(self, auth_key: str, base_url: Optional[str] = None) -> bool:
        result = self.translator.authenticationOpenAICompatibleAuthKey(
            auth_key, base_url=base_url, root_path=config.PATH_LOCAL
        )
        return result

    def getTranslatorOpenAICompatibleModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getOpenAICompatibleModelList()

    def setTranslatorOpenAICompatibleModel(self, model: str) -> bool:
        self.ensure_initialized()
        return self.translator.setOpenAICompatibleModel(model=model)

    def updateTranslatorOpenAICompatibleClient(self) -> None:
        self.ensure_initialized()
        self.translator.updateOpenAICompatibleClient()

    def authenticationTranslatorGroqAuthKey(self, auth_key: str) -> bool:
        result = self.translator.authenticationGroqAuthKey(auth_key, root_path=config.PATH_LOCAL)
        return result

    def getTranslatorGroqModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getGroqModelList()

    def setTranslatorGroqModel(self, model: str) -> bool:
        self.ensure_initialized()
        result = self.translator.setGroqModel(model=model)
        return result

    def updateTranslatorGroqClient(self) -> None:
        self.ensure_initialized()
        self.translator.updateGroqClient()

    def authenticationTranslatorOpenRouterAuthKey(self, auth_key: str) -> bool:
        result = self.translator.authenticationOpenRouterAuthKey(auth_key, root_path=config.PATH_LOCAL)
        return result

    def getTranslatorOpenRouterModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getOpenRouterModelList()

    def setTranslatorOpenRouterModel(self, model: str) -> bool:
        self.ensure_initialized()
        result = self.translator.setOpenRouterModel(model=model)
        return result

    def updateTranslatorOpenRouterClient(self) -> None:
        self.ensure_initialized()
        self.translator.updateOpenRouterClient()

    def getTranslatorLMStudioConnected(self) -> bool:
        self.ensure_initialized()
        return self.translator.getLMStudioConnected()

    def authenticationTranslatorLMStudio(self, base_url: str) -> bool:
        result = self.translator.setLMStudioClientURL(base_url=base_url, root_path=config.PATH_LOCAL)
        return result

    def getTranslatorLMStudioModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getLMStudioModelList()

    def setTranslatorLMStudioModel(self, model: str) -> bool:
        self.ensure_initialized()
        return self.translator.setLMStudioModel(model=model)

    def updateTranslatorLMStudioClient(self) -> None:
        self.ensure_initialized()
        self.translator.updateLMStudioClient()

    def getTranslatorOllamaConnected(self) -> bool:
        self.ensure_initialized()
        return self.translator.getOllamaConnected()

    def authenticationTranslatorOllama(self) -> bool:
        result = self.translator.checkOllamaClient(root_path=config.PATH_LOCAL)
        return result

    def getTranslatorOllamaModelList(self) -> list[str]:
        self.ensure_initialized()
        return self.translator.getOllamaModelList()

    def setTranslatorOllamaModel(self, model: str) -> bool:
        self.ensure_initialized()
        return self.translator.setOllamaModel(model=model)

    def updateTranslatorOllamaClient(self) -> None:
        self.ensure_initialized()
        self.translator.updateOllamaClient()

    def startLogger(self):
        self.ensure_initialized()
        os_makedirs(config.PATH_LOGS, exist_ok=True)
        file_name = os_path.join(config.PATH_LOGS, f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
        self.logger.start(file_name)

    def stopLogger(self):
        self.ensure_initialized()
        self.logger.stop()

    def getListLanguageAndCountry(self):
        """List every language any translation engine supports for the UI.

        Deliberately NOT filtered by translation engine: a user should be
        able to pick any language up front, and if the selected translation
        engine doesn't support it, the engine falls back instead (see
        Controller.updateTranslationEngineAndEngineList()). Filtering this
        list by translation engine instead forces users to switch to a
        broadly-compatible engine first, pick the language, then switch
        back - exactly the friction this list avoids.

        This list IS filtered by the current TRANSCRIPTION engine, though
        (see isLanguageSupportedByTranscriptionEngine()): transcription runs
        before translation in the pipeline, so a language the transcription
        engine can't recognize at all is useless to offer regardless of
        translation engine support. Historically every entry in
        transcription_lang was supported by both local engines (Google/
        Whisper), so this filter was a no-op; Deepgram's language coverage
        genuinely varies by model, so it's the first engine where this
        matters.
        """
        engine = config.SELECTED_TRANSCRIPTION_ENGINE
        transcription_langs = list(transcription_lang.keys())
        translation_langs = []
        for tl_key in translation_lang.keys():
            translation_langs.extend(self.getTranslationLanguagesForEngine(tl_key))
        translation_langs = list(set(translation_langs))
        supported_langs = list(filter(lambda x: x in transcription_langs, translation_langs))

        languages = []
        for language in supported_langs:
            for country in transcription_lang[language]:
                if not self.isLanguageSupportedByTranscriptionEngine(engine, language, country):
                    continue
                languages.append(
                    {
                        "language" : language,
                        "country" : country,
                    }
                )
        languages = sorted(languages, key=lambda x: x['language'])
        return languages

    def isLanguageSupportedByTranscriptionEngine(self, engine: str, language: str, country: str) -> bool:
        """VRCT の (Language, Country) を、指定した文字起こしエンジンが
        対応しているかどうかを返す。

        Google/Whisper/Groq_Whisper/OpenAI_Whisper/Custom_Whisper は
        transcription_lang の全エントリを網羅しているため常に True
        (Groq/OpenAI/カスタムサーバーはローカルWhisperと同じ言語コードを
        使うため)。Deepgram だけは選択中のモデルが実際に申告する対応言語
        一覧と動的に突き合わせる (isLanguageSupportedByDeepgramModel 参照)。
        """
        if language not in transcription_lang or country not in transcription_lang[language]:
            return False
        if engine == "Deepgram":
            model_languages = config.DEEPGRAM_MODEL_LANGUAGES.get(config.SELECTED_DEEPGRAM_MODEL, [])
            return isLanguageSupportedByDeepgramModel(language, country, model_languages)
        return True

    def getTranscriptionLanguagesForEngine(self, engine: str) -> list:
        """指定した文字起こしエンジンが対応する (Language, Country) の一覧。"""
        return [
            {"language": language, "country": country}
            for language, countries in transcription_lang.items()
            for country in countries
            if self.isLanguageSupportedByTranscriptionEngine(engine, language, country)
        ]

    def pickDefaultLanguageAndCountryForTranscriptionEngine(self, engine: str, avoid_languages) -> Optional[dict]:
        """文字起こしエンジンが対応する言語を、日本語→英語の優先順で選ぶ
        (翻訳側の pickDefaultLanguageForEngine と同じ考え方)。`avoid_languages`
        に含まれる言語は避け、他のスロットとの衝突を防ぐ。
        """
        avoid_languages = set(avoid_languages)
        for language, country in (("Japanese", "Japan"), ("English", "United States")):
            if language not in avoid_languages and self.isLanguageSupportedByTranscriptionEngine(engine, language, country):
                return {"language": language, "country": country}
        for entry in self.getTranscriptionLanguagesForEngine(engine):
            if entry["language"] not in avoid_languages:
                return entry
        # このエンジンが対応する言語が既に他スロットで使われている
        return None

    def getTranslationLanguagesForEngine(self, engine: str) -> list[str]:
        """Friendly language names `engine` supports as a source language."""
        if engine == "CTranslate2":
            languages = translation_lang.get(engine, {}).get(config.CTRANSLATE2_WEIGHT_TYPE, {}).get("source", {})
        else:
            languages = translation_lang.get(engine, {}).get("source", {})
        return list(languages.keys())

    def isLanguageSupportedByEngine(self, engine: str, language: str) -> bool:
        return language in self.getTranslationLanguagesForEngine(engine)

    def pickDefaultLanguageForEngine(self, engine: str, avoid_languages) -> dict:
        """Pick a language `engine` supports, preferring Japanese then
        English (the app's own defaults), and avoiding anything in
        `avoid_languages` so the pick can't collide with another slot
        (e.g. resetting the source language to the same value as an
        already-fine enabled target).
        """
        avoid_languages = set(avoid_languages)
        for language, country in (("Japanese", "Japan"), ("English", "United States")):
            if language not in avoid_languages and self.isLanguageSupportedByEngine(engine, language):
                return {"language": language, "country": country}
        for language in self.getTranslationLanguagesForEngine(engine):
            if language not in avoid_languages and language in transcription_lang:
                return {"language": language, "country": next(iter(transcription_lang[language]))}
        # Every language this engine supports is already taken by another
        # slot - nothing to pick that wouldn't collide.
        return None

    def findTranslationEngines(self, source_lang, target_lang, engines_status):
        selectable_engines = [key for key, value in engines_status.items() if value is True]
        compatible_engines = []
        for engine in list(translation_lang.keys()):
            language_list = self.getTranslationLanguagesForEngine(engine)
            source_langs = [e["language"] for e in list(source_lang.values()) if e["enable"] is True]
            target_langs = [e["language"] for e in list(target_lang.values()) if e["enable"] is True]

            if all(e in language_list for e in source_langs) and all(e in language_list for e in target_langs):
                if engine in selectable_engines:
                    compatible_engines.append(engine)

        return compatible_engines

    def addTranslationHistory(self, source: str, text: str) -> None:
        """Add a message to translation context history.
        
        Args:
            source: "chat" | "mic" | "speaker" | "ocr"
            text: message content
        """
        self.ensure_initialized()
        if not text or not text.strip():
            return
        
        history_item = {
            "source": source,
            "text": text.strip(),
            "timestamp": datetime.now().isoformat(),
        }
        self.translation_history.append(history_item)
        
        # 最大件数を超えた場合は古いものを削除
        if len(self.translation_history) > self.translation_history_max_items:
            self.translation_history = self.translation_history[-self.translation_history_max_items:]
    
    def getTranslationHistory(self, max_items: int = None) -> list[dict]:
        """Get recent translation context history.
        
        Args:
            max_items: Maximum number of items to return (newest first)
        
        Returns:
            List of history items
        """
        self.ensure_initialized()
        if max_items is None or max_items <= 0:
            return self.translation_history
        return self.translation_history[-max_items:]
    
    def clearTranslationHistory(self) -> None:
        """Clear all translation context history."""
        self.ensure_initialized()
        self.translation_history = []

    def getTranslate(self, translator_name, source_language, target_language, target_country, message,
                     *, weight_type=None, with_provenance=False):
        self.ensure_initialized()
        success_flag = False
        provenance = "translated"
        weight_type = weight_type if weight_type is not None else config.CTRANSLATE2_WEIGHT_TYPE
        
        # Get context history for LLM-based translators
        history = self.getTranslationHistory()
        
        translation = self.translator.translate(
                        translator_name=translator_name,
                        weight_type=weight_type,
                        source_language=source_language,
                        target_language=target_language,
                        target_country=target_country,
                        message=message,
                        context_history=history
                )

        # LLM は空の応答を返すことがある。空でない文の訳が空なら、訳せなかったとして扱う。
        # 成功扱いにすると、「翻訳後のメッセージのみ送信する」で何も送られず、失敗の通知も出ない
        if isinstance(translation, str) and not translation.strip() and str(message).strip():
            translation = False

        # 翻訳失敗時のフェールセーフ処理
        # translation is None: 選択言語がこのエンジンで未対応（エンジン自体の障害ではない）
        # translation is False: エンジン側の実際の障害（レート制限・通信・認証・プロバイダエラー等）
        if isinstance(translation, str):
            success_flag = True
        else:
            # False = the selected engine itself failed; None = it just
            # doesn't support this language pair.
            primary_failed = translation is False
            max_retries = 20  # 0.1s間隔で最大2秒。CTranslate2が使用不可な場合の無限ループを防ぐ
            for _ in range(max_retries):
                translation = self.translator.translate(
                                    translator_name="CTranslate2",
                                    weight_type=weight_type,
                                    source_language=source_language,
                                    target_language=target_language,
                                    target_country=target_country,
                                    message=message
                            )
                if isinstance(translation, str):
                    break
                if translation is None:
                    break  # CTranslate2もこの言語ペア未対応。リトライしても変わらない
                if not self.translator.isLoadedCTranslate2Model():
                    # 重みが未ロード (未ダウンロード・ロード失敗・切替直後など)。
                    # translateCTranslate2() はこの場合ロックを取った上で即 False を
                    # 返すだけなので、待っても状況は変わらない。ここで抜けないと
                    # 1メッセージあたり 2 秒 (0.1s × 20) を純粋な sleep で捨てる。
                    # getInputTranslate() はターゲット言語ごとにこれを呼ぶため
                    # 3言語で最悪6秒になり、その間パイプラインは単一スレッド
                    # 構造のため文字起こしも止まる。
                    # なお「ロード中」は translateCTranslate2() 側が
                    # _ctranslate2_lock で待たされ、ロード完了後の値を見るため
                    # ここには到達しない (changeCTranslate2Model はロック内で
                    # is_loaded_ctranslate2_model を True にしてから解放する)。
                    break
                sleep(0.1)
            if isinstance(translation, str) and not translation.strip() and str(message).strip():
                translation = False  # 切り替え先の空の訳も、訳せなかったとして扱う
            if isinstance(translation, str):
                success_flag = True
            elif translation is None and not primary_failed:
                # どちらのエンジンもこの言語ペアに未対応なだけ。実障害ではない。
                success_flag = True
                translation = message
                provenance = "unsupported"
            elif translation is None:
                # 選択中のエンジンが実際に失敗し、CTranslate2 も選択中の重みでは
                # この言語ペアに未対応 (例: M2M100 の Basque/Telugu)。以前は
                # 原文を「成功」として黙って流していた。失敗として返すと
                # controller が通知して CTranslate2 へ切り替え、
                # fallbackUnsupportedLanguagesForEngine() が未対応言語を
                # 理由付きでリセットする。
                success_flag = False
                printLog(
                    "Translation failed and CTranslate2 cannot translate this language pair",
                    {"engine": translator_name, "weight_type": weight_type,
                     "source": source_language, "target": target_language},
                )
                translation = message
            else:
                # CTranslate2フォールバック自体が実際に失敗した。
                success_flag = False
                errorLogging()
                translation = message
        if not success_flag:
            provenance = "failed"
        if with_provenance:
            return translation, success_flag, provenance
        return translation, success_flag

    def getInputTranslate(self, message, source_language=None, *, snapshot=None, with_provenance=False):
        self.ensure_initialized()
        if snapshot is not None:
            translator_name = snapshot.engine
            source_language = snapshot.source_language
            target_languages = snapshot.target_languages
        else:
            translator_name = config.SELECTED_TRANSLATION_ENGINES[config.SELECTED_TAB_NO]
            if source_language is None:
                source_language = config.SELECTED_YOUR_LANGUAGES[config.SELECTED_TAB_NO]["1"]["language"]
            target_languages = config.SELECTED_TARGET_LANGUAGES[config.SELECTED_TAB_NO]
        options = {"with_provenance": True} if with_provenance else {}
        if snapshot is not None:
            options["weight_type"] = snapshot.weight_type
        targets = [(value["language"], value["country"]) for value in target_languages.values()
                   if value["enable"] is True]

        if not targets:
            return ([], [], []) if with_provenance else ([], [])

        if len(targets) == 1:
            result = self.getTranslate(
                translator_name, source_language, targets[0][0], targets[0][1], message, **options
            )
            return tuple([item] for item in result)

        # ターゲット言語ごとの翻訳を常設スレッドプールで並列化する。
        # 逐次ループだった頃は3言語有効時に実機で約3.9秒 (1言語あたり
        # 約1.3秒 × 3) かかっていた。翻訳はクラウドエンジンなら
        # ネットワークI/O待ちが支配的なので、概ね1言語分の時間で済む。
        #
        # 1度目の並列化 (73366d0a) は実機でフリーズを起こし取り消した。
        # 原因は translators ライブラリが requests.Session をシングルトンで
        # 使い回しており、スレッドセーフでなかったこと。フォーク側で
        # Tse.session を threading.local() へ分離して解消した
        # (misyaguziya/translators f3697bd)。requirements のpin も追従済み。
        #
        # 使い捨てではなく常設プールなのは、スレッドローカルのセッションを
        # 再利用するため。呼び出しごとにスレッドを作り直すと、毎回
        # ウォームアップ (ホストGET + 言語マップ取得) が走り逆に遅くなる。
        #
        # 添字はターゲット言語スロットに対応するので、完了順ではなく
        # 投入順に結果を取る。例外は最初の1件をそのまま送出する
        # (呼び出し元の _processMessage が VRAM不足エラーを検出する契約)。
        futures = [
            self._translation_executor.submit(
                self.getTranslate,
                translator_name, source_language, target_language, target_country, message, **options,
            )
            for target_language, target_country in targets
        ]
        results = [future.result() for future in futures]

        return tuple([result[i] for result in results] for i in range(3 if with_provenance else 2))

    def getOutputTranslate(self, message, source_language=None, *, snapshot=None, with_provenance=False):
        self.ensure_initialized()
        if snapshot is not None:
            translator_name = snapshot.engine
            source_language = snapshot.source_language
            target = snapshot.your_languages["1"]
        else:
            translator_name = config.SELECTED_TRANSLATION_ENGINES[config.SELECTED_TAB_NO]
            if source_language is None:
                source_language = config.SELECTED_TARGET_LANGUAGES[config.SELECTED_TAB_NO]["1"]["language"]
            target = config.SELECTED_YOUR_LANGUAGES[config.SELECTED_TAB_NO]["1"]
        options = {"with_provenance": True} if with_provenance else {}
        if snapshot is not None:
            options["weight_type"] = snapshot.weight_type
        result = self.getTranslate(
            translator_name, source_language, target["language"], target["country"], message, **options)
        return tuple([item] for item in result)

    def addKeywords(self):
        self.ensure_initialized()
        for f in config.MIC_WORD_FILTER:
            self.keyword_processor.add_keyword(f)

    def checkKeywords(self, message):
        self.ensure_initialized()
        return len(self.keyword_processor.extract_keywords(message)) != 0

    def detectRepeatSendMessage(self, message):
        repeat_flag = self.previous_send_message == message
        self.previous_send_message = message
        return repeat_flag

    def detectRepeatReceiveMessage(self, message):
        repeat_flag = self.previous_receive_message == message
        self.previous_receive_message = message
        return repeat_flag

    def startTransliteration(self):
        self.ensure_initialized()
        if self.transliterator is None:
            self.transliterator = Transliterator()

    def stopTransliteration(self):
        self.ensure_initialized()
        if self.transliterator is not None:
            self.transliterator = None

    def convertMessageToTransliteration(self, message: str, hiragana: bool=True, romaji: bool=True) -> list:
        self.ensure_initialized()
        if hiragana is False and romaji is False:
            return []

        keys_to_keep = {"orig"}
        if hiragana:
            keys_to_keep.add("hira")
        if romaji:
            keys_to_keep.add("hepburn")

        # An admitted message may still need readings after the live switch is off.
        # Keep a local owner so stopTransliteration cannot clear it mid-call.
        transliterator = self.transliterator
        if transliterator is None:
            transliterator = Transliterator()

        data_list = transliterator.analyze(message, use_macron=False)
        filtered_list = [
            {key: value for key, value in item.items() if key in keys_to_keep}
            for item in data_list
        ]
        return filtered_list

    def setOscIpAddress(self, ip_address):
        self.ensure_initialized()
        self.osc_handler.setOscIpAddress(ip_address)

    def setOscPort(self, port):
        self.ensure_initialized()
        self.osc_handler.setOscPort(port)

    def oscStartSendTyping(self):
        self.ensure_initialized()
        self.osc_handler.sendTyping(flag=True)

    def oscStopSendTyping(self):
        self.ensure_initialized()
        self.osc_handler.sendTyping(flag=False)

    def oscSendMessage(self, message:str):
        self.ensure_initialized()
        self.osc_handler.sendMessage(message=message, notification=config.NOTIFICATION_VRC_SFX)

    def setMuteSelfStatus(self):
        self.ensure_initialized()
        with self._mute_status_lock:
            self._mute_status_generation += 1
            generation = self._mute_status_generation
        mute = self.osc_handler.getOSCParameterMuteSelf()
        with self._mute_status_lock:
            if generation == self._mute_status_generation and type(mute) is bool:
                self.mic_mute_status = mute
                if mute and config.VRC_MIC_MUTE_SYNC is True:
                    self.message_delivery.revoke("mic")

    def setMicMuteStatusChangeCallback(self, fn: Optional[Callable[[], None]]) -> None:
        """OSC ミュート同期が pause()/resume() を実行する際に呼ぶ関数を登録する。

        Controller.__init__ が自身の mic_lifecycle_lock を取得する
        ラッパー (_changeMicTranscriptStatusLocked) を登録することで、
        OSC 受信スレッド発の pause()/resume() を他の全ての start/stop 系
        (mainloop ワーカーが直接呼ぶ startTranscriptionSendMessage 等も含む)
        と完全に排他制御する。未登録なら changeMicTranscriptStatus() を直接
        使う (Controller を経由しないテスト等でも壊れないようにするため)。
        """
        self.mic_mute_status_change_callback = fn

    def startReceiveOSC(self):
        self.ensure_initialized()
        with self._mute_status_lock:
            self._mute_status_generation += 1

        def changeHandlerMute(address, osc_arguments):
            # OSC の受信スレッド (osc.py の oscServerServe) で走る。受信を止めないよう、
            # ここで待つ処理をしないこと。
            # changeMicTranscriptStatus() を直接ここで呼ぶと、Auto Mic
            # Select のデバイス切替や mainloop ワーカーが直接呼ぶ
            # start/stop 系 (_stop()/_start() を実行中) と
            # _mic_session.pause()/resume() が無ロックで交錯し得る
            # (ミュート連打中にデバイスが切り替わると壊れた Recorder に
            # 触れる)。mic_lifecycle_worker.enqueue() で Auto Select の
            # 他のデバイス操作と同じ FIFO キューに直列化しつつ、実行される
            # 関数自体は mic_mute_status_change_callback (= Controller の
            # mic_lifecycle_lock 付きラッパー) にすることで、ロックを直接
            # 取得する経路とも完全に排他制御する。
            if config.VRC_MIC_MUTE_SYNC is True:
                with self._mute_status_lock:
                    if osc_arguments is True:
                        # 重複した true も、それ以前に始まった解除確認を無効にする。
                        self._mute_status_generation += 1
                        if self.mic_mute_status is not True:
                            self.mic_mute_status = True
                            # Revoke delivery now; pause may wait in the lifecycle queue.
                            self.message_delivery.revoke("mic")
                            self.mic_lifecycle_worker.enqueue(
                                self.mic_mute_status_change_callback or self.changeMicTranscriptStatus
                            )
                    elif osc_arguments is False and self.mic_mute_status is True:
                        # UDP の false だけでは解除しない。連続する通知は1件の確認にまとめる。
                        pending = self._mute_verification_pending
                        self._mute_verification_pending = self._mute_status_generation
                        if pending is None:
                            self._avatar_query_executor.submit(verifyUnmute, self._mute_status_generation)

        def verifyUnmute(generation):
            try:
                with self._mute_status_lock:
                    if config.VRC_MIC_MUTE_SYNC is not True or generation != self._mute_status_generation:
                        return
                mute = self.osc_handler.getOSCParameterMuteSelf()
                if mute is not False:
                    printLog("OSC: unmute not confirmed by OSCQuery; keeping microphone muted")
                    return
                with self._mute_status_lock:
                    if (config.VRC_MIC_MUTE_SYNC is not True
                            or generation != self._mute_status_generation
                            or self.mic_mute_status is not True):
                        return
                    self._mute_status_generation += 1
                    self.mic_mute_status = False
                    self.mic_lifecycle_worker.enqueue(
                        self.mic_mute_status_change_callback or self.changeMicTranscriptStatus
                    )
            except Exception:
                printLog("OSC: unmute verification failed; keeping microphone muted")
            finally:
                with self._mute_status_lock:
                    pending = self._mute_verification_pending
                    if (pending != generation and pending == self._mute_status_generation
                            and config.VRC_MIC_MUTE_SYNC is True and self.mic_mute_status is True):
                        # 確認中に true → false が届いたなら、最後の false を新しく確認する。
                        # 古い問い合わせの false をそのまま採用してはいけない。
                        self._avatar_query_executor.submit(verifyUnmute, pending)
                    else:
                        self._mute_verification_pending = None

        def changeHandlerAvatar(address, *osc_arguments):
            # アバターを読み込んだ (VRChat の起動・再起動・アバター変更)。ミュートの状態はアバターの
            # パラメータなので、読み込むまで OSCQuery に無い (VRChat が現れた直後の問い合わせは 404)。
            # ここで読み直して同期する。VRCT を先に起動した場合も、ここで初めて状態が決まる。
            # 問い合わせは専用のスレッドで行う (OSC の受信スレッドもマイクのキューも HTTP の待ちで止めない)
            if config.VRC_MIC_MUTE_SYNC is not True:
                return
            with self._mute_status_lock:
                self._avatar_query_executor.submit(syncMuteSelfAfterAvatarLoad, self._mute_status_generation)

        def syncMuteSelfAfterAvatarLoad(generation):
            try:  # executor の中の例外は黙って捨てられるので記録する
                mute = self.osc_handler.getOSCParameterMuteSelf()
                printLog("OSC: MuteSelf read on avatar change", {"mute": mute})
                if type(mute) is not bool:
                    return
                with self._mute_status_lock:
                    if (config.VRC_MIC_MUTE_SYNC is not True
                            or generation != self._mute_status_generation
                            or mute == self.mic_mute_status):
                        return
                    self._mute_status_generation += 1
                    self.mic_mute_status = mute
                    if mute:
                        self.message_delivery.revoke("mic")
                    self.mic_lifecycle_worker.enqueue(
                        self.mic_mute_status_change_callback or self.changeMicTranscriptStatus
                    )
            except Exception:
                errorLogging()

        dict_filter_and_target = {
            self.osc_handler.osc_parameter_muteself: changeHandlerMute,
            "/avatar/change": changeHandlerAvatar,
        }
        self.osc_handler.setDictFilterAndTarget(dict_filter_and_target)
        self.osc_handler.receiveOscParameters()

    def stopReceiveOSC(self):
        """OSC受信サーバ(UDP + OSCQuery HTTP + zeroconf監視)を停止する。

        アプリ終了時(Controller.shutdown())専用の呼び出し口。
        setOscIpAddress()/setOscPort()は再起動のため内部で直接
        osc_handler.oscServerStop()を呼んでおり、このメソッドは経由しない。
        以前はアプリ終了時にこれらを止める経路が無く(フェーズ3項目21で一度
        「未使用」と判断され削除された`stopReceiveOSC`とは別の、実際に
        呼ばれる経路として再設置)、OSCQueryのzeroconfサービス広告が
        `close()`されないままプロセスが終了していた(バックエンドレビュー
        フェーズ4項目30)。
        """
        self.ensure_initialized()
        with self._mute_status_lock:
            self._mute_status_generation += 1
        self.osc_handler.oscServerStop()

    def getIsOscQueryEnabled(self):
        self.ensure_initialized()
        return self.osc_handler.getIsOscQueryEnabled()

    @staticmethod
    def _isVersionSupported(version_str: str) -> bool:
        # Releases older than MIN_SUPPORTED_VERSION stay out of both the
        # update-check comparison and the version picker. Compare release
        # numbers only so X.Y.Z-beta.N (which sorts below X.Y.Z) still counts.
        try:
            return parse(version_str).release >= parse(config.MIN_SUPPORTED_VERSION).release
        except Exception:
            return False

    @staticmethod
    def _fetchGithubReleases() -> list:
        # All releases (including prereleases), newest first, drafts excluded.
        # timeout 無しだと GitHub 側が「接続はするが応答しない」状態になった
        # 場合に無期限にブロックし、これを呼ぶ checkSoftwareUpdated() は
        # Controller.init() から呼ばれるため、初期化そのものが固まる。
        response = requests_get(config.GITHUB_RELEASES_LIST_URL, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
        releases = response.json()
        if not isinstance(releases, list):
            return []
        return [r for r in releases if isinstance(r, dict) and not r.get("draft", False)]

    @staticmethod
    def checkSoftwareUpdated():
        if not config.BUILTIN_UPDATER_ENABLED:
            return {"is_update_available": False, "new_version": ""}
        # check update
        update_flag = False
        version = ""
        try:
            if config.SELECTED_RELEASE_CHANNEL == "beta":
                # beta を使っている間は beta 同士でのみ最新判定する。
                # ここで prerelease を絞らないと、GitHub の公開順(作成日時順)
                # によっては後から出た stable 版が候補[0]に来てしまい、
                # betaユーザーにstableへの「更新あり」通知が出てしまう。
                candidates = [
                    r["name"] for r in Model._fetchGithubReleases()
                    if isinstance(r.get("name"), str) and Model._isVersionSupported(r["name"])
                    and r.get("prerelease", False)
                ]
                version = candidates[0] if candidates else None
            else:
                response = requests_get(config.GITHUB_URL, timeout=_HTTP_TIMEOUT)
                json_data = response.json()
                version = json_data.get("name", None)
            if isinstance(version, str):
                new_version = parse(version)
                current_version = parse(config.VERSION)
                if new_version > current_version:
                    update_flag = True
        except Exception:
            errorLogging()
        return {
            "is_update_available": update_flag,
            "new_version": version,
        }

    @staticmethod
    def listAvailableReleases() -> list:
        if not config.BUILTIN_UPDATER_ENABLED:
            return []
        # Version picker data source: all supported (>= MIN_SUPPORTED_VERSION)
        # releases across both channels, newest first.
        result = []
        try:
            for r in Model._fetchGithubReleases():
                version = r.get("name")
                tag = r.get("tag_name")
                if not isinstance(version, str) or not isinstance(tag, str):
                    continue
                if not Model._isVersionSupported(version):
                    continue
                result.append(ReleaseInfo(
                    tag=tag,
                    version=version,
                    is_prerelease=bool(r.get("prerelease", False)),
                    published_at=str(r.get("published_at", "")),
                ))
        except Exception:
            errorLogging()
        return result

    # setup.exe と一緒に CI が公開する SHA-256 サイドカーアセットのファイル名
    # サフィックス。release.yml 側で <installer名>.sha256 という名前で
    # 追加アップロードしている前提。
    _SHA256_ASSET_SUFFIX = ".sha256"
    # ".sha256" サイドカー (数十バイトの小さなファイル) の取得リトライ回数。
    # これ1つの一時的な通信失敗で更新全体を止めてしまわないための保険。
    # setup.exe 本体の _downloadSetup (5回) より軽い処理なので控えめに3回。
    _SHA256_SIDECAR_ATTEMPTS = 3

    @staticmethod
    def _resolveReleaseForVersion(target_version: Optional[str] = None) -> Optional[dict]:
        # target_version (完全なバージョン文字列) に対応する GitHub Release
        # オブジェクト (assets を含む) を返す。target_version が None の
        # 場合は checkSoftwareUpdated() と同じロジックで、現在の
        # SELECTED_RELEASE_CHANNEL における最新版の Release を返す。
        # 見つからない/取得失敗の場合は None。
        try:
            if target_version is not None:
                for r in Model._fetchGithubReleases():
                    if r.get("name") == target_version:
                        return r
                return None
            if config.SELECTED_RELEASE_CHANNEL == "beta":
                # checkSoftwareUpdated() と同じ理由で prerelease のみに限定。
                candidates = [
                    r for r in Model._fetchGithubReleases()
                    if isinstance(r.get("name"), str) and Model._isVersionSupported(r["name"])
                    and r.get("prerelease", False)
                ]
                return candidates[0] if candidates else None
            response = requests_get(config.GITHUB_URL, timeout=_HTTP_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            errorLogging()
            return None

    @staticmethod
    def _fetchExpectedSha256(release: Optional[dict]) -> Optional[str]:
        # release の assets から "<setup.exe名>.sha256" というサイドカー
        # アセットを探し、中身 (16進ダイジェスト文字列) を取得して返す。
        #
        # 戻り値の意味:
        #   - digest 文字列 : 期待する SHA-256 が取れた
        #   - None          : この release には ".sha256" アセットが存在しない
        #                     (この検証より前に公開された古い release)。呼び出し
        #                     側はサイズチェックのみへフォールバックしてよい。
        #                     古いバージョンの再インストール/ダウングレードを
        #                     壊さないための措置。
        # 例外 SetupSha256Unavailable:
        #   ".sha256" アセットは存在するのに、リトライしても有効なダイジェスト
        #   を取得できなかった。「検証対象が無い」のとは異なり、すり替えの
        #   可能性を排除できないため、呼び出し側は更新を中止する。
        if not isinstance(release, dict):
            return None
        assets = release.get("assets")
        if not isinstance(assets, list):
            return None
        sidecar_urls = [
            asset["browser_download_url"]
            for asset in assets
            if isinstance(asset, dict)
            and isinstance(asset.get("name"), str)
            and asset["name"].endswith(Model._SHA256_ASSET_SUFFIX)
            and isinstance(asset.get("browser_download_url"), str)
        ]
        if not sidecar_urls:
            return None
        for url in sidecar_urls:
            digest = Model._fetchSha256Digest(url)
            if digest is not None:
                return digest
        raise SetupSha256Unavailable(
            f"{len(sidecar_urls)} '.sha256' sidecar asset(s) present on the "
            "release but none yielded a valid SHA-256 digest after retrying"
        )

    @staticmethod
    def _fetchSha256Digest(url: str) -> Optional[str]:
        # ".sha256" は数十バイトの小さなファイルだが、これ1つの一時的な
        # 取得失敗で更新全体を止めてしまわないよう _SHA256_SIDECAR_ATTEMPTS
        # 回リトライする。有効な16進ダイジェスト (64桁) が取れなければ None。
        # レスポンスは得られたが中身がチェックサムでない (空 / 途中で切れた /
        # HTML エラーページ等) 場合も失敗扱いでリトライする。
        for _ in range(Model._SHA256_SIDECAR_ATTEMPTS):
            try:
                res = requests_get(url, timeout=_HTTP_TIMEOUT)
                res.raise_for_status()
                digest = res.text.strip().split()[0].lower()
                if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                    return digest
            except Exception:
                errorLogging()
        return None

    @staticmethod
    def _downloadSetup(expected_sha256: Optional[str] = None, url: Optional[str] = None) -> Optional[str]:
        # try to download at most 5 times
        # 戻り値: 成功なら None、失敗なら SETUP_DOWNLOAD_FAILED / SETUP_VERIFY_FAILED
        url = url or config.setupDownloadUrl()
        program_name = "VRCT-VOX_setup.exe"
        current_directory = config.PATH_LOCAL
        dest_path = os_path.join(current_directory, program_name)
        # minimum plausible size for a real NSIS installer; guards against
        # saving/executing a short HTML error page as the installer
        min_valid_size = 1024 * 1024
        for _ in range(5):
            try:
                res = requests_get(url, stream=True, timeout=_HTTP_TIMEOUT)
                res.raise_for_status()
                downloaded_size = 0
                hasher = hashlib.sha256()
                with open(dest_path, 'wb') as file:
                    for chunk in res.iter_content(chunk_size=1024*5):
                        file.write(chunk)
                        hasher.update(chunk)
                        downloaded_size += len(chunk)
                if downloaded_size < min_valid_size:
                    raise ValueError(f"Downloaded setup file is too small ({downloaded_size} bytes); likely not a valid installer")
                if expected_sha256 is not None:
                    actual_sha256 = hasher.hexdigest()
                    if actual_sha256 != expected_sha256:
                        # ハッシュ不一致は改ざん/破損の疑いであり、通信起因
                        # の一時的な失敗とは性質が異なる (同じレスポンスを
                        # 再試行しても無意味、あるいは攻撃者に汚染された
                        # 配信元を再度信頼することになりかねない) ため、
                        # リトライループには乗せず即座に失敗として扱う。
                        printLog(
                            "Setup file SHA-256 mismatch: expected "
                            f"{expected_sha256}, got {actual_sha256}. Aborting update."
                        )
                        try:
                            os_remove(dest_path)
                        except Exception:
                            errorLogging()
                        return SETUP_VERIFY_FAILED
                return None
            except Exception:
                errorLogging()
                try:
                    if os_path.exists(dest_path):
                        os_remove(dest_path)
                except Exception:
                    errorLogging()
        return SETUP_DOWNLOAD_FAILED

    @staticmethod
    def _downloadVerifiedSetup(target_version: Optional[str]) -> Optional[str]:
        # GitHub Release を解決して期待する SHA-256 を求め、setup.exe を
        # ダウンロード & 検証する。updateSoftware()/updateCudaSoftware() の
        # 共通前処理。
        #
        # 戻り値 None : VRCT-VOX_setup.exe がディスク上にあり起動して問題ない
        # 戻り値 str  : 呼び出し側は何も起動せず中止すること。失敗の種類は
        #   - SETUP_VERIFY_FAILED   : ハッシュが一致しなかった、または ".sha256" が
        #     公開されているのに取得できなかった (SetupSha256Unavailable)。
        #     サイズチェックのみへは格下げしない
        #   - SETUP_DOWNLOAD_FAILED : 取得できなかった
        release = Model._resolveReleaseForVersion(target_version)
        try:
            expected_sha256 = Model._fetchExpectedSha256(release)
        except SetupSha256Unavailable:
            printLog(
                "Setup file SHA-256 sidecar was published for "
                f"{target_version or 'the latest release'} but could not be "
                "retrieved; aborting update (not falling back to size-only "
                "validation)"
            )
            return SETUP_VERIFY_FAILED
        if expected_sha256 is None:
            printLog(
                "Setup file SHA-256 could not be verified (no .sha256 asset found for "
                f"{target_version or 'the latest release'}); falling back to size-only validation"
            )

        # 指定バージョンはforkの対応GitHub tagから取得する。
        # 別版のfloating installerへはフォールバックしない。
        urls = [config.setupDownloadUrl()]
        if target_version:
            tag = release.get("tag_name") if isinstance(release, dict) else None
            urls = [config.setupDownloadUrl(target_version, tag=tag or f"v{target_version}")]
        failure = SETUP_DOWNLOAD_FAILED
        for url in urls:
            failure = Model._downloadSetup(expected_sha256, url)
            if failure != SETUP_DOWNLOAD_FAILED:
                return failure
        return failure

    @staticmethod
    def _updateAndRestart(edition: str, target_version: Optional[str]) -> str:
        if not config.BUILTIN_UPDATER_ENABLED:
            return SETUP_DOWNLOAD_FAILED
        # 起動して終了する (_quitApp) ので、本番で戻るのは失敗したときだけ。
        # 呼び出し側 (Controller) が失敗の種類を UI へ知らせる。SETUP_LAUNCHED を
        # 返すのはテストなどで終了処理を差し替えたとき。
        if target_version is not None and not Model._isVersionSupported(target_version):
            return SETUP_DOWNLOAD_FAILED
        failure = Model._downloadVerifiedSetup(target_version)
        if failure is not None:
            return failure
        # run the NSIS setup wizard, preselecting the given edition; pin to
        # target_version when the user picked a specific release to install;
        # carry over the current UI language so the installer chrome and the
        # custom "UI Language" page start on the user's chosen language;
        # the installer's channel page defaults to the channel of the version
        # being installed (or the current channel when installing the latest).
        # The channel is not saved to config here: if the installer is cancelled,
        # VRCT keeps running on its current version and channel.
        channel = config._channelForVersion(target_version) if target_version else config.SELECTED_RELEASE_CHANNEL
        args = ["VRCT-VOX_setup.exe", f"/EDITION={edition}", f"/UILANG={config.UI_LANGUAGE}", f"/CHANNEL={channel}"]
        if target_version:
            args.append(f"/VERSION={target_version}")
        Popen(args, cwd=config.PATH_LOCAL)
        Model._quitApp()
        return SETUP_LAUNCHED

    @staticmethod
    def updateSoftware(target_version: Optional[str] = None) -> str:
        return Model._updateAndRestart("cpu", target_version)

    @staticmethod
    def updateCudaSoftware(target_version: Optional[str] = None) -> str:
        return Model._updateAndRestart("gpu", target_version)

    @staticmethod
    def _quitApp():
        # The setup wizard's own running-process check can only kill VRCT
        # silently or prompt the user for it; quit proactively here so the
        # app always closes as soon as the wizard has been launched, whether
        # this was a version update or a CPU/GPU switch.
        try:
            psutil_Process(os_getppid()).terminate()
        except Exception:
            errorLogging()
        finally:
            os_exit(0)

    def getListMicHost(self):
        self.ensure_initialized()
        try:
            dm = device_manager.getMicDevices()
            result = [host for host in dm.keys()]
        except Exception:
            errorLogging()
            result = []
        return result

    def getMicDefaultDevice(self):
        self.ensure_initialized()
        try:
            dm = device_manager.getMicDevices()
            result = dm.get(config.SELECTED_MIC_HOST, [{"name": "NoDevice"}])[0]["name"]
        except Exception:
            errorLogging()
            result = "NoDevice"
        return result

    def getListMicDevice(self):
        self.ensure_initialized()
        try:
            dm = device_manager.getMicDevices()
            result = [device["name"] for device in dm.get(config.SELECTED_MIC_HOST, [{"name": "NoDevice"}])]
        except Exception:
            errorLogging()
            result = ["NoDevice"]
        return result

    def getListSpeakerDevice(self):
        self.ensure_initialized()
        try:
            sd = device_manager.getSpeakerDevices()
            result = [device["name"] for device in sd]
        except Exception:
            errorLogging()
            result = ["NoDevice"]
        return result

    def startMicTranscript(self, fnc) -> bool:
        self.ensure_initialized()
        self._mic_session.transcript_fnc = fnc
        self._mic_session.reconfigure(transcript=True)
        if "transcript" in self._mic_session.features:
            self.changeMicTranscriptStatus()
            return True
        return False

    def resumeMicTranscript(self):
        self.ensure_initialized()
        self._mic_session.resume()

    def pauseMicTranscript(self):
        self.ensure_initialized()
        self._mic_session.pause()

    # VRAM 不足エラーを検出するメソッドを追加
    def detectVRAMError(self, error):
        error_str = str(error)
        if isinstance(error, ValueError) and len(error.args) > 0 and error.args[0] == "VRAM_OUT_OF_MEMORY":
            return True, error.args[1] if len(error.args) > 1 else "VRAM out of memory"
        if "CUDA out of memory" in error_str or "CUBLAS_STATUS_ALLOC_FAILED" in error_str:
            return True, error_str
        return False, None

    def changeMicTranscriptStatus(self):
        if config.VRC_MIC_MUTE_SYNC is True:
            match self.mic_mute_status:
                case True:
                    self.pauseMicTranscript()
                case False:
                    self.resumeMicTranscript()
                case None:
                    # mute selfの状態が不明な場合は一時停止しない
                    self.resumeMicTranscript()
                case _:
                    pass
        else:
            self.resumeMicTranscript()

    def stopMicTranscript(self):
        self.ensure_initialized()
        self._mic_session.reconfigure(transcript=False)

    def stopCaptureForRealtime(self, source: str) -> bool:
        self.ensure_initialized()
        if source not in ("mic", "speaker"):
            raise ValueError("realtime_source_invalid")
        return getattr(self, "_" + source + "_session").stop_for_handoff()

    def startCheckMicEnergy(self, fnc:Optional[Callable[[float], None]]=None) -> bool:
        self.ensure_initialized()
        # fnc may be None or a callable. Use cast after checking for None to satisfy type checker.
        if fnc is not None:
            self._mic_session.energy_fnc = cast(Callable[[float], None], fnc)
        self._mic_session.reconfigure(energy=True)
        return "energy" in self._mic_session.features and self._mic_session._recorder is not None

    def stopCheckMicEnergy(self):
        self.ensure_initialized()
        self._mic_session.reconfigure(energy=False)

    def startSpeakerTranscript(self, fnc:Optional[Callable[[dict], None]]=None) -> bool:
        self.ensure_initialized()
        self._speaker_session.transcript_fnc = fnc
        self._speaker_session.reconfigure(transcript=True)
        return "transcript" in self._speaker_session.features

    def stopSpeakerTranscript(self):
        self.ensure_initialized()
        self._speaker_session.reconfigure(transcript=False)

    def startOCRCapture(self, fnc: Callable[[dict], None], model_root=None) -> bool:
        """Start the VRChat chat-bubble OCR pipeline.

        The callback receives dicts shaped like mic/speaker transcripts so
        Controller.ocrMessage can share the mic/speaker translation path.
        model_root is the consented-download directory holding the PP-OCR
        models (Controller.model_downloads.root).
        Returns True once the pipeline started (models loaded). Raises
        OcrStartError carrying the OCR_DISABLED_* reason when it cannot start.
        """
        if self._ocr_shutdown_requested:
            return False
        self.ensure_initialized()
        with self._ocr_lifecycle_lock:
            if self._ocr_shutdown_requested:
                return False
            if isinstance(self.ocr_pipeline, OcrPipeline):
                if self.ocr_pipeline.is_alive:
                    # False when the previous stop is still waiting for cleanup.
                    return self.ocr_pipeline.start()

            # 読み取る言語の扱いは models/ocr/ocr_languages.py を参照。
            # "auto" は PP-OCRv6 small (日英中+ラテン文字系を1モデル) を使い、
            # ハングル・キリル・タイ・アラビア・デーヴァナーガリーだけ明示選択で
            # PP-OCRv5 のスクリプト別モデルへ切り替える。未対応なら起動しない。
            # 以前 auto を SELECTED_TARGET_LANGUAGES から解決していた頃は、
            # 日本語話者が英語へ翻訳する設定だと日本語の吹き出しが読めなかった。
            source_language = config.OCR_SOURCE_LANGUAGE
            if not isSupportedOcrLanguage(source_language):
                printLog(f"OCR: source language {source_language!r} is not selected or not supported, refusing to start")
                raise OcrStartError(ErrorCode.OCR_DISABLED_UNSUPPORTED_LANGUAGE)

            # VRCT-VOX's own chatbox detector, only from its hash-verified download.
            self._ocr_model_root = model_root
            detector = self._ocrChatboxDetector()
            try:
                self.ocr_pipeline = OcrPipeline(
                    callback=fnc,
                    source_language=source_language,
                    window_title=config.OCR_WINDOW_TITLE,
                    poll_interval_ms=config.OCR_POLL_INTERVAL_MS,
                    min_confidence=config.OCR_MIN_CONFIDENCE,
                    min_text_length=config.OCR_BUBBLE_MIN_TEXT_LENGTH,
                    model_root=model_root,
                    region=config.OCR_CAPTURE_REGION,
                    chatbox_filter=config.OCR_CHATBOX_FILTER,
                    detector=detector,
                    activation_ready=lambda: config.ENABLE_OCR_CAPTURE is True,
                )
                # Queue before start: the worker applies both source regions before
                # its first capture. No window coordinates can leak into VR.
                self.ocr_pipeline.applyConfig({"regions": {
                    "window": config.OCR_CAPTURE_REGION,
                    "vr": config.OCR_VR_CAPTURE_REGION,
                }})
                self._ocr_detector_path = getattr(detector, "model_path", None)
                # Shutdown may have raced construction before publication.
                if self._ocr_shutdown_requested:
                    self.ocr_pipeline.requestShutdown()
                    return False
                return self.ocr_pipeline.start()
            except Exception:
                self.ocr_pipeline = None
                raise

    def getOCRRuntime(self) -> dict:
        """Read worker state without probing capture, loading models or changing settings."""
        pipeline = getattr(self, "ocr_pipeline", None)
        if isinstance(pipeline, OcrPipeline) and pipeline.is_alive:
            return pipeline.runtimeStatus
        return {"state": "stopped", "stage": None, "error_code": None, "detector": None}

    def _ocrChatboxDetector(self):
        """The chatbox detector to read with, or None for detector-free reading.

        Used when the switch is on and the download is present and verified.
        """
        if config.OCR_USE_CHATBOX_DETECTOR is not True:
            return None
        return buildChatboxDetector(getattr(self, "_ocr_model_root", None))

    def setOCRSourceLanguage(self, language: str, model_root=None) -> bool:
        """While active, validate and load before saving; the worker only swaps readers.

        Serialize with start/stop so a new pipeline cannot start on the old
        setting while this request is preparing its reader. Never download.
        """
        if self._ocr_shutdown_requested:
            return False
        with self._ocr_lifecycle_lock:
            if self._ocr_shutdown_requested:
                return False
            spec = resolveModelSpec(language)
            if spec is None:
                raise OcrStartError(ErrorCode.OCR_DISABLED_UNSUPPORTED_LANGUAGE)
            pipeline = getattr(self, "ocr_pipeline", None)
            active = isinstance(pipeline, OcrPipeline) and pipeline.is_alive
            if not active:
                # The download list follows the selected language, so a stopped
                # pipeline accepts it; missing files are reported at start.
                config.OCR_SOURCE_LANGUAGE = language
                return True
            try:
                files = resolveModelFiles(model_root, spec)
                reader = ocr_engine.getReader(spec, files)
                if reader is None:
                    raise OcrStartError(ErrorCode.OCR_DISABLED_MODEL_LOAD_FAILED)
            except OcrModelsMissing:
                raise OcrStartError(ErrorCode.OCR_DISABLED_MODEL_MISSING)
            except OcrStartError:
                raise
            except Exception:
                errorLogging()
                raise OcrStartError(ErrorCode.OCR_DISABLED_MODEL_LOAD_FAILED)
            if self._ocr_shutdown_requested:
                return False
            config.OCR_SOURCE_LANGUAGE = language
            pipeline.applyLanguage(language, reader)
            return True

    def updateOCRCaptureSettings(self) -> None:
        """設定変更を実行中のOCRパイプラインへ渡す。停止中なら何もしない。

        OFF→ONを挟まずにしきい値などを切り替える。言語は専用のsetterで扱う。
        """
        # Endpoint locks are separate. Keep snapshot, detector selection (including
        # its remembered path), and enqueue ordered together across all endpoints
        # and start/stop. A later request must never queue an older region last.
        with self._ocr_lifecycle_lock:
            pipeline = self.ocr_pipeline
            if self._ocr_shutdown_requested or not isinstance(pipeline, OcrPipeline):
                return
            try:
                pipeline.applyConfig({
                    "window_title": config.OCR_WINDOW_TITLE,
                    "poll_interval_ms": config.OCR_POLL_INTERVAL_MS,
                    "min_confidence": config.OCR_MIN_CONFIDENCE,
                    "min_text_length": config.OCR_BUBBLE_MIN_TEXT_LENGTH,
                    "regions": {
                        "window": config.OCR_CAPTURE_REGION,
                        "vr": config.OCR_VR_CAPTURE_REGION,
                    },
                    "chatbox_filter": config.OCR_CHATBOX_FILTER,
                    **self._ocrDetectorChange(),
                })
            except Exception:
                errorLogging()

    def _ocrDetectorChange(self) -> dict:
        """{"detector": ...} when the detector to use differs from the running one."""
        detector = self._ocrChatboxDetector()
        path = getattr(detector, "model_path", None)
        if path == getattr(self, "_ocr_detector_path", None):
            return {}
        self._ocr_detector_path = path
        return {"detector": detector}

    def requestOCRShutdown(self) -> None:
        """Close admission and signal the worker without a blocking lock/join."""
        self._ocr_shutdown_requested = True
        pipeline = getattr(self, "ocr_pipeline", None)
        if isinstance(pipeline, OcrPipeline):
            pipeline.requestShutdown()

    def stopOCRCapture(self) -> None:
        with self._ocr_lifecycle_lock:
            pipeline = getattr(self, "ocr_pipeline", None)
            if isinstance(pipeline, OcrPipeline):
                try:
                    if pipeline.stop() is False:
                        return
                except Exception:
                    errorLogging()
                    return
            self.ocr_pipeline = None
            # 明示 gc.collect() は呼ばない: この関数は Controller から別スレッドで
            # 呼ばれる。同じ理由 (comtypes の COM ポインタが CoInitialize していない
            # スレッドで Release され access violation になる、_print_transcript の
            # コメント参照) で禁止している。gc は import されておらず、ここは
            # NameError になって stopOcrCapture スレッドが毎回落ちていた
            # (2026-09-18 実機のstderrで発覚)。

    def startCheckSpeakerEnergy(self, fnc:Optional[Callable[[float], None]]=None) -> bool:
        self.ensure_initialized()
        # Accept None as default and assign safely with cast after None-check
        if fnc is not None:
            self._speaker_session.energy_fnc = cast(Callable[[float], None], fnc)
        self._speaker_session.reconfigure(energy=True)
        return "energy" in self._speaker_session.features and self._speaker_session._recorder is not None

    def stopCheckSpeakerEnergy(self):
        self.ensure_initialized()
        self._speaker_session.reconfigure(energy=False)

    def reconfigureMicDevice(self, device: Optional[dict] = None) -> None:
        """稼働中の Mic Session を新デバイスに差し替える。

        features (transcript/energy) は現状維持。device が None の場合は
        config (SELECTED_MIC_HOST/DEVICE) から解決する。Session 内部で
        差分検知するため、同一デバイスなら no-op になる。

        マイク側は ActiveEndpointTracker (peak 追従) を使わないため
        (device_manager.setMicAutoActive の docstring 参照)、
        pauseMicEndpointTracker/resumeMicEndpointTracker は現状常に no-op。
        speaker 側との対称性のため呼び出しは残す (将来マイク peak 追従を
        復活させた場合の COM デッドロック回避策として機能する)。
        """
        self.ensure_initialized()
        device_manager.pauseMicEndpointTracker()
        try:
            self._mic_session.reconfigure(device=device)
        finally:
            device_manager.resumeMicEndpointTracker()

    def reconfigureSpeakerDevice(self, device: Optional[dict] = None) -> None:
        """稼働中の Speaker Session を新デバイスに差し替える。
        features / device 解決 / 差分検知の扱いは reconfigureMicDevice と同じ。

        Auto Speaker 追跡中は device_manager 側の ActiveEndpointTracker が
        250ms 周期で COM ポーリングしており、Recorder の open/close と並行
        実行されると WASAPI がデッドロックする (実測確認済み)。reconfigure の
        前後で tracker を pause/resume することで並行アクセスを排除する。
        Auto OFF 時は tracker が存在しないので pause/resume は no-op。
        """
        self.ensure_initialized()
        device_manager.pauseSpeakerEndpointTracker()
        try:
            self._speaker_session.reconfigure(device=device)
        finally:
            device_manager.resumeSpeakerEndpointTracker()

    def createOverlayImageSmallLog(self, message:Optional[str], your_language:Optional[str], translation:list, target_language:Optional[dict], transliteration_message:Optional[dict] = None, transliteration_translation:Optional[list] = None) -> object:
        self.ensure_initialized()
        # Normalize target_language dict -> list
        target_language_list = []
        if isinstance(target_language, dict):
            target_language_list = [data["language"] for data in target_language.values() if data.get("enable") is True]

        # 翻訳行ルビ (任意) が指定されていれば渡す。後方互換のため None / 不正型は空リストに。
        if not isinstance(transliteration_message, list):
            transliteration_message = []
        if not isinstance(transliteration_translation, list):
            transliteration_translation = [[] for _ in translation]

        return self.overlay_image.createOverlayImageSmallLog(
            message,
            your_language,
            translation,
            target_language_list,
            transliteration_message=transliteration_message,
            transliteration_translation=transliteration_translation,
        )

    def createOverlayImageSmallMessage(self, message):
        self.ensure_initialized()
        ui_language = config.UI_LANGUAGE
        convert_languages = {
            "en": "Default",
            "jp": "Japanese",
            "ko":"Korean",
            "zh-Hans":"Chinese Simplified",
            "zh-Hant":"Chinese Traditional",
        }
        language = convert_languages.get(ui_language, "Default")
        return self.overlay_image.createOverlayImageSmallLog(message, language)

    def clearOverlayImageSmallLog(self):
        self.ensure_initialized()
        self.overlay.clearImage("small")

    def updateOverlaySmallLog(self, img):
        self.ensure_initialized()
        self.overlay.updateImage(img, "small")

    def updateOverlaySmallLogSettings(self):
        self.ensure_initialized()
        size = "small"

        if (self.overlay.settings[size]["x_pos"] != config.OVERLAY_SMALL_LOG_SETTINGS["x_pos"] or
            self.overlay.settings[size]["y_pos"] != config.OVERLAY_SMALL_LOG_SETTINGS["y_pos"] or
            self.overlay.settings[size]["z_pos"] != config.OVERLAY_SMALL_LOG_SETTINGS["z_pos"] or
            self.overlay.settings[size]["x_rotation"] != config.OVERLAY_SMALL_LOG_SETTINGS["x_rotation"] or
            self.overlay.settings[size]["y_rotation"] != config.OVERLAY_SMALL_LOG_SETTINGS["y_rotation"] or
            self.overlay.settings[size]["z_rotation"] != config.OVERLAY_SMALL_LOG_SETTINGS["z_rotation"] or
            self.overlay.settings[size]["tracker"] != config.OVERLAY_SMALL_LOG_SETTINGS["tracker"]):
            self.overlay.updatePosition(
                config.OVERLAY_SMALL_LOG_SETTINGS["x_pos"],
                config.OVERLAY_SMALL_LOG_SETTINGS["y_pos"],
                config.OVERLAY_SMALL_LOG_SETTINGS["z_pos"],
                config.OVERLAY_SMALL_LOG_SETTINGS["x_rotation"],
                config.OVERLAY_SMALL_LOG_SETTINGS["y_rotation"],
                config.OVERLAY_SMALL_LOG_SETTINGS["z_rotation"],
                config.OVERLAY_SMALL_LOG_SETTINGS["tracker"],
                size,
            )
        if (self.overlay.settings[size]["display_duration"] != config.OVERLAY_SMALL_LOG_SETTINGS["display_duration"]):
            self.overlay.updateDisplayDuration(config.OVERLAY_SMALL_LOG_SETTINGS["display_duration"], size)
        if (self.overlay.settings[size]["fadeout_duration"] != config.OVERLAY_SMALL_LOG_SETTINGS["fadeout_duration"]):
            self.overlay.updateFadeoutDuration(config.OVERLAY_SMALL_LOG_SETTINGS["fadeout_duration"], size)
        if (self.overlay.settings[size]["opacity"] != config.OVERLAY_SMALL_LOG_SETTINGS["opacity"]):
            self.overlay.updateOpacity(config.OVERLAY_SMALL_LOG_SETTINGS["opacity"], size, True)
        if (self.overlay.settings[size]["ui_scaling"] != config.OVERLAY_SMALL_LOG_SETTINGS["ui_scaling"]):
            self.overlay.updateUiScaling(config.OVERLAY_SMALL_LOG_SETTINGS["ui_scaling"], size)

    def createOverlayImageLargeLog(self, message_type:str, message:Optional[str], your_language:Optional[str],  translation:list, target_language:Optional[dict]=None, transliteration_message:Optional[list]=None, transliteration_translation:Optional[list]=None) -> object:
        self.ensure_initialized()
        # normalize target_language dict -> list of language strings
        target_language_list = []
        if isinstance(target_language, dict):
            target_language_list = [data["language"] for data in target_language.values() if data.get("enable") is True]
        return self.overlay_image.createOverlayImageLargeLog(message_type, message, your_language, translation, target_language_list, transliteration_message, transliteration_translation)

    def createOverlayImageLargeMessage(self, message):
        self.ensure_initialized()
        ui_language = config.UI_LANGUAGE
        convert_languages = {
            "en": "Default",
            "jp": "Japanese",
            "ko":"Korean",
            "zh-Hans":"Chinese Simplified",
            "zh-Hant":"Chinese Traditional",
        }
        language = convert_languages.get(ui_language, "Default")
        overlay_image = OverlayImage(config.PATH_LOCAL)

        for _ in range(2):
            overlay_image.createOverlayImageLargeLog("send", message, language)
            overlay_image.createOverlayImageLargeLog("receive", message, language)
        return overlay_image.createOverlayImageLargeLog("send", message, language)

    def clearOverlayImageLargeLog(self):
        self.ensure_initialized()
        self.overlay.clearImage("large")

    def updateOverlayLargeLog(self, img):
        self.ensure_initialized()
        with self.overlay_image.log_lock:
            if self.overlay_image.isCurrentLargeLog(img):
                self.overlay.updateImage(img, "large")

    def publishMessageOverlayLargeLog(self, *args, current):
        """Keep a revoked render out of history used by later publications."""
        if not current():
            return
        self.ensure_initialized()
        with self.overlay_image.log_lock:
            if not current():
                return
            checkpoint = self.overlay_image.checkpointCaptionState()
            committed = False
            try:
                image = self.createOverlayImageLargeLog(*args)
                if current():
                    self.updateOverlayLargeLog(image)
                    committed = True
            finally:
                if not committed:
                    self.overlay_image.restoreCaptionState(checkpoint)

    def publishRealtimeCaptionOverlay(self, payload, language, target_languages, current, *, only_translated=False):
        """Serialize history/render/publication; caller runs outside the WS loop."""
        if not current():
            return
        self.ensure_initialized()
        with self.overlay_image.log_lock:
            if not current():
                return
            translation = [row["message"] for row in payload.get("translations", [])]
            if only_translated and not translation and payload["state"] != "discarded":
                return
            original = payload.get("original", {"message": payload["text"], "transliteration": []})
            identity = (payload["source"], payload["namespace"], payload["item_id"])
            checkpoint = self.overlay_image.checkpointCaptionState()
            committed = False
            try:
                image = self.overlay_image.createOverlayImageLargeLog(
                    "send" if payload["source"] == "mic" else "receive",
                    None if only_translated else original["message"], language,
                    translation, [row["language"] for row in target_languages.values() if row.get("enable")],
                    original.get("transliteration", []), [row.get("transliteration", []) for row in payload.get("translations", [])],
                    caption_id=identity,
                    caption_state=payload["state"], caption_revision=payload["revision"])
                if image is None:
                    committed = True  # An old/terminal revision changed nothing.
                elif current():
                    self.updateOverlayLargeLog(image)
                    committed = True
            finally:
                if not committed:
                    self.overlay_image.rejectCaptionUpdate(checkpoint, identity, payload["revision"])

    def clearRealtimeCaptionOverlay(self, source, namespace):
        self.ensure_initialized()
        with self.overlay_image.log_lock:
            image = self.overlay_image.discardCaptionNamespace(source, namespace)
            self.updateOverlayLargeLog(image)

    def updateOverlayLargeLogSettings(self):
        self.ensure_initialized()
        size = "large"
        if (self.overlay.settings[size]["x_pos"] != config.OVERLAY_LARGE_LOG_SETTINGS["x_pos"] or
            self.overlay.settings[size]["y_pos"] != config.OVERLAY_LARGE_LOG_SETTINGS["y_pos"] or
            self.overlay.settings[size]["z_pos"] != config.OVERLAY_LARGE_LOG_SETTINGS["z_pos"] or
            self.overlay.settings[size]["x_rotation"] != config.OVERLAY_LARGE_LOG_SETTINGS["x_rotation"] or
            self.overlay.settings[size]["y_rotation"] != config.OVERLAY_LARGE_LOG_SETTINGS["y_rotation"] or
            self.overlay.settings[size]["z_rotation"] != config.OVERLAY_LARGE_LOG_SETTINGS["z_rotation"] or
            self.overlay.settings[size]["tracker"] != config.OVERLAY_LARGE_LOG_SETTINGS["tracker"]):
            self.overlay.updatePosition(
                config.OVERLAY_LARGE_LOG_SETTINGS["x_pos"],
                config.OVERLAY_LARGE_LOG_SETTINGS["y_pos"],
                config.OVERLAY_LARGE_LOG_SETTINGS["z_pos"],
                config.OVERLAY_LARGE_LOG_SETTINGS["x_rotation"],
                config.OVERLAY_LARGE_LOG_SETTINGS["y_rotation"],
                config.OVERLAY_LARGE_LOG_SETTINGS["z_rotation"],
                config.OVERLAY_LARGE_LOG_SETTINGS["tracker"],
                size,
            )
        if (self.overlay.settings[size]["display_duration"] != config.OVERLAY_LARGE_LOG_SETTINGS["display_duration"]):
            self.overlay.updateDisplayDuration(config.OVERLAY_LARGE_LOG_SETTINGS["display_duration"], size)
        if (self.overlay.settings[size]["fadeout_duration"] != config.OVERLAY_LARGE_LOG_SETTINGS["fadeout_duration"]):
            self.overlay.updateFadeoutDuration(config.OVERLAY_LARGE_LOG_SETTINGS["fadeout_duration"], size)
        if (self.overlay.settings[size]["opacity"] != config.OVERLAY_LARGE_LOG_SETTINGS["opacity"]):
            self.overlay.updateOpacity(config.OVERLAY_LARGE_LOG_SETTINGS["opacity"], size, True)
        if (self.overlay.settings[size]["ui_scaling"] != config.OVERLAY_LARGE_LOG_SETTINGS["ui_scaling"]):
            self.overlay.updateUiScaling(config.OVERLAY_LARGE_LOG_SETTINGS["ui_scaling"] * 0.25, size)

    def setVrPanelWindows(self, log: bool, popup: bool) -> None:
        """VR UIのログウィンドウと一時ウィンドウの表示・非表示を切り替える。"""
        self.ensure_initialized()
        self.overlay.setVrWindows(log, popup)

    def setVrPanelEnabled(self, enabled: bool) -> None:
        """VR UI (ランチャーと各ウィンドウ) を表示するか。OFFの間は撮影もしない。"""
        self.ensure_initialized()
        self.overlay.setVrPanelEnabled(enabled)

    def setVrPanelLocked(self, locked: bool) -> None:
        """VR UIのログウィンドウを掴めなくする (操作バーのロック)。"""
        self.ensure_initialized()
        self.overlay.panel_locked = locked

    def setVrLauncherAutoHide(self, enabled: bool) -> None:
        """VR UIのランチャーを手首を見たときだけ出すか。"""
        self.ensure_initialized()
        self.overlay.launcher_auto_hide = enabled

    def resetVrLauncher(self) -> None:
        """ランチャーを初期の位置・大きさ・手 (左手) へ戻す。VR につながっていれば、手首へ吸い寄せて戻る。"""
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.requestLauncherReset()

    def updateVrLauncherPosition(self) -> None:
        """保存したランチャーの位置と付ける手をオーバーレイに反映する。"""
        self.ensure_initialized()
        s = config.OVERLAY_VR_LAUNCHER_SETTINGS
        self.overlay.updatePosition(s["x_pos"], s["y_pos"], s["z_pos"], s["x_rotation"], s["y_rotation"], s["z_rotation"], s["tracker"], LAUNCHER)

    def requestVrPanelAnchor(self, anchor: str) -> None:
        """VR UIのログウィンドウの固定先を切り替える (オーバーレイのスレッドで反映される)。"""
        self.ensure_initialized()
        self.overlay.requestAnchor(anchor)

    def recallVrPanelLog(self) -> None:
        """VR UIのログウィンドウを目の前へ呼び戻す。"""
        self.ensure_initialized()
        self.overlay.requestRecallPanel()

    def setVrPanelTooltip(self, data: dict) -> None:
        """Forward without initializing heavy backend resources."""
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.setTooltip(data)

    def setVrPanelLayoutRendered(self, panel_size: list) -> None:
        """VR画面が新しい並びで描き終えたことをオーバーレイに伝える。

        初期化中にも届く (取りこぼすと表示が切り替わらない) ので、ここで初期化はしない。
        オーバーレイがまだ無ければ捨ててよい (作られるときは既定の並びで、VR画面も既定の並びで描いている)。
        """
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.setLayoutRendered(panel_size)

    def setOverlayLayoutCallback(self, fn: Optional[Callable[[dict], None]]) -> None:
        """VR画面の並び (ログの大きさで変わる) が変わったときに呼ぶ関数を登録する。"""
        self.ensure_initialized()
        self.overlay.layout_callback = fn
        if fn is not None:
            fn(self.overlay.getVrLayout())

    def setOverlayPanelOutOfViewCallback(self, fn: Optional[Callable[[bool], None]]) -> None:
        """VR UIのログウィンドウが視線から外れた・戻ったときに呼ぶ関数を登録する。"""
        self.ensure_initialized()
        self.overlay.panel_out_of_view_callback = fn

    def setOverlayLauncherIntroCallback(self, fn: Optional[Callable[[str], None]]) -> None:
        """VR UIの起動演出の状態 (idle/pending/playing) が変わったときに呼ぶ関数を登録する。登録時に今の状態も渡す。"""
        self.ensure_initialized()
        self.overlay.launcher_intro_callback = fn
        if fn is not None:
            fn(self.overlay.launcher_intro_state)

    def updateOverlayVrPanelOpacity(self) -> None:
        """VR UIのログウィンドウの不透明度を反映する (オーバーレイのスレッドが毎フレーム settings から適用する)。"""
        self.ensure_initialized()
        self.overlay.settings[PANEL]["opacity"] = config.OVERLAY_VR_PANEL_SETTINGS["opacity"]

    def setOverlayPointerCallback(self, fn: Optional[Callable[[Optional[tuple]], None]]) -> None:
        """VR UI上のポインタの位置が変わったときに呼ぶ関数を登録する (ホバー表示用)。"""
        self.ensure_initialized()
        self.overlay.pointer_callback = fn

    def setOverlayPositionChangedCallback(self, fn: Optional[Callable[[str, dict], None]]) -> None:
        """VR内でオーバーレイを掴んで動かし、位置が確定したときに呼ぶ関数を登録する。"""
        self.ensure_initialized()
        self.overlay.position_changed_callback = fn

    def startOverlay(self):
        self.ensure_initialized()
        self.overlay.startOverlay()

    def shutdownOverlay(self):
        self.ensure_initialized()
        self.overlay.shutdownOverlay()

    def startWatchdog(self):
        self.ensure_initialized()
        with self._watchdog_lifecycle_lock:
            if self.th_watchdog is not None and self.th_watchdog.is_alive():
                return
            self._watchdog_stop_logged = False
            self.th_watchdog = threadFnc(self.watchdog.start)
            self.th_watchdog.daemon = True
            self.th_watchdog.start()
            self._armFreezeDump()

    def feedWatchdog(self):
        self.ensure_initialized()
        self.watchdog.feed()
        self._armFreezeDump()

    def _armFreezeDump(self):
        """次の feed が freeze 判定になるより前に、全スレッドスタックを
        freeze_trace.log へ書き出すタイマーを (再) 武装する。呼ぶたびに
        以前のタイマーは自動的に上書きされる (faulthandler の仕様)。
        """
        timeout = self.watchdog.interval + _FREEZE_DUMP_MARGIN_SEC
        try:
            faulthandler.dump_traceback_later(
                timeout, repeat=False, file=_freeze_trace_file, exit=False
            )
        except Exception:
            errorLogging()

    def setWatchdogCallback(self, callback):
        self.ensure_initialized()
        self.watchdog.setCallback(callback)

    def stopTranslationExecutor(self):
        """getInputTranslate() の並列化に使う常設プールを止める。

        ThreadPoolExecutor のワーカーは非デーモンスレッドで、インタプリタ
        終了時に atexit (concurrent.futures.thread._python_exit) で join
        される。翻訳が詰まったままだと終了がそこで止まるため、shutdown()
        から明示的に停止する。待たない (wait=False) のは、詰まっている
        呼び出しに shutdown() を道連れにさせないため。

        注意: shutdown(wait=False) が捨てるのは**まだ開始していない**
        タスクだけで、既に実行中のワーカーは止まらない。つまりこの関数は
        すぐ返るが、**プロセスが消えるのは実行中の呼び出しが返るまで
        遅れうる**。その上限はエンジンによって違う:

        - Google / Bing / Papago: _WEB_TRANSLATOR_TIMEOUT_SECONDS (10秒)
        - LMStudio / Ollama / OpenRouter: 各プロバイダで timeout 指定あり
        - OpenAI / OpenAI互換 / Groq / Gemini / Plamo: **明示指定なし**。
          SDK の既定に従う (openai は read=600秒 × max_retries=2) ので
          分単位になりうる

        実機では終了遅延を観測していない。executor を使うのは
        getInputTranslate (mic/chat のみ。speaker は getOutputTranslate の
        同期呼び出しで通らない) で、shutdown() は先に文字起こしを止めて
        いるため、停止の瞬間に翻訳が飛んでいる必要があるから。
        なお watchdog エスカレーション経由の終了 (mainloop.py の
        os._exit) は atexit を飛ばすのでこの経路に当たらない。

        ここで安易に wait=True + タイムアウト付き join を足すと、
        P-4 の初回修正と同じ「新たな終了遅延を作り込む」形になる。
        実機で終了遅延が実際に出てから、上限の無いエンジン側に timeout を
        入れる方向で直すこと。
        """
        executor = getattr(self, '_translation_executor', None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def stopWatchdog(self):
        self.ensure_initialized()
        with self._watchdog_lifecycle_lock:
            # ダンプタイマーの解除を必ず先に行う。Watchdog.start() は末尾で
            # time.sleep(self.interval) する (既定20秒) 一方、threadFnc.stop() は
            # loop フラグを降ろすだけでこの sleep を中断できないため、join は
            # 最大 interval 秒ブロックする。以前はこの解除が join の後ろにあり、
            # shutdown() 側の _stopServiceForShutdown が5秒で諦めた時点で
            # 一度も実行されず、「正常終了なのに freeze_trace.log へダンプが出る」
            # という当初直したかった現象がそのまま残っていた (実機ログで確認)。
            # 解除自体はスレッドと独立した faulthandler の操作なので先に行える。
            try:
                faulthandler.cancel_dump_traceback_later()
            except Exception:
                errorLogging()
            if isinstance(self.th_watchdog, threadFnc):
                self.th_watchdog.stop()
                # 上記のとおり sleep は中断できないので join は無期限にしない。
                # daemon thread なので、起きそこねてもプロセス終了時に破棄される。
                self.th_watchdog.join(timeout=_WATCHDOG_JOIN_TIMEOUT_SEC)
                if self.th_watchdog.is_alive():
                    if not getattr(self, "_watchdog_stop_logged", False):
                        self._watchdog_stop_logged = True
                        printLog("Watchdog: stop timed out; restart deferred until the worker exits")
                    return
                self.th_watchdog = None

    def message_handler(self, server, websocket, message):
        """WebSocketメッセージ受信時の処理"""
        pass

    def startWebSocketServer(self, host, port) -> bool:
        """Wait up to six seconds for listening; cancel and reap a failed attempt."""
        self.ensure_initialized()
        with self._websocket_lifecycle_lock:
            server = self.websocket_server
            if server is None or server.is_stopped:
                server = WebSocketServer(host=host, port=port, token=config.WEBSOCKET_AUTH_TOKEN)
                server.set_message_handler(self.message_handler)
                self.websocket_server = server
            try:
                attempt = server.begin_start(timeout=_WEBSOCKET_START_TIMEOUT)
            except Exception:
                errorLogging()
                return False

        try:
            server.wait_started(attempt)
        except Exception:
            errorLogging()
            # Cleanup owns only this server, not a replacement published by a
            # concurrent enable. Keep a stuck worker reachable until it exits.
            with self._websocket_lifecycle_lock:
                if self.websocket_server is server and server.is_stopped:
                    self.websocket_server = None
            return False
        with self._websocket_lifecycle_lock:
            return self.websocket_server is server and server.is_running

    def stopWebSocketServer(self):
        """Cancel pending startup as well as an already listening server."""
        self.ensure_initialized()
        with self._websocket_lifecycle_lock:
            server = self.websocket_server
            if server is None:
                return
            server.stop()
            if server.is_stopped:
                self.websocket_server = None
            else:
                # Don't forget the old attempt or allow a competing bind while
                # its resources are still being released. A later start retries.
                printLog("WebSocket server thread did not terminate properly")

    def checkWebSocketServerAlive(self):
        self.ensure_initialized()
        with self._websocket_lifecycle_lock:
            return self.websocket_server is not None and self.websocket_server.is_running

    def startObsBrowserSourceServer(self, host: str, port: int) -> bool:
        """Return true only when OBS is listening on the requested address."""
        self.ensure_initialized()
        with self._obs_lifecycle_lock:
            server = self.obs_browser_source_server
            if (server is not None and server.is_running
                    and server.host == host and server.port == port):
                return True
            self.stopObsBrowserSourceServer()
            if self.obs_browser_source_server is not None:
                return False  # The previous worker still owns its server.
            try:
                server = ObsBrowserSourceServer(host=host, port=port, ws_token=config.WEBSOCKET_AUTH_TOKEN)
                self.obs_browser_source_server = server
                server.start()
                return server.is_running
            except Exception:
                errorLogging()
                if server is None or server.is_stopped:
                    self.obs_browser_source_server = None
                return False

    def stopObsBrowserSourceServer(self) -> None:
        self.ensure_initialized()
        with self._obs_lifecycle_lock:
            server = self.obs_browser_source_server
            if server is None:
                return
            try:
                server.stop()
            except Exception:
                errorLogging()
                return
            if server.is_stopped:
                self.obs_browser_source_server = None

    def checkObsBrowserSourceServerAlive(self) -> bool:
        self.ensure_initialized()
        try:
            return (
                isinstance(self.obs_browser_source_server, ObsBrowserSourceServer)
                and self.obs_browser_source_server.is_running
            )
        except Exception:
            errorLogging()
            return False

    def websocketSendMessage(self, message_dict:dict):
        """
        WebSocketサーバーから全クライアントにメッセージを送信する
        :param message_dict: 送信するメッセージの辞書
        :return: 送信成功したかどうか
        """
        self.ensure_initialized()
        if not self.checkWebSocketServerAlive():
            return False
        try:
            message_json = json.dumps(message_dict)
            return self.websocket_server.send(message_json)
        except BufferError:
            # Let the existing per-output failure notification report admission
            # limits without losing the other conversation outputs.
            raise
        except Exception:
            errorLogging()
            return False

    def setCopyToClipboardAndPasteFromClipboard(self, text:str) -> bool:
        self.ensure_initialized()
        try:
            if isinstance(self.clipboard, Clipboard):
                self.clipboard.copy_and_paste(text)
                return True
            else:
                return False
        except Exception:
            errorLogging()
            return False

    def telemetryInit(self, enabled: bool, app_version: str, storage_path: str = None):
        """Model 内で Telemetry を初期化"""
        if storage_path is None:
            try:
                storage_path = os_path.join(config.PATH_DATA, "telemetry_state.json")
            except Exception:
                storage_path = None
        self.telemetry.init(enabled=enabled, app_version=app_version, storage_path=storage_path)

    def telemetryShutdown(self):
        """Model cleanup on application shutdown."""
        if hasattr(self, "telemetry") and self.telemetry:
            self.telemetry.shutdown()

    def telemetryTrackError(self, error_code: str):
        """エラーコードのテレメトリ送信 (Model ラッパー)。日次デデュープ済み。"""
        if hasattr(self, "telemetry") and self.telemetry:
            self.telemetry.track_error(error_code)

    def telemetryTouchActivity(self):
        """テレメトリアクティビティ更新 (Model ラッパー)"""
        if hasattr(self, "telemetry") and self.telemetry:
            self.telemetry.touch_activity()

model = Model()

# エラー生成時にテレメトリへ通知するフックを登録する（日次デデュープ済み）
from errors import register_error_report_hook  # noqa: E402
register_error_report_hook(model.telemetryTrackError)
