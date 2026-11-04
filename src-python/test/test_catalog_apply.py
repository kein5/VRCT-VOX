"""Apply/shutdown races with tiny files, fake transport and gated verification."""

import ast
import copy
import hashlib
import io
from pathlib import Path
from threading import Barrier, Event, RLock, Thread
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from models.model_downloads.catalog import Artifact, Model, SPEECH_FIELDS
from models.model_downloads.manager import Downloads
from models.model_downloads import manager as downloads_module


@pytest.fixture
def ready(tmp_path):
    content = b"GGUF test bytes"
    artifact = Artifact("model.gguf", len(content), hashlib.sha256(content).hexdigest(), "model")
    entry = Model("test-model", "japanese", "Test", "Author", "author/model", "a" * 40,
                  "MIT", (), "irodori", (artifact,))
    manager = Downloads(tmp_path / "models", catalog=(entry,),
                        transport=lambda _: io.BytesIO(content), reserve_bytes=0)
    request = {"id": entry.id, "consent": True, "catalog_version": manager.catalog_version}
    manager.start(request)
    manager.thread.join(2)
    assert not manager.thread.is_alive()
    job = manager.state()["jobs"][entry.id]
    assert job["phase"] == "ready"
    yield manager, entry, job, request
    assert manager.close()


@pytest.fixture
def run_thread():
    threads = []

    def run(fn):
        result, errors, done = [], [], Event()

        def work():
            try:
                result.append(fn())
            except Exception as error:
                errors.append(error)
            finally:
                done.set()

        thread = Thread(target=work, daemon=True)
        threads.append(thread)
        thread.start()
        return SimpleNamespace(result=result, errors=errors, done=done)

    yield run
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()


@pytest.fixture
def verification_gate(ready, monkeypatch):
    manager, _, _, _ = ready
    original = manager._verify
    entered, release = Event(), Event()
    tokens = []

    def verify(path, artifact, event):
        tokens.append(event)
        entered.set()
        assert release.wait(3), "verification was not released"
        original(path, artifact, event)

    monkeypatch.setattr(manager, "_verify", verify)
    yield entered, release, tokens
    release.set()


def assert_error(work, code):
    assert work.done.wait(2)
    assert not work.result
    assert len(work.errors) == 1
    assert isinstance(work.errors[0], ValueError)
    assert str(work.errors[0]) == code


def test_normal_apply_reverifies_and_applies_once(ready):
    manager, entry, job, _ = ready
    callback = Mock()
    state = manager.apply(entry.id, job["job_id"], callback)
    callback.assert_called_once_with(entry, job["paths"])
    assert state["jobs"][entry.id]["phase"] == "applied"
    with pytest.raises(ValueError, match="download_not_ready"):
        manager.apply(entry.id, job["job_id"], callback)
    assert callback.call_count == 1


@pytest.mark.parametrize("timeout", [0, 0.05])
def test_close_bounds_wait_and_cancels_apply_hashing(ready, run_thread, verification_gate, timeout):
    manager, entry, job, request = ready
    entered, release, tokens = verification_gate
    callback = Mock()
    applying = run_thread(lambda: manager.apply(entry.id, job["job_id"], callback))
    assert entered.wait(1)
    begun = time.monotonic()
    closing = run_thread(lambda: manager.close(timeout))
    assert closing.done.wait(timeout + 0.2), "close waited for blocked hashing"
    assert time.monotonic() - begun < timeout + 0.25
    assert closing.result == [False] and not closing.errors
    assert tokens[0].is_set()
    callback.assert_not_called()
    with pytest.raises(ValueError, match="downloads_closed"):
        manager.start(request)
    release.set()
    assert_error(applying, "downloads_closed")
    terminal = manager.state()["jobs"][entry.id]
    assert terminal["phase"] == "cancelled" and terminal["paths"] == {}
    assert terminal["error_code"] is None
    callback.assert_not_called()
    assert manager.close(timeout=0)


def test_close_waits_for_cooperative_hash_cancellation(ready, monkeypatch, run_thread):
    manager, entry, job, _ = ready
    entered = Event()
    original = manager._verify

    def verify(path, artifact, event):
        entered.set()
        assert event.wait(2)
        original(path, artifact, event)

    monkeypatch.setattr(manager, "_verify", verify)
    callback = Mock()
    applying = run_thread(lambda: manager.apply(entry.id, job["job_id"], callback))
    assert entered.wait(1)
    assert manager.close(timeout=1)
    assert_error(applying, "downloads_closed")
    callback.assert_not_called()


def test_close_stops_hash_updates_at_the_next_chunk(ready, monkeypatch, run_thread):
    manager, entry, job, _ = ready
    entered, release = Event(), Event()
    original = hashlib.sha256
    blocks = []

    class SlowDigest:
        def __init__(self):
            self.digest = original()

        def update(self, block):
            blocks.append(block)
            self.digest.update(block)
            entered.set()
            assert release.wait(2)

        def hexdigest(self):
            return self.digest.hexdigest()

    monkeypatch.setattr(downloads_module, "CHUNK", 4)
    monkeypatch.setattr(downloads_module.hashlib, "sha256", SlowDigest)
    callback = Mock()
    applying = run_thread(lambda: manager.apply(entry.id, job["job_id"], callback))
    try:
        assert entered.wait(1)
        closing = run_thread(lambda: manager.close(timeout=0))
        assert closing.done.wait(0.25)
        assert closing.result == [False] and not closing.errors
    finally:
        release.set()
    assert_error(applying, "downloads_closed")
    assert blocks == [b"GGUF"]
    callback.assert_not_called()


@pytest.mark.parametrize("read_error", [False, True])
def test_close_is_rechecked_even_if_verifier_misses_cancellation(ready, monkeypatch, read_error):
    manager, entry, job, _ = ready

    def verify(*_):
        assert not manager.close(timeout=0)
        if read_error:
            raise OSError("read interrupted")

    monkeypatch.setattr(manager, "_verify", verify)
    callback = Mock()
    with pytest.raises(ValueError, match="downloads_closed"):
        manager.apply(entry.id, job["job_id"], callback)
    callback.assert_not_called()
    assert manager.state()["jobs"][entry.id]["phase"] == "cancelled"


def test_apply_reserves_single_job_and_cancel_has_terminal_state(ready, run_thread, verification_gate):
    manager, entry, job, request = ready
    entered, release, _ = verification_gate
    callback = Mock()
    applying = run_thread(lambda: manager.apply(entry.id, job["job_id"], callback))
    assert entered.wait(1)
    # State and cancellation remain available while verification is blocked.
    assert manager.state()["jobs"][entry.id]["phase"] == "verifying"
    with pytest.raises(ValueError, match="download_not_ready"):
        manager.apply(entry.id, job["job_id"], callback)
    with pytest.raises(ValueError, match="download_busy"):
        manager.start(request)
    manager.cancel(entry.id, job["job_id"])
    release.set()
    assert_error(applying, "download_not_ready")
    assert manager.state()["jobs"][entry.id]["phase"] == "cancelled"
    callback.assert_not_called()
    # Explicit cancellation does not close the manager or remove verified files.
    manager.start(request)
    manager.thread.join(2)
    assert manager.state()["jobs"][entry.id]["phase"] == "ready"


@pytest.mark.parametrize("change,code", [("replace", "stale_job"), ("phase", "download_not_ready")])
def test_apply_rechecks_job_after_verification(ready, run_thread, verification_gate, change, code):
    manager, entry, job, _ = ready
    entered, release, _ = verification_gate
    callback = Mock()
    applying = run_thread(lambda: manager.apply(entry.id, job["job_id"], callback))
    assert entered.wait(1)
    with manager.lock:
        if change == "replace":
            manager.jobs[entry.id] = dict(job, job_id="replacement")
        else:
            manager.jobs[entry.id]["phase"] = "failed"
        expected = copy.deepcopy(manager.jobs[entry.id])
    release.set()
    assert_error(applying, code)
    assert manager.state()["jobs"][entry.id] == expected
    callback.assert_not_called()


def test_close_signals_before_waiting_for_state_lock(ready, run_thread):
    manager, entry, job, request = ready
    with manager.lock:
        closing = run_thread(lambda: manager.close(timeout=0.05))
        assert closing.done.wait(0.25)
        assert closing.result == [False] and not closing.errors
        assert manager.cancel_event.is_set()
    with pytest.raises(ValueError, match="downloads_closed"):
        manager.start(request)
    with pytest.raises(ValueError, match="downloads_closed"):
        manager.apply(entry.id, job["job_id"], Mock())


def test_apply_committed_before_close_finishes_once(ready, run_thread):
    manager, entry, job, _ = ready
    committed, release = Event(), Event()
    paths = []

    def callback(_, saved):
        paths.append(saved)
        committed.set()
        assert release.wait(2)

    applying = run_thread(lambda: manager.apply(entry.id, job["job_id"], callback))
    try:
        assert committed.wait(1)
        closing = run_thread(lambda: manager.close(timeout=0))
        assert closing.done.wait(0.25)
        assert closing.result == [False] and not closing.errors
    finally:
        release.set()
    assert applying.done.wait(1) and not applying.errors
    assert manager.close()
    assert paths == [job["paths"]]
    assert manager.state()["jobs"][entry.id]["phase"] == "applied"


@pytest.mark.parametrize("attempt", range(10))
def test_simultaneous_apply_and_close_have_one_outcome(ready, run_thread, attempt):
    manager, entry, job, _ = ready
    barrier = Barrier(2)
    callback = Mock()

    def apply():
        barrier.wait(timeout=2)
        return manager.apply(entry.id, job["job_id"], callback)

    def close():
        barrier.wait(timeout=2)
        return manager.close(timeout=1)

    applying = run_thread(apply)
    closing = run_thread(close)
    assert applying.done.wait(2) and closing.done.wait(2)
    assert not closing.errors and closing.result == [True]
    phase = manager.state()["jobs"][entry.id]["phase"]
    if applying.errors:
        assert_error(applying, "downloads_closed")
        assert phase in ("ready", "cancelled")
        callback.assert_not_called()
    else:
        assert phase == "applied"
        callback.assert_called_once_with(entry, job["paths"])


@pytest.fixture
def controller_methods():
    # Execute the unchanged endpoint bodies without importing runtime services.
    source = Path(__file__).resolve().parents[1] / "controller.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Controller")
    names = {"_modelDownloadFailure", "_modelDownloadRequest", "applyModelDownload", "shutdown"}
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"copy": copy, "SPEECH_DOWNLOAD_FIELDS": SPEECH_FIELDS}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("change,code", [("settings", "settings_changed"), ("state", "model_target_busy")])
def test_controller_rechecks_settings_and_target_after_hashing(
    ready, run_thread, verification_gate, controller_methods, change, code
):
    manager, entry, job, _ = ready
    entered, release, _ = verification_gate
    controller = controller_methods["Controller"]()
    controller.model_downloads = manager
    controller._speech_settings_lock = RLock()
    controller._speech_settings = {"profiles": {"japanese": {"model": "/old", "device": "cpu"}}}
    controller._config = SimpleNamespace(SPEECH_SERVER_SETTINGS=copy.deepcopy(controller._speech_settings))
    states = {"japanese": {"state": "stopped"}}
    controller.speech_servers = SimpleNamespace(state=lambda: states)
    request = {"id": entry.id, "job_id": job["job_id"], "expected": {"model": "/old"}}
    applying = run_thread(lambda: controller.applyModelDownload(request))
    assert entered.wait(1)
    with controller._speech_settings_lock:
        if change == "settings":
            controller._speech_settings["profiles"]["japanese"]["model"] = "/changed"
        else:
            states["japanese"]["state"] = "ready"
    release.set()
    assert applying.done.wait(1) and not applying.errors
    assert applying.result == [{"status": 409, "result": {"error_code": code}}]
    assert controller._config.SPEECH_SERVER_SETTINGS["profiles"]["japanese"]["model"] == "/old"
    assert manager.state()["jobs"][entry.id]["phase"] == "ready"


def test_shutdown_closes_manager_before_waiting_for_other_services(ready, controller_methods):
    manager, _, _, _ = ready

    class ReachedOcrLock(Exception):
        pass

    class OcrLock:
        def __enter__(self):
            assert manager.closed
            raise ReachedOcrLock()

        def __exit__(self, *args):
            pass

    controller_methods["_OCR_CONTROL_LOCK"] = OcrLock()
    # shutdown() first revokes message delivery (PR #118); nothing else is needed here.
    controller_methods["model"] = SimpleNamespace(message_delivery=SimpleNamespace(revoke=lambda source: None))
    controller = controller_methods["Controller"]()
    controller.model_downloads = manager
    with pytest.raises(ReachedOcrLock):
        controller.shutdown()
