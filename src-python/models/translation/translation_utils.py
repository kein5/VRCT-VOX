"""Pinned CTranslate2 admission, conflict-preserving migration and local tokenizers."""
from os import path as os_path
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Callable
import yaml

from models.builtin_model_pins import MODEL_PINS, tokenizerFilePins
from models.legacy_model_downloads import download_directory, verified_directory
from models.model_downloads.manager import directory
from models.model_downloads.staging import RootLease

# Tokenizer loading is optional; integrity checks do not load native models.
# Transformers takes over a second to import, so it waits for the first
# tokenizer. None means it is not installed, which differs from UNLOADED.
UNLOADED = object()
transformers = UNLOADED


def loadTransformers():
    global transformers
    if transformers is UNLOADED:
        try:
            import transformers as module
        except Exception:
            module = None
        transformers = module
    return transformers


# License metadata is shown next to each weight in Config -> Translation, and
# commercial_use=False weights need an explicit opt-in before they can be
# downloaded or selected (see Controller.setCtranslate2WeightType /
# downloadCtranslate2Weight). Licenses per the Hugging Face model cards
# (2026-10-31): facebook/nllb-200-* and its ct2 conversions are CC-BY-NC-4.0,
# facebook/m2m100_* and the jncraton ct2 conversions are MIT. A conversion
# cannot relax the upstream license, so the upstream (tokenizer) repo decides.
_LICENSE_MIT = {
    "license": "MIT",
    "commercial_use": True,
}
_LICENSE_CC_BY_NC_4_0 = {
    "license": "CC-BY-NC-4.0",
    "commercial_use": False,
}

ctranslate2_weights = {
    "m2m100_418M-ct2-int8": {
        "hf_repo": "jncraton/m2m100_418M-ct2-int8",
        "directory_name": "m2m100_418M-ct2-int8",
        "tokenizer": "facebook/m2m100_418M",
        **_LICENSE_MIT,
    },
    "m2m100_1.2B-ct2-int8": {
        "hf_repo": "jncraton/m2m100_1.2B-ct2-int8",
        "directory_name": "m2m100_1.2B-ct2-int8",
        "tokenizer": "facebook/m2m100_1.2B",
        **_LICENSE_MIT,
    },
    "nllb-200-distilled-600M-ct2-int8": {
        "hf_repo": "JustFrederik/nllb-200-distilled-600M-ct2-int8",
        "directory_name": "nllb-200-distilled-600M-ct2-int8",
        "tokenizer": "facebook/nllb-200-distilled-600M",
        **_LICENSE_CC_BY_NC_4_0,
    },
    "nllb-200-distilled-1.3B-ct2-int8": {
        "hf_repo": "OpenNMT/nllb-200-distilled-1.3B-ct2-int8",
        "directory_name": "nllb-200-distilled-1.3B-ct2-int8",
        "tokenizer": "facebook/nllb-200-distilled-1.3B",
        **_LICENSE_CC_BY_NC_4_0,
    },
    "nllb-200-3.3B-ct2-int8": {
        "hf_repo": "OpenNMT/nllb-200-3.3B-ct2-int8",
        "directory_name": "nllb-200-3.3B-ct2-int8",
        "tokenizer": "facebook/nllb-200-3.3B",
        **_LICENSE_CC_BY_NC_4_0,
    },
}

# Weight used for configurations that have no saved CTRANSLATE2_WEIGHT_TYPE.
# Must allow commercial use. Acquisition still requires model-specific consent.
DEFAULT_CTRANSLATE2_WEIGHT_TYPE = "m2m100_418M-ct2-int8"


def isNonCommercialCTranslate2Weight(weight_type: str) -> bool:
    """True for weights whose license forbids commercial use.

    Unknown weight types return False: they are rejected by the
    CTRANSLATE2_WEIGHT_TYPE descriptor anyway, and treating them as
    restricted would only change which error the caller sees.
    """
    weight = ctranslate2_weights.get(weight_type)
    return weight is not None and weight.get("commercial_use") is False

_LEGACY_DIRECTORIES = {
    "m2m100_418M-ct2-int8": "m2m100_418M",
    "m2m100_1.2B-ct2-int8": "m2m100_12b",
}


def resolveCTranslate2Weight(root: str, weight_type: str, control=None):
    """Prefer the verified current name, retaining and accepting a verified old copy."""
    weight = ctranslate2_weights[weight_type]
    repo = weight["hf_repo"]
    base = Path(root) / "weights" / "ctranslate2"
    names = [weight["directory_name"]]
    if weight_type in _LEGACY_DIRECTORIES:
        names.append(_LEGACY_DIRECTORIES[weight_type])
    for name in names:
        path = base / name
        if verified_directory(path, repo, MODEL_PINS[repo], control):
            return path
    return None


def backwardCompatibleRenameWeightsDir(root: str):
    # Conflicts are retained, even when both copies are valid. Cleanup is separate.
    base = Path(root).absolute() / "weights" / "ctranslate2"
    if not base.exists():
        return
    lease = RootLease(base)
    try:
        directory(base)
        lease.acquire()
        for current, old in _LEGACY_DIRECTORIES.items():
            target, source = base / current, base / old
            if target.exists() or target.is_symlink():
                continue
            repo = ctranslate2_weights[current]["hf_repo"]
            if verified_directory(source, repo, MODEL_PINS[repo]):
                source.rename(target)
    except (OSError, ValueError):
        # A running acquisition owns migration too; availability can use the old name.
        return
    finally:
        lease.close()


def hasCTranslate2WeightFile(root: str, weight_type: str = "m2m100_418M-ct2-int8") -> bool:
    return resolveCTranslate2Weight(root, weight_type) is not None


def checkCTranslate2Weight(root: str, weight_type: str = "m2m100_418M-ct2-int8"):
    return resolveCTranslate2Weight(root, weight_type) is not None


def downloadCTranslate2Weight(root: str, weight_type: str = "m2m100_418M-ct2-int8",
                             callback: Callable = None, end_callback: Callable = None, *, control=None) -> bool:
    try:
        if resolveCTranslate2Weight(root, weight_type, control) is not None:
            return True
        weight = ctranslate2_weights[weight_type]
        repo = weight["hf_repo"]
        return download_directory(Path(root) / "weights" / "ctranslate2", weight["directory_name"],
                                  repo, MODEL_PINS[repo], control, callback)
    finally:
        if end_callback is not None:
            end_callback()


class MissingCTranslate2Tokenizer(FileNotFoundError):
    """The pinned local bundle is unavailable; direct the user to Downloads."""


class CTranslate2TokenizerLoadError(RuntimeError):
    """The pinned bundle is on the disk and verified, but its tokenizer could not be built.

    Fetching the model again cannot help, so this must not send the user to Downloads: the
    files verify, the load fails again, and the review reopens for ever. That is what every
    Windows package up to 0.1.0-beta.7 did, where Transformers could not be imported.
    """


def downloadCTranslate2Tokenizer(path: str, weight_type: str = "m2m100_418M-ct2-int8", *, local_files_only: bool = True):
    # Both families already include their tokenizer assets in the pinned CT2
    # bundle. Never delegate acquisition to Transformers or trust its hub cache.
    weight_path = resolveCTranslate2Weight(path, weight_type)
    if weight_path is None:
        raise MissingCTranslate2Tokenizer(weight_type)
    if loadTransformers() is None:
        raise CTranslate2TokenizerLoadError(weight_type)
    try:
        # Transformers imports the class on first use; a broken package fails here.
        tokenizer_class = (transformers.M2M100Tokenizer if weight_type.startswith("m2m100")
                           else transformers.NllbTokenizerFast)
    except Exception as exc:
        raise CTranslate2TokenizerLoadError(weight_type) from exc
    repo = ctranslate2_weights[weight_type]["hf_repo"]
    pin = MODEL_PINS[repo]
    files = tokenizerFilePins(repo)
    # Transformers also reads optional added_tokens/config files. A private
    # projection prevents unpinned extras in a user's directory being loaded.
    with TemporaryDirectory(prefix="vrct-tokenizer-") as temporary:
        try:
            for name in files:
                copyfile(weight_path / name, Path(temporary) / name)
        except OSError as exc:
            raise MissingCTranslate2Tokenizer(weight_type) from exc
        if not verified_directory(temporary, repo, {"revision": pin["revision"], "files": files}):
            raise MissingCTranslate2Tokenizer(weight_type)
        try:
            return tokenizer_class.from_pretrained(temporary, local_files_only=True)
        except Exception as exc:
            raise CTranslate2TokenizerLoadError(weight_type) from exc


def loadTranslatePromptConfig(root_path: str | None = None, prompt_filename: str | None = None) -> dict:
    # PyInstaller 展開後
    if root_path and prompt_filename and os_path.exists(os_path.join(root_path, "_internal", "translation_settings", "prompt", prompt_filename)):
        prompt_path = os_path.join(root_path, "_internal", "translation_settings", "prompt", prompt_filename)
    # src-python 直下実行
    elif prompt_filename and os_path.exists(os_path.join(os_path.dirname(__file__), "models", "translation", "translation_settings", "prompt", prompt_filename)):
        prompt_path = os_path.join(os_path.dirname(__file__), "models", "translation", "translation_settings", "prompt", prompt_filename)
    # translation フォルダ直下実行
    elif prompt_filename and os_path.exists(os_path.join(os_path.dirname(__file__), "translation_settings", "prompt", prompt_filename)):
        prompt_path = os_path.join(os_path.dirname(__file__), "translation_settings", "prompt", prompt_filename)
    else:
        raise FileNotFoundError(f"Prompt file not found: {prompt_filename}")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# テスト用コード（直接実行時のみ）
if __name__ == "__main__":
    def progress_callback(percent):
        print(f"Download progress: {percent*100:.2f}%")

    def end_callback():
        print("Download finished.")

    root = "./"  # 必要に応じてパスを変更
    # for weight_type in ctranslate2_weights.keys():
    #     print(f"Testing download for: {weight_type}")
    #     downloadCTranslate2Weight(root, weight_type, callback=progress_callback, end_callback=end_callback)
    #     result = checkCTranslate2Weight(root, weight_type)
    #     print(f"Model loadable: {result}")
    #     break
    # downloadCTranslate2Tokenizer(root, "m2m100_418M-ct2-int8")

    # model download test
    downloadCTranslate2Weight(root, "nllb-200-distilled-1.3B", callback=progress_callback, end_callback=end_callback)
    result = checkCTranslate2Weight(root, "nllb-200-distilled-1.3B")
    print(f"Model loadable: {result}")
