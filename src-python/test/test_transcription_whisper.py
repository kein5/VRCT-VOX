"""Whisper downloads and admission use tiny local pins; no model or network."""
import hashlib
import io
from unittest.mock import Mock

import pytest

from models import legacy_model_downloads as downloads
from models.transcription import transcription_whisper as whisper


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    bodies = {"model.bin": b"weights", "tokenizer.json": b"tokenizer"}
    repo = whisper._MODELS["base"]
    pin = {"revision": "a" * 40, "files": {
        name: (len(body), hashlib.sha256(body).hexdigest()) for name, body in bodies.items()
    }}
    monkeypatch.setitem(whisper.MODEL_PINS, repo, pin)
    requests = []

    def transport(url, **kwargs):
        requests.append((url, kwargs))
        return io.BytesIO(bodies[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(downloads, "open_public", transport)
    return tmp_path, bodies, pin, requests


def test_downloads_full_pinned_set_and_settles_already_present_shortcut(pinned):
    root, bodies, pin, requests = pinned
    end = Mock()
    for _ in range(2):
        assert whisper.downloadWhisperWeight(root, "base", end_callback=end)
    assert end.call_count == 2
    assert len(requests) == len(bodies)
    for url, options in requests:
        assert f"/resolve/{pin['revision']}/" in url
        assert options["timeout"] == 60
    assert whisper.checkWhisperWeight(root, "base")


def test_invalid_existing_bytes_are_never_loaded_or_deleted(pinned, monkeypatch):
    root, bodies, _, requests = pinned
    path = root / "weights/whisper/base"
    path.mkdir(parents=True)
    for name, body in bodies.items():
        (path / name).write_bytes(b"x" * len(body))
    loader = Mock()
    monkeypatch.setattr(whisper, "WhisperModel", loader)
    assert not whisper.checkWhisperWeight(root, "base")
    with pytest.raises(FileNotFoundError):
        whisper.getWhisperModel(root, "base")
    loader.assert_not_called()
    assert not requests
    assert (path / "model.bin").read_bytes() == b"x" * len(bodies["model.bin"])


def test_load_uses_verified_local_bundle_and_rejects_tamper(pinned, monkeypatch):
    root, bodies, _, _ = pinned
    assert whisper.downloadWhisperWeight(root, "base")
    loader = Mock()
    monkeypatch.setattr(whisper, "WhisperModel", loader)
    whisper.getWhisperModel(root, "base", compute_type="int8")
    assert loader.call_args.kwargs["local_files_only"] is True
    (root / "weights/whisper/base/tokenizer.json").write_bytes(b"tamper")
    with pytest.raises(FileNotFoundError):
        whisper.getWhisperModel(root, "base", compute_type="int8")
    assert loader.call_count == 1


def test_exception_still_calls_end_once_and_never_admits(pinned, monkeypatch):
    root, _, _, _ = pinned
    end = Mock()
    monkeypatch.setattr(downloads, "open_public", Mock(side_effect=RuntimeError("transport failed")))
    with pytest.raises(RuntimeError):
        whisper.downloadWhisperWeight(root, "base", end_callback=end)
    end.assert_called_once()
    assert not whisper.checkWhisperWeight(root, "base")
