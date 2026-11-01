"""OCR pipeline orchestrator: capture → candidates → OCR → bubbles → dedup → callback.

Candidates come from a pluggable source (see ocr_detection.py). Without a
detector, the configured region is read whole and PP-OCR's text lines are
grouped into bubbles afterwards. With VRCT-VOX's chatbox detector
(ocr_chatbox_detector.py, built by the caller), each detected chatbox whose
centre lies in the region is read on its own. Models are the user's consented
downloads (ocr_models.py); nothing is fetched here.

Runs in its own thread. The callback signature mirrors mic/speaker
transcript callbacks so Controller.ocrMessage can reuse the same
translation → UI/overlay flow.

Callback payload:
    {
        "text": str,
        "language": str,     # VRCT source language name ("auto" if unknown)
        "is_final": True,
        "segment_id": str,
        "recognition_error": False,
        "source": "ocr",
    }
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import OrderedDict
from threading import Event, Lock, Thread
from typing import Callable, List, Optional

import numpy as np

from ..background_priority import BackgroundThreads, lowerCurrentThread
from .ocr_capture import CAPTURE_OK, CAPTURE_UNAVAILABLE, OcrCapture, probeCapture
from .ocr_detection import FULL_REGION, RegionCandidates, blockBounds, groupLines, looksLikeChatbox, regionPixels
from . import ocr_engine_rapidocr as ocr_engine
from .ocr_languages import OcrModelSpec, resolveModelSpec
from .ocr_models import OcrModelsInvalid, OcrModelsMissing, resolveModelFiles
from errors import ErrorCode, OcrStartError

try:
    from utils import errorLogging, printLog
except Exception:  # pragma: no cover
    def errorLogging():
        import traceback
        print(traceback.format_exc())

    def printLog(*args, **kwargs):
        print(*args, **kwargs)


# Upper bound on how many candidate rectangles get OCR'd in a single tick,
# and how long that OCR work may take before the tick yields.
MAX_CANDIDATES_PER_TICK = 6
TICK_OCR_BUDGET_RATIO = 0.8

# 何も出ないときの原因が「フレームが来ない」「吹き出しが検出されない」
# 「文字が読めない」のどれなのか、ログから区別できなかったので定期的に内訳を出す。
# 実機で「OCRは起動しているのに無言」という状態を3回踏んでいる (2026-09-18)。
STATUS_INTERVAL_SEC = 30.0

# 配送済みの文を覚えておく時間。画面から消えてからこの秒数で忘れる。
# 記憶だけ (時間の上限なし) にすると「はい」「Wow!」のような短い定型文が
# LRUから押し出されるまで二度と表示されなくなる。静かなインスタンスでは
# 何時間もかかるので、時間の上限は要る。一方でユーザーが決める材料は無く、
# 実際に1秒に設定されて同じ文が繰り返し流れたので、設定には出さない。
DEDUP_RETENTION_SEC = 30.0


# 行末がこれらで終わっていれば、折り返しではなく送信者が入れた改行とみなす。
SENTENCE_END_CHARS = ("。", "．", ".", "！", "!", "？", "?", "…", "」", "』", ")", "）")
NEWLINE = chr(10)


def _isLatin(char: str) -> bool:
    """ラテン文字・数字なら True。行を繋ぐときにスペースを入れるかの判断に使う。"""
    return bool(char) and (char.isascii() and (char.isalnum() or char in "\"'"))


def _textHash(text: str) -> str:
    return hashlib.blake2b(text.casefold().encode("utf-8"), digest_size=8).hexdigest()


def _similar(a: str, b: str, max_distance: int = 2) -> bool:
    """Cheap bounded edit-distance check for near-duplicate OCR output.

    OCR jitter across frames flips a character or two, which produces a
    different hash for what a human reads as the same bubble. Comparing with
    a small distance budget catches those without a fuzzy-matching dependency.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > max_distance:
        return False
    # Classic DP, but bail out as soon as the whole row exceeds the budget.
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            ))
        if min(current) > max_distance:
            return False
        previous = current
    return previous[-1] <= max_distance


class _DedupCache:
    """一度配送した吹き出しの文を覚えておき、同じ文は配送しない。

    覚えている間は時間に関係なく抑制する。時間で解禁する方式だと、画面に出続けて
    いる吹き出しでも解禁のたびに同じ文が流れてしまうため (実機で再現、2026-09-18)。

    エントリは「最後に見た時刻」で持ち、見るたびに更新する。つまり保持時間は
    「画面から消えてから」測る。消えて `retention_sec` 経っても現れなければ忘れ、
    その後で同じ文が出たら新しい発言として配送する。
    近い文 (編集距離2以内) も同じ扱いにする。OCRのゆらぎで1〜2文字違うだけの
    同じ吹き出しを別物として配送しないため。
    """

    def __init__(self, max_items: int = 128) -> None:
        self._items: "OrderedDict[str, tuple[float, str, tuple[int, int]]]" = OrderedDict()
        self._max_items = max_items

    def evictStale(self, now: float, retention_sec: float) -> None:
        stale = [k for k, (ts, _, _) in self._items.items() if (now - ts) > retention_sec]
        for k in stale:
            self._items.pop(k, None)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)

    def seen(self, text_hash: str, text: str, now: float) -> bool:
        """覚えていれば True。見た時刻を更新するので、出続けている間は忘れない。"""
        entry = self._items.get(text_hash)
        if entry is not None:
            self._items[text_hash] = (now, text, entry[2])
            self._items.move_to_end(text_hash)
            return True

        for key, (_, prev_text, center) in list(self._items.items()):
            if _similar(text, prev_text):
                self._items[key] = (now, prev_text, center)
                self._items.move_to_end(key)
                return True
        return False

    def record(self, text_hash: str, text: str, bbox_center: tuple, now: float) -> None:
        self._items[text_hash] = (now, text, bbox_center)
        self._items.move_to_end(text_hash)


class OcrPipeline:
    def __init__(
        self,
        callback: Callable[[dict], None],
        source_language: str = "auto",
        window_title: str = "VRChat",
        poll_interval_ms: int = 750,
        min_confidence: float = 0.55,
        min_text_length: int = 2,
        model_root=None,
        region=FULL_REGION,
        chatbox_filter: bool = True,
        detector=None,
        capture_probe: Optional[Callable[[str], str]] = None,
    ) -> None:
        """detector: a candidate source with isAvailable()/loadModel()/detect().

        None (the default) reads the configured region without a detector.
        VRCT-VOX's own detector comes from ocr_chatbox_detector.buildChatboxDetector;
        the upstream one must never be passed (see ocr_chatbox_detector.py).
        """
        self._callback = callback
        self._source_language = source_language or "auto"
        self._window_title = window_title or "VRChat"
        self._poll_interval = max(0.1, poll_interval_ms / 1000.0)
        # Keep OCR work inside a fraction of the poll interval so the loop
        # stays responsive to stop() and does not run back-to-back.
        self._tick_budget = self._poll_interval * TICK_OCR_BUDGET_RATIO
        self._min_confidence = float(min_confidence)
        self._min_text_length = max(1, int(min_text_length))

        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._background_threads: Optional[BackgroundThreads] = None
        self._capture: Optional[OcrCapture] = None
        self._model_root = model_root
        self._region_source = RegionCandidates(region)
        self._detector = detector if detector is not None else self._region_source
        self._chatbox_filter = bool(chatbox_filter)
        self._capture_probe = capture_probe or probeCapture
        self._dedup = _DedupCache()
        self._reader = None
        # 設定変更はここに積んでおき、ワーカースレッドが次のtickの頭で取り込む。
        # 推論器とキャプチャはスレッドに紐づくので、値を書き換える
        # スレッドではなく、使っているスレッドの側で作り直す。
        self._pending: dict = {}
        self._pending_lock = Lock()
        self._counts = {"tick": 0, "frame": 0, "candidate": 0, "ocr": 0, "text": 0, "bubble": 0, "emit": 0}
        self._counts_since = 0.0
        self._last_tick_at = 0.0

    @property
    def detectorName(self) -> str:
        """Which candidate source reads frames ("region" without a detector)."""
        return getattr(self._detector, "name", "custom")

    def isEngineAvailable(self) -> bool:
        # 検出器は必須ではない (無ければ範囲指定+PP-OCRの行検出で読む)。
        return ocr_engine.isAvailable()

    def _readerFor(self, spec: OcrModelSpec):
        """spec のモデルで推論器を作る。ダウンロード済みのファイルだけを使う。

        無い・壊れているときは OcrModelsMissing / OcrModelsInvalid をそのまま投げる。
        """
        files = resolveModelFiles(self._model_root, spec)
        return ocr_engine.getReader(spec, files)

    def start(self) -> bool:
        """モデルを読み込んでからワーカーを起動する。

        起動できなければ理由 (OCR_DISABLED_*) を載せた OcrStartError を投げる。
        モデルはここで読むので、戻った時点で読み取りを始められる。
        """
        if not self.isEngineAvailable():
            printLog("OCR pipeline: engine or opencv unavailable, refusing to start")
            raise OcrStartError(ErrorCode.OCR_DISABLED_ENGINE_UNAVAILABLE)
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop_event.clear()
        spec = resolveModelSpec(self._source_language)
        if spec is None:
            printLog(f"OCR pipeline: language {self._source_language!r} is not supported by the OCR engine")
            raise OcrStartError(ErrorCode.OCR_DISABLED_UNSUPPORTED_LANGUAGE)
        # モデルを読むときに増える onnxruntime のスレッドは、VR UI や VRChat より低い優先度にする
        self._background_threads = BackgroundThreads()
        try:
            self._reader = self._readerFor(spec)
        except OcrModelsMissing as missing:
            printLog(f"OCR pipeline: models not downloaded: {', '.join(missing.model_ids)}")
            self.stop()
            raise OcrStartError(ErrorCode.OCR_DISABLED_MODEL_MISSING)
        except (OcrModelsInvalid, OSError):
            errorLogging()
            self.stop()
            raise OcrStartError(ErrorCode.OCR_DISABLED_MODEL_LOAD_FAILED)
        if self._reader is None:
            printLog(f"OCR pipeline: OCR engine init failed for {spec.label}")
            self.stop()
            raise OcrStartError(ErrorCode.OCR_DISABLED_MODEL_LOAD_FAILED)
        if not self._detector.isAvailable():
            printLog(f"OCR pipeline: detector {getattr(self._detector, 'name', '?')!r} unavailable, reading the region instead")
            self._detector = self._region_source
        try:
            self._detector.loadModel()
        except Exception:
            errorLogging()
            printLog("OCR pipeline: bubble detector model load failed")
            self.stop()
            raise OcrStartError(ErrorCode.OCR_DISABLED_MODEL_LOAD_FAILED)
        capture = self._capture_probe(self._window_title)
        if capture != CAPTURE_OK:
            printLog(f"OCR pipeline: capture not ready ({capture}) for window {self._window_title!r}")
            self.stop()
            raise OcrStartError(ErrorCode.OCR_DISABLED_CAPTURE_UNAVAILABLE if capture == CAPTURE_UNAVAILABLE
                                else ErrorCode.OCR_DISABLED_WINDOW_NOT_FOUND)
        printLog(f"OCR pipeline: started ({spec.label}, candidates={getattr(self._detector, 'name', 'custom')}, "
                 f"region={self._region_source.region}, chatbox_filter={self._chatbox_filter})")
        self._background_threads.lower()
        self._thread = Thread(target=self._run, name="ocr_pipeline", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        th = self._thread
        if th is not None:
            try:
                th.join(timeout=5.0)
            except Exception:
                pass
        self._thread = None
        # _run() closes self._capture itself before exiting — capture
        # backends hold OS resources (GDI DCs, OpenVR handles) tied to the
        # thread that created them, so tearing down from here is unsafe.
        self._capture = None

    def applyConfig(self, settings: dict) -> None:
        """実行中のパイプラインへ設定変更を反映する (OFF→ONを挟まない)。

        呼び出し元(Controller)はUIスレッド側なので、ここでは値を預かるだけ。
        実際の切り替えはワーカースレッドが次のtickの頭で行う。
        """
        if not isinstance(settings, dict) or not settings:
            return
        with self._pending_lock:
            self._pending.update(settings)

    def _applyPending(self) -> None:
        """預かった設定を取り込む。ワーカースレッドからのみ呼ぶこと。"""
        with self._pending_lock:
            if not self._pending:
                return
            pending, self._pending = self._pending, {}

        if "poll_interval_ms" in pending:
            try:
                self._poll_interval = max(0.1, int(pending["poll_interval_ms"]) / 1000.0)
                self._tick_budget = self._poll_interval * TICK_OCR_BUDGET_RATIO
            except (TypeError, ValueError):
                errorLogging()
        if "min_confidence" in pending:
            try:
                self._min_confidence = float(pending["min_confidence"])
            except (TypeError, ValueError):
                errorLogging()
        if "min_text_length" in pending:
            try:
                self._min_text_length = max(1, int(pending["min_text_length"]))
            except (TypeError, ValueError):
                errorLogging()
        if "region" in pending:
            self._region_source.setRegion(pending["region"])
        if "chatbox_filter" in pending:
            self._chatbox_filter = bool(pending["chatbox_filter"])
        if "detector" in pending:
            self._switchDetector(pending["detector"])

        # 言語を変えると使うモデルが変わることがある (auto/日英中+ラテンは同じモデル、
        # ハングル・キリル・タイ等はPP-OCRv5の別モデル)。同じモデルはキャッシュ
        # されているので、一度使った組み合わせへ戻すときは即座に切り替わる。
        language = pending.get("source_language", self._source_language)
        if language != self._source_language:
            spec = resolveModelSpec(language)
            if spec is None:
                printLog(f"OCR pipeline: language {language!r} is not supported, keeping {self._source_language!r}")
            else:
                try:
                    reader = self._readerFor(spec)
                except OcrModelsMissing as missing:
                    printLog(f"OCR pipeline: models for {language!r} not downloaded ({', '.join(missing.model_ids)})")
                    reader = None
                except (OcrModelsInvalid, OSError):
                    errorLogging()
                    reader = None
                if reader is None:
                    printLog(f"OCR pipeline: could not load {spec.label}, keeping {self._source_language!r}")
                else:
                    self._reader = reader
                    self._source_language = language
                    # 言語が変われば同じ吹き出しでも読める内容が変わるので、
                    # 抑制済みの文言を引きずらないようにキャッシュを捨てる。
                    self._dedup = _DedupCache()

        # キャプチャはOSリソースをこのスレッドで掴んでいるので、ここで開き直す。
        window_title = pending.get("window_title")
        if isinstance(window_title, str) and window_title and window_title != self._window_title:
            self._window_title = window_title
            try:
                if self._capture is not None:
                    self._capture.close()
            except Exception:
                errorLogging()
            self._capture = OcrCapture(window_title=self._window_title)

    def _switchDetector(self, detector) -> None:
        """検出器を差し替える (None で範囲読みへ戻す)。ワーカースレッドからのみ呼ぶ。

        起動中の切り替えで読めなくなるのは避けたいので、使えない・読み込めない
        検出器は範囲読みに戻すだけで、OCRは止めない。
        """
        source = detector if detector is not None else self._region_source
        if source is not self._region_source:
            try:
                if not source.isAvailable():
                    printLog(f"OCR pipeline: detector {getattr(source, 'name', '?')!r} unavailable, reading the region instead")
                    source = self._region_source
                else:
                    source.loadModel()
            except Exception:
                errorLogging()
                printLog("OCR pipeline: bubble detector model load failed, reading the region instead")
                source = self._region_source
        if source is not self._detector:
            self._detector = source
            printLog(f"OCR pipeline: candidates={self.detectorName}")

    def _inRegion(self, candidates, frame):
        """検出器の候補のうち、中心が読み取り範囲に入るものだけ残す。

        検出はフレーム全体で行う (学習時と同じ縮尺で推論するため)。範囲の境目に
        かかった吹き出しは切らずに丸ごと読む。
        """
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return candidates
        height, width = shape[:2]
        x, y, w, h = regionPixels(self._region_source.region, width, height)
        if (x, y, w, h) == (0, 0, width, height):
            return candidates
        kept = []
        for candidate in candidates:
            bx, by, bw, bh = candidate[0]
            cx, cy = bx + bw / 2.0, by + bh / 2.0
            if x <= cx < x + w and y <= cy < y + h:
                kept.append(candidate)
        return kept

    def _emit(self, text: str) -> None:
        try:
            self._callback({
                "text": text,
                "language": self._source_language if self._source_language != "auto" else None,
                "is_final": True,
                "segment_id": uuid.uuid4().hex,
                "recognition_error": False,
                "source": "ocr",
            })
        except Exception:
            errorLogging()

    def _run(self) -> None:
        # Capture backends hold OS resources tied to the creating thread,
        # so construct on this thread rather than the one that called start().
        self._capture = OcrCapture(window_title=self._window_title)
        lowerCurrentThread()  # OCR を VR UI や VRChat より先に動かさない
        ticks = 0
        try:
            while not self._stop_event.is_set():
                start_t = time.monotonic()
                try:
                    self._applyPending()
                    self._tick()
                except Exception:
                    errorLogging()
                ticks += 1
                if ticks <= 2 and self._background_threads is not None:
                    # 推論を始めてから作られるスレッドもある
                    self._background_threads.lower()
                elapsed = time.monotonic() - start_t
                sleep_for = self._poll_interval - elapsed
                if sleep_for > 0:
                    self._stop_event.wait(sleep_for)
        finally:
            try:
                self._capture.close()
            except Exception:
                pass

    def _logStatus(self, now: float) -> None:
        """tickの内訳を定期的に出す。無言のときにどこで止まっているかを見るため。"""
        if self._counts_since == 0.0:
            self._counts_since = now
            return
        if (now - self._counts_since) < STATUS_INTERVAL_SEC:
            return
        counts = self._counts
        printLog(
            f"OCR status ({now - self._counts_since:.0f}s): "
            f"tick={counts['tick']} frame={counts['frame']} candidate={counts['candidate']} "
            f"ocr={counts['ocr']} text={counts['text']} bubble={counts['bubble']} emit={counts['emit']} "
            f"lang={self._source_language!r}")
        for key in counts:
            counts[key] = 0
        self._counts_since = now

    def _tick(self) -> None:
        self._counts["tick"] += 1
        self._logStatus(time.monotonic())
        if self._capture is None or self._reader is None:
            return
        frame = self._capture.get()
        if frame is None:
            return
        self._counts["frame"] += 1
        candidates = self._detector.detect(frame)
        if candidates and self._detector is not self._region_source:
            candidates = self._inRegion(candidates, frame)
        if not candidates:
            return
        self._counts["candidate"] += len(candidates)

        # A frame can hold several bubbles at once (and the detector is run
        # recall-first, so a few non-bubbles come through too). Running OCR on
        # all of them would stall the loop for seconds and starve the GPU that
        # whisper is sharing, so only the most confident few — which the
        # detector already sorted first — get an OCR budget on any single tick.
        candidates = candidates[:MAX_CANDIDATES_PER_TICK]

        now = time.monotonic()
        # 保持時間の下限はtick間隔の2倍。1tickはOCR1件あたり約0.8秒かかるので、
        # 保持時間の方が短いと、画面に出続けている吹き出しでも見るたびに忘れられて
        # しまい、同じ文が繰り返し配送される。
        interval = (now - self._last_tick_at) if self._last_tick_at else 0.0
        self._last_tick_at = now
        retention = max(DEDUP_RETENTION_SEC, interval * 2.0)
        self._dedup.evictStale(now, retention)
        deadline = now + self._tick_budget

        splits = getattr(self._detector, "splits_bubbles", False) is True
        for bbox, crop in candidates:
            if self._stop_event.is_set():
                return
            if time.monotonic() > deadline:
                break
            self._counts["ocr"] += 1
            words = ocr_engine.readtext_bgr(self._reader, crop, self._min_confidence)
            if not words:
                continue
            self._counts["text"] += 1
            for block, center in self._bubbles(bbox, crop, words, splits):
                self._counts["bubble"] += 1
                merged = self._mergeWords(block)
                if len(merged) < self._min_text_length:
                    continue
                h = _textHash(merged)
                if self._dedup.seen(h, merged, now):
                    continue
                self._dedup.record(h, merged, center, now)
                self._counts["emit"] += 1
                self._emit(merged)

    def _bubbles(self, bbox, crop, words: List[dict], splits: bool):
        """候補1つ分のOCR行を吹き出しごとに分ける。[(行のリスト, 中心座標), ...]。

        検出器の候補は1つが1吹き出し。検出器なし (範囲読み) は範囲に複数の
        吹き出しやワールドの文字が写るので、行をまとめ直す。どちらも、
        チャットボックスの見た目 (暗い板に明るい文字) でないものを落とす。
        検出器の候補で落ちるのは、実測 (chatbox_lab のval) では消えかけて
        灰色になった吹き出しだけだった。明るいうちに読み終えているので失うものは無い。
        """
        center = (int(bbox[0] + bbox[2] / 2), int(bbox[1] + bbox[3] / 2))
        if not splits:
            if self._chatbox_filter and not looksLikeChatbox(crop, words):
                return []
            return [(words, center)]
        out = []
        for block in groupLines(words):
            if self._chatbox_filter and not looksLikeChatbox(crop, block):
                continue
            bounds = blockBounds(block)
            block_center = center
            if bounds is not None:
                block_center = (int(bbox[0] + bounds[0] + bounds[2] / 2), int(bbox[1] + bounds[1] + bounds[3] / 2))
            out.append((block, block_center))
        return out

    @staticmethod
    def _mergeWords(words: List[dict]) -> str:
        """OCRが返した行を1つの文にまとめる。

        VRChatは「送信者が入れた改行」と「幅による折り返し」を同じように描画し、
        吹き出しの幅も内容に合わせて決まるため、行の位置だけでは区別できない
        (実データで確認: 改行4行のリストも折り返された1文も、どの行も右端まで
        到達していた)。そこで次の順で判断する。

        1. 前の行が文末の記号 (。.!? 等) で終わっていれば改行とみなす
        2. それ以外は折り返しとみなして繋ぐ。ラテン文字が絡む境目はスペース、
           日本語や中国語だけの境目は詰める (「少 しずつ」のような余計な
           スペースを入れないため)

        右端の余白で判定する案も試したが、吹き出しに複数の文字列 (他人の吹き出しと
        ワールドの文字など) が写ると基準がずれて折り返しを改行と誤判定したのでやめた。
        文末記号だけの方が実データでは正確だった。
        """
        lines = [w for w in words if isinstance(w.get("text"), str) and w["text"].strip()]
        if not lines:
            return ""
        if any("top" in w for w in lines):
            lines.sort(key=lambda w: w.get("top", 0.0))
        merged = lines[0]["text"].strip()
        for previous, current in zip(lines, lines[1:]):
            text = current["text"].strip()
            merged += OcrPipeline._lineJoiner(previous, text) + text
        return merged.strip()

    @staticmethod
    def _lineJoiner(previous: dict, next_text: str) -> str:
        previous_text = previous["text"].strip()
        if previous_text.endswith(SENTENCE_END_CHARS):
            return NEWLINE
        if _isLatin(previous_text[-1]) or _isLatin(next_text[:1]):
            return " "
        return ""
