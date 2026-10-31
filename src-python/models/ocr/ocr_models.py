"""Find the PP-OCR files the user downloaded through the consented catalog.

RapidOCR downloads any model it is not given a path for, unpinned and into its
own package folder (read-only inside an AppImage, and never consented to). So
the engine only ever starts with explicit paths from here, and
ocr_engine_rapidocr blocks RapidOCR's downloader as a second line of defence.

Layout (owned by models/model_downloads/manager.py):
    <root>/<catalog id>/<revision>/<artifact filename>
The root is `downloaded_models` next to config.json.

PaddleOCR keeps the recogniser's character list in inference.yml
(PostProcess.character_dict). RapidOCR wants a plain text file with one
character per line, so it is derived once into <root>/.ocr-keys/.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from threading import Lock
from typing import Dict, Iterable, List, Tuple

from .ocr_languages import BASE_MODEL_ID, OcrModelSpec

from ..model_downloads.catalog import CATALOG

KEYS_DIRECTORY = ".ocr-keys"
_ENTRIES = {model.id: model for model in CATALOG if model.target == "ocr"}
# (path, size, mtime_ns) -> sha256 verified in this process. Hashing ~31 MB takes
# tens of milliseconds, cheap at start-up but pointless on every language switch.
_verified: Dict[Tuple[str, int, int], str] = {}
_lock = Lock()


class OcrModelsMissing(Exception):
    """Some downloads a language needs are absent or incomplete."""

    def __init__(self, model_ids: Iterable[str]) -> None:
        self.model_ids = tuple(model_ids)
        super().__init__(", ".join(self.model_ids))


class OcrModelsInvalid(Exception):
    """Files exist but do not match the catalog (edited, truncated, replaced)."""


@dataclass(frozen=True)
class OcrModelFiles:
    det: str
    rec: str
    keys: str


def catalogEntry(model_id: str):
    return _ENTRIES.get(model_id)


def isInstalled(root, model_id: str) -> bool:
    """Every file of the download is present with the catalog size (no hashing)."""
    entry = _ENTRIES.get(model_id)
    if entry is None or root is None:
        return False
    directory = Path(root) / entry.id / entry.revision
    for artifact in entry.artifacts:
        path = directory / artifact.filename
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size != artifact.size:
                return False
        except OSError:
            return False
    return True


def missingModels(root, spec: OcrModelSpec) -> List[str]:
    return [model_id for model_id in spec.model_ids if not isInstalled(root, model_id)]


def _verify(path: Path, size: int, sha256: str) -> None:
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _lock:
        if _verified.get(key) == sha256:
            return
    if stat.st_size != size:
        raise OcrModelsInvalid(f"size mismatch: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != sha256:
        raise OcrModelsInvalid(f"hash mismatch: {path.name}")
    with _lock:
        _verified[key] = sha256


def _characters(dict_yml: Path) -> List[str]:
    import yaml  # PyYAML is a RapidOCR dependency.

    with dict_yml.open("r", encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    characters = (document or {}).get("PostProcess", {}).get("character_dict")
    if not isinstance(characters, list) or not characters:
        raise OcrModelsInvalid(f"no character_dict in {dict_yml.name}")
    out = []
    for character in characters:
        character = str(character)
        # One entry per line in RapidOCR's format; a line break inside an entry
        # would silently shift every later index.
        if "\n" in character or "\r" in character:
            raise OcrModelsInvalid(f"unsupported character entry in {dict_yml.name}")
        out.append(character)
    return out


def _keysFile(root: Path, dict_yml: Path, sha256: str) -> Path:
    target = root / KEYS_DIRECTORY / f"{sha256[:32]}.txt"
    if target.is_file() and not target.is_symlink():
        return target
    text = "\n".join(_characters(dict_yml)) + "\n"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".keys-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def resolveModelFiles(root, spec: OcrModelSpec) -> OcrModelFiles:
    """Verified paths for `spec`, or OcrModelsMissing / OcrModelsInvalid."""
    if root is None:
        raise OcrModelsMissing(spec.model_ids)
    root = Path(root)
    missing = missingModels(root, spec)
    if missing:
        raise OcrModelsMissing(missing)
    paths = {}
    for model_id in spec.model_ids:
        entry = _ENTRIES[model_id]
        for artifact in entry.artifacts:
            path = root / entry.id / entry.revision / artifact.filename
            _verify(path, artifact.size, artifact.sha256)
            if model_id == BASE_MODEL_ID and artifact.role == "det":
                paths["det"] = path
            if model_id == spec.rec_model_id and artifact.role in ("rec", "dict"):
                paths[artifact.role] = (path, artifact.sha256)
    rec_path, _ = paths["rec"]
    dict_path, dict_sha = paths["dict"]
    keys = _keysFile(root, dict_path, dict_sha)
    return OcrModelFiles(det=str(paths["det"]), rec=str(rec_path), keys=str(keys))
