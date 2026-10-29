"""Path policy shared by PyInstaller collection and final artifact inspection."""

PRIVATE_VOICE_NAMES = frozenset("mia2026" + suffix for suffix in (".pth", ".index", ".zip", ".png"))
MODEL_SUFFIXES = (".onnx", ".pth", ".pt", ".ckpt", ".safetensors", ".gguf", ".bin", ".pdparams", ".pdmodel", ".pdiparams")
ARCHIVE_SUFFIXES = (".zip", ".7z", ".tar", ".tgz", ".tar.gz", ".tar.xz", ".rar")


def violation(name):
    parts = str(name).replace("\\", "/").lower().split("/")
    base = parts[-1]
    if base in PRIVATE_VOICE_NAMES:
        return "Private voice asset"
    ocr = any(part in {"ocr", "ocr_onnx", "rapidocr", "rapidocr_onnxruntime"} for part in parts)
    if base.endswith(MODEL_SUFFIXES) and (ocr or "ocr" in base or base.startswith("chatbox_yolo")):
        return "Restricted OCR model"
    return None


def filter_toc(entries):
    # Hooks may rename destinations: inspect original source paths as well.
    return [entry for entry in entries if not any(violation(name) for name in entry[:2])]
