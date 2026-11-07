import base64
from functools import lru_cache
from typing import Any, Callable, List, Dict, Optional, Tuple
import ctypes
import glob
import json
import os
import queue
import sys
import traceback
import logging
import threading
import time
from collections import OrderedDict
from logging.handlers import RotatingFileHandler

import requests
import startup_timing
from models.network_policy import redact_urls
from models.diagnostics import exception_provider, redact_diagnostic_text
import ipaddress
import socket

def _registerBundledCudaLibraries() -> None:
    """nvidia-*-cu12 wheel が置いたCUDAライブラリをDLL検索パスへ登録する。

    CUDA版ビルドは ctranslate2 が必要とする cuBLAS / cuDNN を
    nvidia-cublas-cu12 / nvidia-cudnn-cu12 から取る。これらは
    site-packages/nvidia/<lib>/bin に展開されるだけで検索パスには載らない。
    torch を入れていた頃は torch が自前の lib/ を登録するついでに
    同梱の cuBLAS を拾えていたので、torch を落とした今は自分で登録する
    (2026-09-18)。

    PATH にも足すのは、cudnn64_9.dll が中で cudnn_ops64_9.dll 等を素の
    LoadLibrary で開き、add_dll_directory の登録が効かないため
    (実測: PATH 無しだと "Could not locate cudnn_ops64_9.dll" で落ちる)。

    凍結ビルドでも同じ処理で動く。PyInstaller は同じDLL群を
    _internal/nvidia/<lib>/bin/ へ収集するので (spec/backend_cuda.spec の
    hiddenimports 参照)、`nvidia.__path__` からそのまま辿れる。
    CPU版ビルドには `nvidia` が無いので、その場合は何もせず返る。
    """
    if os.name != "nt":
        return
    try:
        import nvidia  # type: ignore
    except ImportError:
        return

    library_dirs = sorted(
        {
            library_dir
            for search_path in nvidia.__path__
            for library_dir in glob.glob(os.path.join(search_path, "*", "bin"))
            if os.path.isdir(library_dir)
        }
    )
    if not library_dirs:
        return
    for library_dir in library_dirs:
        os.add_dll_directory(library_dir)
    os.environ["PATH"] = os.pathsep.join(library_dirs) + os.pathsep + os.environ.get("PATH", "")

_registerBundledCudaLibraries()

# ctranslate2 は import 時に ctranslate2.converters.transformers 経由で
# transformers を読み込む。transformers は torch が無いと
# "Models won't be available" という advice 警告を stderr へ出すが、
# VRCT が transformers に使っているのは AutoTokenizer だけなので
# 実害はなく紛らわしいだけ (torch 撤去後に発生, 2026-09-18)。
# advice 警告だけを黙らせる。通常の警告・エラーはそのまま出る。
# フロントの StartPythonController は sidecar の stderr 出力を致命的エラー
# 通知に昇格させるため、放置すると良性の警告が「An error occurred」
# ダイアログに化ける (mainloop.py の grpcio FutureWarning と同じ理由)。
# ここに置いているのは、ctranslate2 を最初に import するのがこのファイルで、
# 警告は import 時に出てしまうため。
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

# Optional runtime dependencies. `None` fallback lets non-GPU / no-ctranslate2
# environments keep the app running with reduced feature set.
try:
    from ctranslate2 import get_supported_compute_types as _ct2_get_supported_compute_types  # noqa: F401
except Exception:
    def _ct2_get_supported_compute_types(device: str, device_index: int) -> List[str]:  # type: ignore
        return []

try:
    from ctranslate2 import get_cuda_device_count as _ct2_get_cuda_device_count  # noqa: F401
except Exception:
    def _ct2_get_cuda_device_count() -> int:  # type: ignore
        return 0


# stdout は Tauri 側が読み取る IPC チャンネルとして使われており、
# printLog/printResponse は複数スレッド (mainloop の worker 群、
# MicSession/SpeakerSession の transcript スレッド、
# AudioLifecycleWorker 等) から高頻度・並行に呼ばれ得る。
# print(..., flush=True) は内部で複数の write システムコールに
# 分解され得るため、ロック無しで並行に呼ぶと (特に Windows の名前付き
# パイプ相手に) 出力が混ざったり、OSError (Errno 22, Invalid argument)
# を招くことがある。1 プロセス内で書き込みを直列化する。
_stdout_write_lock = threading.Lock()


def _logStdoutTransport(message: str) -> None:
    """輸送自体の診断は error.log だけへ。失敗しても stdout に戻さない。"""
    global error_logger
    try:
        if error_logger is None:
            error_logger = setupLogger("error", "error.log", logging.ERROR)
        error_logger.error(message)
    except Exception:
        pass


_STDOUT_WRITE_ATTEMPTS = 3
_stdout_needs_separator = False


def _writeStdoutLine(line: str) -> bool:
    """一時的な OSError は同じ行を最大3回試す。要求の処理は再実行しない。

    write/flush の例外では途中まで出た可能性がある。次の試行・次の行の
    前に改行を flush し、断片と次の JSON を連結しない。改行の失敗も
    試行回数に含める。改行済みの行で flush が失敗した場合の重複は、
    受信確認のない現行プロトコルでは判別できない。
    """
    global _stdout_needs_separator

    def write(text):
        count = sys.stdout.write(text)
        if count is not None and count != len(text):
            raise OSError("short stdout write")
        sys.stdout.flush()

    with _stdout_write_lock:
        for attempt in range(_STDOUT_WRITE_ATTEMPTS):
            try:
                if _stdout_needs_separator:
                    write("\n")
                    _stdout_needs_separator = False
                write(line + "\n")
                return True
            except Exception as exc:
                _stdout_needs_separator = True
                # 例外の本文には出力内容が含まれ得るため、型と errno だけ残す。
                _logStdoutTransport(
                    f"stdout write failed: attempt={attempt + 1} "
                    f"type={type(exc).__name__} errno={getattr(exc, 'errno', None)}"
                )
                if not isinstance(exc, OSError) or isinstance(exc, BrokenPipeError):
                    break
    return False


# --- stdout 専用書き込みスレッド (フェーズ3項目18) ---
#
# 以前は printLog/printResponse を呼んだスレッドが直接 _writeStdoutLine()
# を (ロック付きで) 実行していた。Tauri 側のパイプが壊れると
# sys.stdout.write() が OSError (Errno 22) を送出し (error.log に実例あり、
# 2026-08-27)、パイプが「読まれずに埋まる」場合はブロックする。
# いずれの場合も _stdout_write_lock を握ったまま止まるため、
# printLog/printResponse/run() を呼ぶ全スレッド (energy メーターは
# 毎秒15回程度 run() を叩く) が芋づる式に停止していた
# (freeze_trace.log 2026-08-27、35秒フリーズで実際に確認済み)。
#
# 書き込み自体を専用スレッド1本に閉じ込め、呼び出し元は「キューに積む」
# だけにすることでこの連鎖を断つ。応答と確定通知は上限なしで保持し、
# 許可した状態通知だけを集約する。独立した監視スレッドが詰まりを記録する。
# 診断ログは古いものから捨てる200件のキューを維持する。
_STDOUT_LOG_QUEUE_MAXSIZE = 200
_STDOUT_REPLACEABLE_MAX_KEYS = 64
_STDOUT_CAPTION_TERMINAL_MAX_KEYS = 256
_STDOUT_STALL_SECONDS = 20.0
_MAX_CONSECUTIVE_STDOUT_FAILURES = 50


class _StdoutResponseQueue:
    """呼び出し元が _stdout_writer_condition で保護する順序付きバッファ。

    集約した値は新しい投入位置へ移す。これにより開始応答を追い越さず、
    残った行同士の順序も変えない。異なる字幕行などは互いの代替にならない。
    64キーを超える新規キーは通常の行として保持し、勝手に捨てない。
    """
    def __init__(self):
        self._lines = OrderedDict()
        self._replaceable = {}
        self._terminal = OrderedDict()
        self._pending_terminals = {}
        self._sequence = 0

    def put(self, line, replaceable_key=None, terminal_key=None):
        if terminal_key is not None:
            previous = self._replaceable.pop(terminal_key, None)
            if previous is not None:
                del self._lines[previous]
            self._pending_terminals[terminal_key] = self._pending_terminals.get(terminal_key, 0) + 1
        if replaceable_key is not None:
            if replaceable_key in self._terminal or replaceable_key in self._pending_terminals:
                return  # 確定済み字幕の遅い partial は表示を巻き戻さない。
            previous = self._replaceable.pop(replaceable_key, None)
            if previous is not None:
                del self._lines[previous]
            elif len(self._replaceable) >= _STDOUT_REPLACEABLE_MAX_KEYS:
                replaceable_key = None  # 別の行を捨てるより、集約を諦める。
        self._sequence += 1
        self._lines[self._sequence] = (line, replaceable_key, terminal_key)
        if replaceable_key is not None:
            self._replaceable[replaceable_key] = self._sequence

    def get_nowait(self):
        if not self._lines:
            raise queue.Empty
        _, (line, key, terminal_key) = self._lines.popitem(last=False)
        if key is not None:
            del self._replaceable[key]
        if terminal_key is not None:
            self._pending_terminals[terminal_key] -= 1
            if not self._pending_terminals[terminal_key]:
                del self._pending_terminals[terminal_key]
            # 待機中の確定行はすべて保護。取り出した履歴だけを字幕生成側と同じ256件にする。
            self._terminal[terminal_key] = None
            self._terminal.move_to_end(terminal_key)
            if len(self._terminal) > _STDOUT_CAPTION_TERMINAL_MAX_KEYS:
                self._terminal.popitem(last=False)
        return line

    def qsize(self):
        return len(self._lines)

    def empty(self):
        return not self._lines


def _stdoutDeliveryKeys(status, endpoint, result):
    """通知だけの許可リスト。要求の応答には呼ばない。不明な形は保持する。"""
    if status != 200:
        return None, None
    if endpoint in ("/run/check_mic_volume", "/run/check_speaker_volume"):
        if type(result) in (int, float):
            return (endpoint,), None  # useVolume は現在値を置き換えるだけ。
    elif endpoint == "/run/vr_panel_pointer":
        if result is None or (isinstance(result, dict)
                and all(type(result.get(axis)) in (int, float) for axis in ("x", "y"))):
            return (endpoint,), None  # hover 表示の座標。クリックは別経路。
    elif endpoint in ("/run/download_progress_ctranslate2_weight", "/run/download_progress_whisper_weight"):
        if (isinstance(result, dict) and isinstance(result.get("weight_type"), str)
                and 0 < len(result["weight_type"]) <= 256
                and type(result.get("progress")) in (int, float) and 0 <= result["progress"] <= 1):
            return (endpoint, result["weight_type"]), None  # 完了処理は downloaded 通知。
    elif endpoint == "/run/realtime_caption" and isinstance(result, dict):
        if (result.get("source") in ("mic", "speaker")
                and type(result.get("generation")) is int and result["generation"] >= 0
                and isinstance(result.get("namespace"), str) and 0 < len(result["namespace"]) <= 128
                and isinstance(result.get("item_id"), str) and 0 < len(result["item_id"]) <= 256
                and type(result.get("revision")) is int and result["revision"] >= 1
                and (isinstance(result.get("text"), str) or result.get("state") == "outcome")):
            key = (endpoint, result["source"], result["generation"], result["namespace"], result["item_id"])
            if result.get("state") == "partial" and result["text"].strip():
                return key, None  # 同じ字幕行の全文。空文字は UI の retire 操作なので保持。
            if result.get("state") in ("final", "translated", "discarded", "outcome"):
                return None, key
    return None, None


_stdout_response_queue = _StdoutResponseQueue()
_stdout_log_queue: "queue.Queue" = queue.Queue(maxsize=_STDOUT_LOG_QUEUE_MAXSIZE)
_stdout_writer_thread: Optional[threading.Thread] = None
_stdout_monitor_thread: Optional[threading.Thread] = None
_stdout_writer_start_lock = threading.Lock()
_stdout_writer_stop_event = threading.Event()
# 状態の更新は同じロックで保護し、起こす相手だけ条件変数で分ける。
_stdout_state_lock = threading.RLock()
_stdout_writer_condition = threading.Condition(_stdout_state_lock)
_stdout_monitor_condition = threading.Condition(_stdout_state_lock)
_stdout_monitor_deadline: Optional[float] = None
_stdout_stalled_at: Optional[int] = None
_stdout_pending_since: Optional[float] = None
_stdout_in_flight = False
_stdout_completed_lines = 0
_stdout_lost_lines = 0
_on_frontend_lost: Optional[Callable[[], None]] = None


def _stdoutBacklogCounts():
    replaceable = len(_stdout_response_queue._replaceable)
    return (f"reliable={_stdout_response_queue.qsize() - replaceable} "
            f"replaceable={replaceable} logs={_stdout_log_queue.qsize()} "
            f"in_flight={int(_stdout_in_flight)} lost_lines={_stdout_lost_lines}")


def _stdoutMonitorLoop() -> None:
    """専用の条件変数で期限まで眠り、20秒進捗がなければ1回記録する。"""
    global _stdout_monitor_deadline, _stdout_stalled_at
    while not _stdout_writer_stop_event.is_set():
        with _stdout_monitor_condition:
            if _stdout_writer_stop_event.is_set():
                return
            if _stdout_stalled_at is not None and _stdout_completed_lines != _stdout_stalled_at:
                message = "stdout recovered: " + _stdoutBacklogCounts()
                _stdout_stalled_at = None
                _stdout_monitor_deadline = (None if _stdout_pending_since is None
                                            else _stdout_pending_since + _STDOUT_STALL_SECONDS)
            elif _stdout_stalled_at is not None or _stdout_monitor_deadline is None:
                _stdout_monitor_condition.wait()
                continue
            else:
                remaining = _stdout_monitor_deadline - time.monotonic()
                if remaining > 0:
                    _stdout_monitor_condition.wait(remaining)
                    continue
                if _stdout_pending_since is None:
                    _stdout_monitor_deadline = None
                    continue
                # 正常な完了は時刻だけ更新する。期限が来てから最新の進捗を読む。
                _stdout_monitor_deadline = _stdout_pending_since + _STDOUT_STALL_SECONDS
                if _stdout_monitor_deadline > time.monotonic():
                    continue
                _stdout_stalled_at = _stdout_completed_lines
                _stdout_monitor_deadline = None
                message = f"stdout stalled: threshold_seconds={_STDOUT_STALL_SECONDS} " + _stdoutBacklogCounts()
        # ディスク書き込み中は投入側のロックを持たない。停止・再送はしない。
        _logStdoutTransport(message)


def setFrontendLostCallback(callback: Optional[Callable[[], None]]) -> None:
    """stdoutへの書き込みが連続して失敗した際に呼ぶコールバックを登録する。

    未登録 (None、既定) の場合は os._exit(1) で自己終了する。テストが
    実プロセスを終了させずに検知だけを確認できるようにするための差し替え口。
    """
    global _on_frontend_lost
    _on_frontend_lost = callback


def _stdoutWriterLoop() -> None:
    global _stdout_pending_since, _stdout_in_flight, _stdout_completed_lines, _stdout_lost_lines
    consecutive_failures = 0
    while not _stdout_writer_stop_event.is_set():
        # 両キューへの投入と停止を同じ条件変数で通知する。
        # 空の確認から待機までをロックで保護し、通知の取りこぼしを防ぐ。
        # 起床後も応答を先に取り出す。実際の書き込み中はロックを離す。
        with _stdout_writer_condition:
            _stdout_writer_condition.wait_for(
                lambda: _stdout_writer_stop_event.is_set()
                or not _stdout_response_queue.empty()
                or not _stdout_log_queue.empty()
            )
            if _stdout_writer_stop_event.is_set():
                return
            try:
                line = _stdout_response_queue.get_nowait()
            except queue.Empty:
                line = _stdout_log_queue.get_nowait()
            _stdout_in_flight = True

        success = _writeStdoutLine(line)
        with _stdout_writer_condition:
            _stdout_in_flight = False
            if success:
                _stdout_completed_lines += 1
                _stdout_pending_since = time.monotonic()
                if _stdout_stalled_at is not None and _stdout_completed_lines == _stdout_stalled_at + 1:
                    _stdout_monitor_condition.notify()  # 詰まりの報告後、最初の成功だけ復旧を通知。
            else:
                _stdout_lost_lines += 1
            if _stdout_response_queue.empty() and _stdout_log_queue.empty():
                _stdout_pending_since = None
        if success:
            consecutive_failures = 0
            continue

        consecutive_failures += 1
        # 次の行の成功で連続失敗は戻すが、欠落の累計と記録は消さない。
        _logStdoutTransport(f"stdout line lost: lost_lines={_stdout_lost_lines} consecutive_failures={consecutive_failures}")
        if consecutive_failures >= _MAX_CONSECUTIVE_STDOUT_FAILURES:
            callback = _on_frontend_lost
            if callback is not None:
                try:
                    callback()
                except Exception:
                    _logStdoutTransport("stdout frontend-lost callback failed")
            else:
                os._exit(1)
            return  # コールバック指定時は書き込みスレッドを終了する


def _ensureStdoutWriterStarted() -> None:
    # 2つのスレッドがほぼ同時に初回の printLog/printResponse を呼ぶと、
    # 素朴な "None なら作る" チェックだけでは両方が「まだ無い」と判定し
    # 書き込みスレッドが2本立ち上がりうる (直そうとしている「複数スレッドが
    # 同時に stdout へ書き込む」問題の再発になる)。起動処理自体をロックで
    # 直列化する。
    global _stdout_writer_thread, _stdout_monitor_thread
    with _stdout_writer_start_lock:
        if _stdout_writer_thread is not None and _stdout_writer_thread.is_alive():
            return
        _stdout_writer_stop_event.clear()
        _stdout_writer_thread = threading.Thread(
            target=_stdoutWriterLoop, name="StdoutWriter", daemon=True
        )
        _stdout_writer_thread.start()
        if _stdout_monitor_thread is None or not _stdout_monitor_thread.is_alive():
            _stdout_monitor_thread = threading.Thread(
                target=_stdoutMonitorLoop, name="StdoutMonitor", daemon=True
            )
            _stdout_monitor_thread.start()


def stopStdoutWriter() -> None:
    """通常のシャットダウン時に書き込みスレッドを止める。デーモンスレッド
    なのでプロセス終了自体はこれを呼ばなくてもブロックしないが、
    行儀よく止めておく。"""
    with _stdout_writer_condition:
        _stdout_writer_stop_event.set()
        _stdout_writer_condition.notify()
        _stdout_monitor_condition.notify()


def _markStdoutPending() -> None:
    """共有ロック内で呼ぶ。監視の期限が未設定なら、最初の投入だけ通知する。"""
    global _stdout_pending_since, _stdout_monitor_deadline
    if _stdout_pending_since is None:
        _stdout_pending_since = time.monotonic()
        if _stdout_monitor_deadline is None and _stdout_stalled_at is None:
            # 一度セットした期限は、途中でキューが空になっても監視側まで維持する。
            # すぐ書けるメーターでも、空→投入のたびに監視を起こさないため。
            _stdout_monitor_deadline = _stdout_pending_since + _STDOUT_STALL_SECONDS
            _stdout_monitor_condition.notify()


def _enqueueResponseLine(line: str, replaceable_key=None, terminal_key=None) -> None:
    _ensureStdoutWriterStarted()
    with _stdout_writer_condition:
        _stdout_response_queue.put(line, replaceable_key, terminal_key)
        if not _stdout_response_queue.empty():
            _markStdoutPending()
        _stdout_writer_condition.notify()


def putDroppingOldestOnFull(q: "queue.Queue", item: Any) -> bool:
    """非ブロッキングでqに積む。満杯なら最も古い項目を1つ捨てて積み直す。

    ブロッキングpush (put()) は呼び出し元スレッド (録音コールバックや
    ログ出力元などリアルタイム処理を行うプロデューサ) を止めてしまう
    ため、常にput_nowaitのみを使う。あふれた場合は直近の状態の方が
    有用という前提で、古いものから捨てる (フェーズ3項目18で導入、
    項目20でaudio_queueにも展開する際に共通ヘルパーへ切り出した)。

    Returns:
        満杯で古い項目を1つ捨てた場合はTrue。呼び出し元が「捨てが
        発生したこと」をログに残したい場合に使う。
    """
    try:
        q.put_nowait(item)
        return False
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(item)
        except queue.Full:
            pass
        return True


def _enqueueLogLine(line: str) -> None:
    _ensureStdoutWriterStarted()
    with _stdout_writer_condition:
        putDroppingOldestOnFull(_stdout_log_queue, line)
        _markStdoutPending()
        _stdout_writer_condition.notify()


def validateDictStructure(data: dict, structure: dict) -> bool:
    """
    辞書とその期待される構造（型）が完全に一致するかを判別する関数
    Args:
        data (dict): 検証対象の辞書
        structure (dict): 期待される構造を定義した辞書値には型（str, int, bool等）や入れ子の辞書を指定

    Returns:
        bool: 構造が完全に一致する場合True、そうでなければFalse
    """

    if not isinstance(data, dict) or not isinstance(structure, dict):
        return False

    # キーの数と名前が完全に一致するかチェック
    if set(data.keys()) != set(structure.keys()):
        return False

    # 各キーの値の型または構造をチェック
    for key, expected_type_or_structure in structure.items():
        if key not in data:
            return False

        value = data[key]
        # 期待される型が辞書の場合（入れ子構造）
        if isinstance(expected_type_or_structure, dict):
            # 再帰的に検証（多重入れ子に対応）
            if not validateDictStructure(value, expected_type_or_structure):
                return False
        # 期待される型が型オブジェクトの場合
        else:
            if not isinstance(value, expected_type_or_structure):
                return False
    return True

def isConnectedNetwork(timeout=3) -> bool:
    """Probe only the pinned download origin, when a consented download is due."""
    from models.model_downloads.transport import probe_download_host
    return probe_download_host(timeout=timeout)

def isValidPort(port) -> bool:
    """Network settings require an exact integer, never bool or coercion."""
    return type(port) is int and 1 <= port <= 65535


def isValidWebSocketHost(host) -> bool:
    """WebSocket and OBS share an IPv4-only bind and URL contract."""
    if not isinstance(host, str):
        return False
    try:
        address = ipaddress.IPv4Address(host)
        return not address.is_unspecified
    except ValueError:
        return False


def isAvailableWebSocketServer(host: str, port: int) -> bool:
    """Return True if the given host/port appear available for binding.

    Note: This attempts to bind a TCP socket to the address. If bind
    succeeds the function returns True (meaning the address was available).
    """
    if not isValidWebSocketHost(host) or not isValidPort(port):
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as chk:
            chk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            chk.bind((host, port))
        return True
    except Exception:
        return False

def isValidIpAddress(ip_address: str) -> bool:
    """Return True if `ip_address` is a valid IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(ip_address)
        return True
    except ValueError:
        return False

def isWildcardBindAddress(ip_address: str) -> bool:
    """Return True if `ip_address` is the IPv4/IPv6 "unspecified" address
    (0.0.0.0 / ::), which means "listen on every interface".

    Used to reject binding the local WebSocket server to a wildcard
    address: unlike a specific LAN IP (which at least requires the same
    network segment), 0.0.0.0/:: exposes the unauthenticated-by-default
    transcript stream to literally any interface the machine has,
    including ones the user may not realize are reachable (VPN, hotspot,
    etc.).
    """
    try:
        return ipaddress.ip_address(ip_address).is_unspecified
    except ValueError:
        return False

# ctranslate2.dll は GPU 実行時に cuBLAS を LoadLibrary で遅延ロードする
# (ctranslate2.dll 内の文字列テーブルに "cublas64_12.dll" が入っている)。
# cuDNN は ctranslate2 の wheel に同梱されているが cuBLAS は入っておらず、
# CUDA版ビルドだけが nvidia-cublas-cu12 でこれを持つ。つまり
# 「cuBLASを引けるか」がそのままこのビルドでGPU実行できるかの判定になる。
# torch を使っていた頃は torch.cuda.is_available() が偶然この役目を
# 果たしていた (CPU版には CPU 版 torch が入るので常に False だった)。
_CUBLAS_LIBRARY_NAME = "cublas64_12.dll" if os.name == "nt" else "libcublas.so.12"

@lru_cache(maxsize=1)
def _getCudaDeviceNames() -> Tuple[str, ...]:
    """GPU実行に使えるCUDAデバイスの名前を返す。使えなければ空タプル。

    torch を落とした代替 (2026-09-18)。デバイスの有無と数は ctranslate2 が
    答えられるが、名前を返すAPIを持っていないのでそこだけ CUDA Driver API
    (nvcuda.dll / libcuda.so.1) を直接叩く。どちらもNVIDIAドライバに
    同梱されていて、CUDA Toolkit のインストールは要らない。

    名前が取れなくても致命傷ではないので空文字にフォールバックする。
    用途は UI 表示と compute_type 選択のキーワード一致 (GTX/RTX/...) だけで、
    どれにも一致しなければ "default" の優先順位が使われる。

    デバイス構成はプロセス実行中に変わらないので結果をキャッシュする。
    """
    try:
        device_count = _ct2_get_cuda_device_count()
    except Exception:
        return ()
    if device_count <= 0:
        return ()

    try:
        ctypes.CDLL(_CUBLAS_LIBRARY_NAME)
    except OSError:
        # GPUはあるが、このビルドは ctranslate2 が必要とするCUDAライブラリを
        # 同梱していない (CPU版)。選ばせると必ずモデル読み込みで失敗するので
        # デバイス一覧に出さない。
        return ()

    device_names = [""] * device_count
    try:
        cuda = ctypes.CDLL("nvcuda.dll" if os.name == "nt" else "libcuda.so.1")
    except OSError:
        # ドライバ不在。ctranslate2 が 0 を返していれば通常ここには来ない。
        return tuple(device_names)

    try:
        if cuda.cuInit(0) != 0:
            return tuple(device_names)
        name_buffer = ctypes.create_string_buffer(256)
        for device_index in range(device_count):
            device = ctypes.c_int()
            if cuda.cuDeviceGet(ctypes.byref(device), device_index) != 0:
                continue
            if cuda.cuDeviceGetName(name_buffer, len(name_buffer), device) != 0:
                continue
            device_names[device_index] = name_buffer.value.decode("utf-8", "replace")
    except Exception:
        errorLogging()
    return tuple(device_names)

def getComputeDeviceList() -> List[Dict[str, Any]]:
    """Return a list of available compute devices and supported compute types.

    The returned list contains dicts describing CPU and (if available)
    CUDA devices. This function is defensive to missing optional packages.
    """
    get_supported_compute_types = _ct2_get_supported_compute_types

    compute_types: List[Dict[str, Any]] = [
        {
            "device": "cpu",
            "device_index": 0,
            "device_name": "cpu",
            "compute_types": ["auto"] + sorted(list(get_supported_compute_types("cpu", 0))),
        }
    ]

    try:
        for device_index, gpu_device_name in enumerate(_getCudaDeviceNames()):
            gpu_compute_types = ["auto"] + sorted(list(get_supported_compute_types("cuda", device_index)))

            # デバイスごとの計算タイプの制限
            if "GTX" in gpu_device_name:
                unsupported_types = {"int8_bfloat16", "bfloat16", "float16", "int8"}
                gpu_compute_types = [t for t in gpu_compute_types if t not in unsupported_types]
            elif not any(keyword in gpu_device_name for keyword in ["RTX", "Tesla", "A100", "Quadro"]):
                gpu_compute_types = ["float32"]

            compute_types.append(
                {
                    "device": "cuda",
                    "device_index": device_index,
                    "device_name": gpu_device_name,
                    "compute_types": gpu_compute_types,
                }
            )
    except Exception:
        # If querying GPU devices fails, return at least the CPU entry
        errorLogging()

    return compute_types

def getBestComputeType(device: str, device_index: int) -> str:
    """Pick the best available compute type for a device.

    Falls back to "float32" when no preferred type is available.
    """
    try:
        compute_types = set(_ct2_get_supported_compute_types(device, device_index))
    except Exception:
        compute_types = set()

    if device == "cpu":
        device_name = "cpu"
    else:
        cuda_device_names = _getCudaDeviceNames()
        device_name = cuda_device_names[device_index] if device_index < len(cuda_device_names) else ""

    # デバイスごとの優先計算タイプ
    preferred_types = {
        "default": ["int8_bfloat16", "int8_float16", "int8", "bfloat16", "float16", "int8_float32", "float32"],
        "GTX": ["float32"],
        "RTX": ["int8_bfloat16", "int8_float16", "int8", "bfloat16", "float16", "int8_float32", "float32"],
        "Tesla": ["int8_bfloat16", "int8_float16", "int8", "bfloat16", "float16", "int8_float32", "float32"],
        "A100": ["int8_bfloat16", "int8_float16", "int8", "bfloat16", "float16", "int8_float32", "float32"],
        "Quadro": ["int8_bfloat16", "int8_float16", "int8", "bfloat16", "float16", "int8_float32", "float32"],
    }

    # デバイス名に基づいて優先タイプを選択
    selected_types = preferred_types["default"]
    for key in preferred_types:
        if key in device_name:
            selected_types = preferred_types[key]
            break

    # 利用可能な計算タイプを返す
    for compute_type in selected_types:
        if compute_type in compute_types:
            return compute_type

    return "float32"

def encodeBase64(data: str) -> Dict[str, Any]:
    """Decode a base64-encoded JSON string and return the parsed object.

    Returns an empty dict on failure.
    """
    try:
        return json.loads(base64.b64decode(data).decode('utf-8'))
    except Exception:
        errorLogging()
        return {}

def diagnosticLogPath(filename: str) -> str:
    """Honor explicit state isolation without changing legacy default paths."""
    directory = os.environ.get("VRCT_CONFIG_DIR")
    if not directory or os.path.dirname(filename):
        return filename
    logs = os.path.join(os.path.abspath(os.path.expanduser(directory)), "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, filename)


# faulthandler writes stack dumps straight to an open file, so the 10 MB cap of
# the logging handlers does not cover crash_trace.log and freeze_trace.log, and
# each freeze, crash or resume from sleep appended to them for good. Once over
# the cap, a trace file keeps only its newest part when the sidecar starts.
_TRACE_LOG_LIMIT = 10 * 1024 * 1024
_TRACE_LOG_KEEP = 1024 * 1024


def openTraceLog(filename: str, limit: int = _TRACE_LOG_LIMIT, keep: int = _TRACE_LOG_KEEP):
    """Return the path and an append handle of a faulthandler trace file."""
    path = diagnosticLogPath(filename)
    try:
        if os.path.getsize(path) > limit:
            with open(path, "rb") as source:
                source.seek(-keep, os.SEEK_END)
                tail = source.read()
            newline = tail.find(b"\n")  # start at a whole line
            with open(path, "wb") as target:
                target.write(tail[newline + 1:] if newline >= 0 else tail)
    except OSError:
        pass  # missing, or unreadable: appending below still works or fails as before
    return path, open(path, "a", encoding="utf-8")


def removeLog() -> None:
    """Truncate the process log file (process.log) if present."""
    try:
        with open(diagnosticLogPath('process.log'), 'w', encoding="utf-8") as f:
            f.write("")
    except Exception:
        errorLogging()

class TruncatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that truncates the log file in place instead of
    rotating it to a numbered backup (e.g. process.log.1). Creating that
    backup file was being picked up by Tauri's dev file watcher (src-tauri
    is inside the watched tree) and triggering a rebuild loop.
    """
    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        with open(self.baseFilename, "w", encoding=self.encoding):
            pass
        if not self.delay:
            self.stream = self._open()

class ConversationLogger:
    """会話ログの開始・停止・書き込みを同じロックで直列化する窓口。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._logger = logging.getLogger("log")
        self._logger.disabled = True

    def _stop(self):
        self._logger.disabled = True
        for handler in self._logger.handlers[:]:
            self._logger.removeHandler(handler)
            handler.close()

    def start(self, log_file: str):
        with self._lock:
            # 同じ秒で再開した場合も含め、古いハンドラーを残さない。
            self._stop()
            setupLogger("log", log_file)
            self._logger.disabled = False

    def stop(self):
        with self._lock:
            self._stop()

    def info(self, message, *args, **kwargs):
        with self._lock:
            # 停止後も窓口を残す。機能フラグの確認直後に停止されても安全。
            self._logger.info(message, *args, **kwargs)


def setupLogger(name: str, log_file: str, level: int = logging.INFO) -> logging.Logger:
    """
    特定の名前とログファイルを持つロガーを設定します。
    """
    # ロガーを作成
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # 親ロガーへの伝播を防ぐ

    # filled with 10MB logs
    max_log_size = 10 * 1024 * 1024  # 10MB

    # ハンドラーを作成
    file_handler = TruncatingFileHandler(
        diagnosticLogPath(log_file),
        maxBytes=max_log_size,
        backupCount=0,
        encoding="utf-8",
        delay=True
        )
    file_handler.setLevel(level)

    # フォーマッターを設定
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # ロガーにハンドラーを追加（重複追加を避ける）
    if not any(isinstance(h, RotatingFileHandler) and getattr(h, 'baseFilename', None) == getattr(file_handler, 'baseFilename', None) for h in logger.handlers):
        logger.addHandler(file_handler)

    return logger

process_logger: Optional[logging.Logger] = None

# エンドポイント名にこれらのいずれかが含まれる場合、ログに書き出す値をマスクする
SENSITIVE_ENDPOINT_MARKERS = ("auth_key", "api_key", "password", "token", "secret", "voice_settings", "instructions")


def _isSensitiveEndpoint(endpoint: Any) -> bool:
    if not isinstance(endpoint, str):
        return False
    # ラベル文字列 ("Set OpenRouter Auth Key") とエンドポイント文字列
    # ("/set/data/openrouter_auth_key") の両方で "auth_key" 等のマーカーに
    # ヒットするよう、空白をアンダースコアに正規化してから判定する。
    lowered = endpoint.lower().replace(" ", "_")
    return any(marker in lowered for marker in SENSITIVE_ENDPOINT_MARKERS)


def _maskSensitiveValue(value: Any) -> Any:
    return "***MASKED***" if value not in (None, "") else value


def _maskSensitiveData(data: Any) -> Any:
    """Recursively mask values under dict keys that look like secrets.

    Used for aggregate payloads (e.g. the /run/initialization_complete
    response, which bundles every /get/data/* result including the
    *_auth_key entries into a single dict) where the top-level endpoint
    name itself isn't "sensitive" but individual keys inside the payload
    are. Each dict key is checked with the same normalization as
    _isSensitiveEndpoint, so both endpoint-style keys
    ("/get/data/openrouter_auth_key") and log-label keys are caught.
    """
    if isinstance(data, dict):
        return {
            key: (_maskSensitiveValue(value) if _isSensitiveEndpoint(str(key)) else _maskSensitiveData(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_maskSensitiveData(item) for item in data]
    return data


# Conversation text (chat, transcripts, translations) reaches only the
# explicitly enabled conversation logger, never the always-on diagnostic log.
_CONVERSATION_ENDPOINTS = frozenset({
    "/run/send_message_box", "/run/transcription_send_mic_message",
    "/run/transcription_receive_speaker_message", "/run/transcription_ocr_message",
})
_CONVERSATION_KEYS = frozenset({"message", "original", "translation", "translations", "transliteration", "text"})


def _redactConversation(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: ("***CONVERSATION***" if key in _CONVERSATION_KEYS and value not in (None, "", [], {})
                  else _redactConversation(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_redactConversation(item) for item in data]
    return data


def printLog(log: str, data: Any = None) -> None:
    """Log and print a structured process log message."""
    global process_logger
    if process_logger is None:
        process_logger = setupLogger("process", "process.log", logging.INFO)

    logged_data = _maskSensitiveValue(data) if _isSensitiveEndpoint(log) else data
    if log in _CONVERSATION_ENDPOINTS:
        logged_data = _redactConversation(logged_data)
    response = {
        "status": 348,
        "log": redact_urls(log),
        "data": str(redact_urls(logged_data)),
    }
    process_logger.info(response)
    serialized = json.dumps(response)
    _enqueueLogLine(serialized)
    startup_timing.note(log)

# High-rate pointer data and private captions are IPC only. Final transcript
# persistence is handled by the explicitly enabled message logger, not this
# always-on process diagnostic log.
_UNLOGGED_ENDPOINTS = {"/run/vr_panel_pointer", "/run/realtime_caption", "/run/word_filter"}

# State the UI polls every 0.5-1 s (src-ui/logics/useReceiveRoutes.js). Logging
# each request, result and response added about 12 MB an hour to process.log
# even while idle; the file is truncated at 10 MB, so the polls pushed out the
# startup and error records. Successful polls are not logged; failures are.
POLLED_ENDPOINTS = frozenset({
    "/get/data/ocr_capture_status",
    "/get/data/voice_status",
    "/get/data/voice_route",
    "/get/data/direct_voice_state",
    "/get/data/speech_server_state",
    "/get/data/realtime_asr_state",
    "/get/data/model_download_state",
    "/get/data/model_download_hardware",
})


def isQuietPoll(endpoint: Any, status: int = 200) -> bool:
    """A successful answer to a polled state request, or a volume meter sample, which is not logged."""
    return status == 200 and (endpoint in POLLED_ENDPOINTS or endpoint in _METER_ENDPOINTS)


# The volume meters push one value per audio read (sample rate / 1024 a second
# per meter) while the settings page checks a device: logging each one filled
# the 10 MB process.log in about 17 minutes with a 48 kHz microphone.
_METER_ENDPOINTS = frozenset({"/run/check_mic_volume", "/run/check_speaker_volume"})


def _shapeOf(value: Any, depth: int = 0) -> Any:
    """The types in a value, without the values themselves (for diagnostics)."""
    if depth >= 4:
        return "..."
    if isinstance(value, dict):
        return {str(key): _shapeOf(item, depth + 1) for key, item in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_shapeOf(item, depth + 1) for item in list(value)[:5]] + ([f"... {len(value)} items"] if len(value) > 5 else [])
    return type(value).__name__


def printResponse(status: int, endpoint: str, result: Any = None, *, notification: bool = False) -> None:
    """Log and print a structured response object.

    If JSON serialization fails, record the error and emit a generic error payload.
    """
    global process_logger
    if process_logger is None:
        process_logger = setupLogger("process", "process.log", logging.INFO)

    response = {
        "status": status,
        "endpoint": endpoint,
        "result": result,
    }

    # エンドポイント自体が機微な場合 (/get/data/openrouter_auth_key 等) は
    # result 全体を、そうでない場合 (/run/initialization_complete のような
    # 集約レスポンス) は result 内部を再帰的に走査してマスクする。
    # エンドポイント名だけを見る判定は集約レスポンスに対して機能しないため。
    if _isSensitiveEndpoint(endpoint):
        logged_result = _maskSensitiveValue(result)
    else:
        logged_result = _maskSensitiveData(result)
    if endpoint in _CONVERSATION_ENDPOINTS:
        logged_result = _redactConversation(logged_result)
    logged_response = {**response, "result": redact_urls(logged_result)}
    if endpoint not in _UNLOGGED_ENDPOINTS and not isQuietPoll(endpoint, status):
        process_logger.info(logged_response)  # Log the (possibly masked) response, never the raw secret

    try:
        serialized_response = json.dumps(response, allow_nan=False)
    except Exception as e:
        errorLogging()  # Log the full traceback of the exception
        try:
            # Only the shape: the raw object can hold captions or keys that the
            # normal path above masks or never writes.
            process_logger.error(f"Response for {endpoint} could not be serialized; shape: {_shapeOf(result)}")
            process_logger.error(f"Exception during json.dumps: {e}")
        except Exception:
            pass
        # Fallback generic error payload
        error_json = json.dumps({
            "status": 500,
            "endpoint": endpoint,
            "result": {"error": "Failed to serialize response", "details": str(e)},
        }, allow_nan=False)
        _enqueueResponseLine(error_json)
    else:
        if notification:
            _enqueueResponseLine(serialized_response, *_stdoutDeliveryKeys(status, endpoint, result))
        else:
            _enqueueResponseLine(serialized_response)

error_logger: Optional[logging.Logger] = None


def errorLogging(*, provider=None, status=None) -> None:
    """Keep redacted general tracebacks; omit bodies/chains for provider errors."""
    global error_logger
    exc = sys.exc_info()[1]
    provider = provider if provider is not None else exception_provider(exc)
    if provider is None:
        record = redact_diagnostic_text(traceback.format_exc())
    else:
        if exc is not None:
            exc._vrct_provider = provider
        code = status if status is not None else getattr(exc, "status_code", None)
        if code is None:
            code = getattr(getattr(exc, "response", None), "status_code", None)
        record = {"error": type(exc).__name__ if exc else "ProviderError", "provider": provider}
        if type(code) is int:
            record["status"] = code
        if exc is not None:
            record["frames"] = [f"{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}"
                                for frame in traceback.extract_tb(exc.__traceback__)]
    try:
        if error_logger is None:
            error_logger = setupLogger("error", "error.log", logging.ERROR)
        error_logger.error(record)
    except Exception:
        print(record if isinstance(record, str) else json.dumps(record), flush=True)

if __name__ == "__main__":
    print(getComputeDeviceList())
