"""RapidOCR (ONNX) ラッパー。モデル指定ごとに遅延生成した推論器をキャッシュする。

readtext_bgr(crop) -> [{"text": str, "confidence": float, "left"/"right"/"top"/"bottom": float}, ...]。
EasyOCRラッパーと同じ形を返すので、パイプライン側の扱いは変わらない。
例外は投げず、失敗時は空リストを返してそのtickを飛ばす。

EasyOCRから乗り換えた理由と実測は ocr_languages.py と
docs/details/ocr.md を参照。onnxruntime は faster-whisper が
Silero VAD 用に既に依存しているので、追加される実行時依存はない。
"""

from __future__ import annotations

from threading import Lock
from typing import Dict, List, Optional

import numpy as np

from .ocr_languages import OcrModelSpec, ocr_onnx_threads
from .ocr_models import OcrModelFiles

try:
    from utils import errorLogging, printLog
except Exception:  # pragma: no cover
    def errorLogging():
        import traceback
        print(traceback.format_exc())

    def printLog(*args, **kwargs):
        print(*args, **kwargs)

try:
    from rapidocr import EngineType, LangRec, ModelType, OCRVersion, RapidOCR  # type: ignore
except Exception:  # pragma: no cover
    RapidOCR = None  # type: ignore
    EngineType = LangRec = ModelType = OCRVersion = None  # type: ignore
    errorLogging()


class ImplicitDownloadBlocked(RuntimeError):
    pass


def _blockImplicitDownloads() -> bool:
    """RapidOCR downloads any model or dictionary it lacks a path for. Refuse.

    getReader() always passes explicit paths, so this only fires if a future
    RapidOCR adds another implicit fetch: the reader then fails to load
    (OCR_DISABLED_MODEL_LOAD_FAILED) instead of reaching the network
    without the user's consent.
    """
    try:
        from rapidocr.utils.download_file import DownloadFile  # type: ignore
    except Exception:
        return False

    def refuse(cls, input_params):
        url = getattr(input_params, "file_url", "?")
        raise ImplicitDownloadBlocked(f"RapidOCR tried to download {url}; models must come from consented downloads")

    DownloadFile.run = classmethod(refuse)
    return True


if RapidOCR is not None:
    _blockImplicitDownloads()

# 吹き出しの切り出しは小さい(短辺100px前後のこともある)。RapidOCRの既定は
# 短辺を736pxまで拡大する設定 (limit_type="min") なので、そのままだと7倍に
# 引き伸ばして1枚2秒近くかかる。320に下げると実測で2倍以上速くなり、
# 精度は落ちなかった (95枚で中央値 1778ms -> 790ms)。
DET_LIMIT_SIDE_LEN = 320
# PaddleOCR の PP-OCRv6 det の inference.yml にある正規化 (ImageNet)。RapidOCR の既定
# (0.5/0.5) は同梱モデル用。合成画像ではどちらでも読めたが、配布元の前処理に合わせる。
DET_MEAN = [0.485, 0.456, 0.406]
DET_STD = [0.229, 0.224, 0.225]

_engine_cache: Dict[tuple, object] = {}
_engine_lock = Lock()


def isAvailable() -> bool:
    return RapidOCR is not None


def getReader(spec: OcrModelSpec, files: Optional[OcrModelFiles] = None) -> Optional[object]:
    """モデル指定に対応する推論器を返す。生成に失敗したら None。

    files はダウンロード済みモデルのパス (ocr_models.resolveModelFiles)。無ければ
    推論器は作らない。RapidOCR はパスを渡されないモデルを自分でダウンロードしに行く
    (パッケージのフォルダへ、同意なしで) ので、それを起こさないため。
    """
    if RapidOCR is None or spec is None or files is None:
        return None
    key = (spec, files)
    with _engine_lock:
        cached = _engine_cache.get(key)
        if cached is not None:
            return cached
        try:
            params = {
                # RapidOCRは既定でモデルの読み込み経過をINFOでstderrへ出す。
                # VRCTのstderrはUIのコンソールへ流れて他のログを埋めるので黙らせる。
                "Global.log_level": "error",
                # VRChat の吹き出しは回転しないので向き判定は使わない。ただし RapidOCR
                # 3.9.2 は use_cls=False でも分類器のセッションを作り、パスが無いと
                # ダウンロードする。手元にある検出モデルを指しておけば読み込むだけで済む
                # (推論には一度も使われない)。
                "Global.use_cls": False,
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Cls.engine_type": EngineType.ONNXRUNTIME,
                "Det.model_path": files.det,
                "Cls.model_path": files.det,
                "Rec.model_path": files.rec,
                "Rec.rec_keys_path": files.keys,
                "Det.mean": DET_MEAN,
                "Det.std": DET_STD,
                "Det.ocr_version": OCRVersion(spec.ocr_version),
                "Rec.ocr_version": OCRVersion(spec.ocr_version),
                "Det.model_type": ModelType(spec.model_type),
                "Rec.model_type": ModelType(spec.model_type),
                "Det.limit_side_len": DET_LIMIT_SIDE_LEN,
                # 全コアを使い切らない (ocr_onnx_threads 参照)
                "EngineConfig.onnxruntime.intra_op_num_threads": ocr_onnx_threads(),
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
            if spec.lang_rec:
                params["Rec.lang_type"] = LangRec(spec.lang_rec)
            engine = RapidOCR(params=params)
        except Exception:
            errorLogging()
            printLog(f"OCR engine: could not load {spec.label}")
            return None
        _engine_cache[key] = engine
        return engine


def readtext_bgr(reader: object, crop_bgr: np.ndarray, min_confidence: float = 0.5) -> List[dict]:
    if reader is None or crop_bgr is None or crop_bgr.size == 0:
        return []
    try:
        result = reader(crop_bgr)  # type: ignore[operator]
    except Exception:
        errorLogging()
        return []

    # boxes は ndarray なので or でのフォールバックは使えない (真偽判定が曖昧になる)。
    texts = list(getattr(result, "txts", None) or [])
    scores = list(getattr(result, "scores", None) or [])
    raw_boxes = getattr(result, "boxes", None)
    boxes = [] if raw_boxes is None else list(raw_boxes)
    out: List[dict] = []
    for index, text in enumerate(texts):
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue
        try:
            confidence = float(scores[index]) if index < len(scores) else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < min_confidence:
            continue
        # 行の位置は、行同士をどう繋ぐか (改行か、スペースか、詰めるか) の判断に使う。
        item = {"text": text, "confidence": confidence}
        if index < len(boxes):
            try:
                points = [(float(x), float(y)) for x, y in boxes[index]]
                item["left"] = min(p[0] for p in points)
                item["right"] = max(p[0] for p in points)
                item["top"] = min(p[1] for p in points)
                item["bottom"] = max(p[1] for p in points)
            except (TypeError, ValueError):
                pass
        out.append(item)
    return out
