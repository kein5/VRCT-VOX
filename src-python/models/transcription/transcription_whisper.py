"""Helpers for downloading and loading Whisper (faster-whisper) models.

This module exposes small utilities used by the transcription subsystem:
- checkWhisperWeight: quick local availability check
- downloadWhisperWeight: download model artifacts from HF hub
- getWhisperModel: construct and return a WhisperModel instance

The functions are defensive: failures are caught and reported by the caller.
"""

from os import path as os_path
from typing import Callable, Optional
import logging
from utils import getBestComputeType
from models.builtin_model_pins import MODEL_PINS
from models.legacy_model_downloads import download_directory, verified_directory

# Model loading is optional; integrity checks do not load native models.
# faster_whisper also imports av and huggingface_hub, so it waits for the first
# model. None means it is not installed, which differs from _UNLOADED.
_UNLOADED = object()
WhisperModel = _UNLOADED


def _loadWhisperModelClass():
    global WhisperModel
    if WhisperModel is _UNLOADED:
        try:
            from faster_whisper import WhisperModel as model_class
        except Exception:
            model_class = None
        WhisperModel = model_class
    return WhisperModel


logger = logging.getLogger('faster_whisper')
logger.setLevel(logging.CRITICAL)

_MODELS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo-int8": "Zoont/faster-whisper-large-v3-turbo-int8-ct2", #794MB
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2", #1.58GB
}

def checkWhisperWeight(root: str, weight_type: str) -> bool:
    """Admit only the complete pinned artifact set; old load-only caches do not count."""
    repo = _MODELS[weight_type]
    return verified_directory(os_path.join(root, "weights", "whisper", weight_type), repo, MODEL_PINS[repo])


def downloadWhisperWeight(
    root: str,
    weight_type: str,
    callback: Optional[Callable[[float], None]] = None,
    end_callback: Optional[Callable[[], None]] = None,
    *,
    control=None,
) -> bool:
    try:
        repo = _MODELS[weight_type]
        return download_directory(os_path.join(root, "weights", "whisper"), weight_type,
                                  repo, MODEL_PINS[repo], control, callback)
    finally:
        if callable(end_callback):
            end_callback()


def getWhisperModel(
    root: str,
    weight_type: str,
    device: str = "cpu",
    device_index: int = 0,
    compute_type: str = "auto",
):
    """Return a `WhisperModel` instance loaded from local weights.

    Raises:
        ValueError: when VRAM shortage is detected (wrapped from RuntimeError)
        Exception: other loading errors are propagated.
    """
    if _loadWhisperModelClass() is None:
        raise RuntimeError("faster_whisper is not installed")
    path = os_path.join(root, "weights", "whisper", weight_type)
    if not checkWhisperWeight(root, weight_type):
        raise FileNotFoundError("Whisper weights need a verified download")
    if compute_type == "auto":
        compute_type = getBestComputeType(device, device_index)
    try:
        model = WhisperModel(
            path,
            device=device,
            device_index=device_index,
            compute_type=compute_type,
            cpu_threads=4,
            num_workers=1,
            local_files_only=True,
        )
        return model
    except RuntimeError as e:
        # Detect VRAM out-of-memory-like errors and raise a clear ValueError
        error_message = str(e)
        if "CUDA out of memory" in error_message or "CUBLAS_STATUS_ALLOC_FAILED" in error_message:
            raise ValueError("VRAM_OUT_OF_MEMORY", error_message)
        raise

if __name__ == "__main__":
    def callback(value):
        print(value)
        pass

    def end_callback():
        print("end")
        pass

    downloadWhisperWeight("./", "tiny", callback, end_callback)
    downloadWhisperWeight("./", "base", callback, end_callback)
    downloadWhisperWeight("./", "small", callback, end_callback)
    downloadWhisperWeight("./", "medium", callback, end_callback)
    downloadWhisperWeight("./", "large-v1", callback, end_callback)
    downloadWhisperWeight("./", "large-v2", callback, end_callback)
    downloadWhisperWeight("./", "large-v3", callback, end_callback)