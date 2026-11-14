"""Offline transactions: tiny pinned bytes, fake bodies, and real local OS leases."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread

import pytest

from models import legacy_model_downloads as downloads
from models.model_downloads.manager import Cancelled

# Upper bounds for things that happen at once on a fast PC. A slow CI runner needs more,
# and every wait returns as soon as the thing happens, so a generous bound costs nothing.
# owner.wait() past its bound cancels the job, which turned a slow pass into a failure.
WAIT = 10


@pytest.fixture
def bundle():
    bodies = {"model.bin": b"model bytes", "tokenizer.json": b"tokenizer bytes"}
    pin = {"revision": "a" * 40, "files": {
        name: (len(body), hashlib.sha256(body).hexdigest()) for name, body in bodies.items()
    }}
    return bodies, pin


def write_bundle(path, bodies):
    path.mkdir(parents=True)
    for name, body in bodies.items():
        (path / name).write_bytes(body)
    return path


def fake_transport(bodies):
    return lambda url: io.BytesIO(bodies[url.rsplit("/", 1)[-1]])


def test_old_load_success_cache_and_wrong_manifest_are_not_admission(tmp_path, bundle, monkeypatch):
    bodies, pin = bundle
    path = write_bundle(tmp_path / "model", bodies)
    marker = path / downloads.MARKER
    marker.write_text(json.dumps({"verified_files": {"model.bin": {"size": 11, "mtime": 0}}}))
    calls = []
    verify = downloads.verify_file

    def record(*args):
        calls.append(args[0].name)
        return verify(*args)

    monkeypatch.setattr(downloads, "verify_file", record)
    assert downloads.verified_directory(path, "owner/model", pin)
    assert calls == list(bodies)
    assert downloads.verified_directory(path, "owner/model", pin)
    assert calls == list(bodies)  # Exactly once for unchanged files and manifest.
    other = {**pin, "revision": "b" * 40}
    assert downloads.verified_directory(path, "owner/model", other)
    assert calls == list(bodies) * 2
    changed = {**other, "files": {**pin["files"], "model.bin": (11, "0" * 64)}}
    assert not downloads.verified_directory(path, "owner/model", changed)
    assert (path / "model.bin").read_bytes() == bodies["model.bin"]


def test_mismatched_existing_files_are_preserved_and_never_admitted(tmp_path, bundle):
    bodies, pin = bundle
    path = write_bundle(tmp_path / "model", {**bodies, "model.bin": b"bad"})
    assert not downloads.verified_directory(path, "owner/model", pin)
    assert (path / "model.bin").read_bytes() == b"bad"
    assert downloads.download_directory(tmp_path, "model", "owner/model", pin,
                                        transport=fake_transport(bodies))
    preserved = list(tmp_path.glob(".preserved-model-*"))
    assert len(preserved) == 1 and (preserved[0] / "model.bin").read_bytes() == b"bad"
    assert downloads.verified_directory(path, "owner/model", pin)


@pytest.mark.skipif(sys.platform == "win32", reason=(
    "Windows st_ctime is the creation time, not the inode change time; a same-size rewrite "
    "that restores mtime keeps the receipt until the file is re-verified"))
def test_same_size_rewrite_invalidates_receipt_even_with_restored_mtime(tmp_path, bundle):
    import os
    bodies, pin = bundle
    path = write_bundle(tmp_path / "model", bodies)
    assert downloads.verified_directory(path, "owner/model", pin)
    target = path / "model.bin"
    before = target.stat()
    target.write_bytes(b"x" * len(bodies["model.bin"]))
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert not downloads.verified_directory(path, "owner/model", pin)


def test_full_bundle_required_before_publication(tmp_path, bundle):
    bodies, pin = bundle
    with pytest.raises(ValueError, match="size_mismatch"):
        downloads.download_directory(tmp_path, "model", "owner/model", pin,
            transport=fake_transport({**bodies, "tokenizer.json": b"bad"}))
    assert not (tmp_path / "model").exists()
    assert not list(tmp_path.glob(".partial-*"))


def test_oversized_stream_never_writes_beyond_pin(tmp_path):
    control = downloads.DownloadControl()
    artifact = downloads._artifacts({"files": {"model.bin": (4, "0" * 64)}})[0]
    reads = []

    class Oversized(io.BytesIO):
        def read(self, size):
            reads.append(size)
            return b"x" * 64  # Even a misbehaving transport cannot write this.

    target = tmp_path / "private"
    with pytest.raises(ValueError, match="size_mismatch"):
        downloads.stream_artifact("fake", target, artifact, control, transport=lambda _: Oversized())
    assert target.stat().st_size == 0
    assert reads == [5]


class Stalled(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.entered, self.aborted = Event(), Event()

    def read(self, size):
        self.entered.set()
        assert self.aborted.wait(3), "body must be interrupted by its owner"
        return b""

    def abort(self):
        self.aborted.set()


def test_total_deadline_interrupts_a_stalled_stream_and_cleans_staging(tmp_path, bundle):
    _, pin = bundle
    body = Stalled()
    with pytest.raises(TimeoutError, match="download_deadline"):
        downloads.download_directory(tmp_path, "model", "owner/model", pin,
                                     transport=lambda _: body, timeout=0.05)
    assert body.aborted.is_set()
    assert not (tmp_path / "model").exists()
    assert not list(tmp_path.glob(".partial-*"))


def test_slow_trickle_obeys_total_deadline(tmp_path, bundle):
    import time
    bodies, pin = bundle

    class Trickle(Stalled):
        def read(self, size):
            time.sleep(0.01)
            return b"m"

    with pytest.raises(TimeoutError, match="download_deadline"):
        downloads.download_directory(tmp_path, "model", "owner/model", pin,
                                     transport=lambda _: Trickle(), timeout=0.03)
    assert not (tmp_path / "model").exists()


def test_shutdown_cancels_and_joins_running_download_once(tmp_path, bundle):
    _, pin = bundle
    owner, body, results = downloads.LegacyDownloads(), Stalled(), []
    thread = owner.start(("whisper", "base"),
        lambda control: downloads.download_directory(tmp_path, "model", "owner/model", pin, control,
                                                      transport=lambda _: body),
        lambda *result: results.append(result))
    assert body.entered.wait(WAIT)
    assert owner.close(timeout=WAIT)
    assert not thread.is_alive()
    assert results == [(False, "cancelled")]
    assert not list(tmp_path.glob(".partial-*"))
    assert not (tmp_path / "model").exists()
    with pytest.raises(ValueError, match="downloads_closed"):
        owner.start("other", lambda _: True, lambda *_: None)


def test_same_weight_request_is_rejected_while_owned_and_retry_joins(tmp_path, bundle):
    bodies, pin = bundle
    owner, body = downloads.LegacyDownloads(), Stalled()
    results = []
    owner.start("base", lambda control: downloads.download_directory(
        tmp_path, "model", "owner/model", pin, control, transport=lambda _: body),
        lambda *result: results.append(result))
    assert body.entered.wait(WAIT)
    with pytest.raises(ValueError, match="download_busy"):
        owner.start("base", lambda _: pytest.fail("duplicate started"), lambda *_: None)
    assert owner.stop("base", timeout=WAIT)
    owner.start("base", lambda control: downloads.download_directory(
        tmp_path, "model", "owner/model", pin, control, transport=fake_transport(bodies)),
        lambda *result: results.append(result))
    assert owner.wait("base", timeout=WAIT)
    assert results == [(False, "cancelled"), (True, None)]
    assert (tmp_path / "model/model.bin").read_bytes() == bodies["model.bin"]


def test_two_independent_downloaders_cannot_touch_each_others_staging(tmp_path, bundle):
    bodies, pin = bundle
    entered, release, errors = Event(), Event(), []

    class Paused(io.BytesIO):
        def read(self, size):
            entered.set()
            assert release.wait(2)
            return super().read(size)

    def first():
        try:
            downloads.download_directory(tmp_path, "model", "owner/model", pin,
                transport=lambda url: Paused(bodies[url.rsplit("/", 1)[-1]]))
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=first)
    thread.start()
    try:
        assert entered.wait(WAIT)
        staging = list(tmp_path.glob(".partial-*"))
        with pytest.raises(ValueError, match="download_busy"):
            downloads.download_directory(tmp_path, "model", "owner/model", pin,
                transport=lambda _: pytest.fail("second downloader reached transport"))
        assert list(tmp_path.glob(".partial-*")) == staging
    finally:
        release.set()
        thread.join(2)
    assert not errors and not thread.is_alive()
    assert (tmp_path / "model/model.bin").read_bytes() == bodies["model.bin"]


def test_root_lease_is_interprocess(tmp_path, bundle):
    _, pin = bundle
    source = Path(__file__).resolve().parents[2] / "src-python"
    code = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "from models.model_downloads.staging import RootLease; "
        "lease = RootLease(Path(sys.argv[2])); lease.acquire(); "
        "print('held', flush=True); sys.stdin.read(1); lease.close()"
    )
    child = subprocess.Popen([sys.executable, "-B", "-c", code, str(source), str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        with pytest.raises(ValueError, match="download_busy"):
            downloads.download_directory(tmp_path, "model", "owner/model", pin,
                                         transport=lambda _: pytest.fail("lease bypassed"))
    finally:
        child.communicate("x", timeout=3)
    assert child.returncode == 0


def test_cancel_before_publication_preserves_existing_directory(tmp_path, bundle):
    bodies, pin = bundle
    original = write_bundle(tmp_path / "model", {"model.bin": b"user file"})
    control = downloads.DownloadControl()

    def progress(_):
        control.cancel()

    with pytest.raises(Cancelled):
        downloads.download_directory(tmp_path, "model", "owner/model", pin, control, progress,
                                     transport=fake_transport(bodies))
    assert (original / "model.bin").read_bytes() == b"user file"
    assert not list(tmp_path.glob(".partial-*"))


@pytest.mark.parametrize("outcome", [True, False, "exception"])
def test_owner_always_delivers_one_terminal_result(outcome):
    results = []
    owner = downloads.LegacyDownloads()

    def operation(_):
        if outcome == "exception":
            raise RuntimeError("private transport details")
        return outcome

    owner.start("weight", operation, lambda *result: results.append(result))
    assert owner.wait("weight", timeout=WAIT)
    assert results == [(True, None) if outcome is True else
                       (False, "verification_failed" if outcome is False else "download_failed")]


def test_uninterruptible_open_is_reported_pending_then_cannot_publish(tmp_path, bundle):
    bodies, pin = bundle
    entered, release, results = Event(), Event(), []
    owner = downloads.LegacyDownloads()

    def opening(url):
        entered.set()
        assert release.wait(2)
        return fake_transport(bodies)(url)

    thread = owner.start("base", lambda control: downloads.download_directory(
        tmp_path, "model", "owner/model", pin, control, transport=opening),
        lambda *result: results.append(result))
    try:
        assert entered.wait(WAIT)
        assert owner.close(timeout=0.01) is False
        assert owner.closed
        assert not (tmp_path / "model").exists()
    finally:
        release.set()
        thread.join(1)
    assert not thread.is_alive()
    assert results == [(False, "cancelled")]
    assert not list(tmp_path.glob(".partial-*"))
    assert not (tmp_path / "model").exists()


def test_failed_publish_rolls_back_without_deleting_existing_files(tmp_path, bundle, monkeypatch):
    bodies, pin = bundle
    original = write_bundle(tmp_path / "model", {"model.bin": b"user file"})
    rename = Path.rename

    def fail_publish(path, target):
        if path.name.startswith(".partial-"):
            raise OSError("fake rename failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(OSError, match="fake rename failure"):
        downloads.download_directory(tmp_path, "model", "owner/model", pin,
                                     transport=fake_transport(bodies))
    assert (original / "model.bin").read_bytes() == b"user file"
    assert not list(tmp_path.glob(".partial-*"))
    assert not list(tmp_path.glob(".preserved-*"))


def test_recovery_only_removes_owned_partial_bundle_under_lease(tmp_path, bundle):
    from types import SimpleNamespace
    from uuid import uuid4
    bodies, pin = bundle
    partial = tmp_path / (".partial-" + uuid4().hex)
    partial.mkdir()
    entry = SimpleNamespace(id="model", revision=downloads.manifest_identity("owner/model", pin),
                            artifacts=downloads._artifacts(pin))
    downloads.mark_owned(partial, entry)
    (partial / downloads.MARKER).write_text("{}")
    (partial / "model.bin").write_bytes(b"interrupted")
    unknown = tmp_path / (".partial-" + uuid4().hex)
    unknown.mkdir()
    (unknown / "user.txt").write_text("keep")
    assert downloads.download_directory(tmp_path, "model", "owner/model", pin, transport=fake_transport(bodies))
    assert not partial.exists()
    assert (unknown / "user.txt").read_text() == "keep"


def test_first_admission_hashes_once_under_concurrent_checks(tmp_path, bundle, monkeypatch):
    bodies, pin = bundle
    path = write_bundle(tmp_path / "model", bodies)
    entered, release, results, calls = Event(), Event(), [], []
    verify = downloads.verify_file

    def paused(*args):
        calls.append(args[0].name)
        entered.set()
        assert release.wait(2)
        return verify(*args)

    monkeypatch.setattr(downloads, "verify_file", paused)
    threads = [Thread(target=lambda: results.append(downloads.verified_directory(path, "owner/model", pin)))
               for _ in range(2)]
    threads[0].start()
    try:
        assert entered.wait(WAIT)
        threads[1].start()
    finally:
        release.set()
        for thread in threads:
            thread.join(1)
    assert results == [True, True]
    assert calls == list(bodies)


@pytest.mark.parametrize("held_lock", ["owner", "control"])
def test_close_signals_before_bounded_lock_wait(held_lock):
    owner = downloads.LegacyDownloads()
    entered, release, results = Event(), Event(), []

    def operation(control):
        lock = owner.lock if held_lock == "owner" else control.lock
        with lock:
            entered.set()
            assert release.wait(2)
            control.checkpoint()

    thread = owner.start("weight", operation, lambda *result: results.append(result))
    try:
        assert entered.wait(WAIT)
        assert not owner.close(timeout=0)
        control = owner.jobs["weight"][0]
        assert control.event.is_set() and owner.closing.is_set()
    finally:
        release.set()
        thread.join(2)
        assert owner.close(timeout=WAIT)
    assert not thread.is_alive()
    assert results == [(False, "cancelled")]


def test_close_during_registration_cancels_before_operation(monkeypatch):
    owner = downloads.LegacyDownloads()
    entered, release, results, errors = Event(), Event(), [], []
    control_class = downloads.DownloadControl

    class RegisteringControl(control_class):
        def __init__(self, closing=None):
            super().__init__(closing)
            entered.set()
            assert release.wait(2)

    monkeypatch.setattr(downloads, "DownloadControl", RegisteringControl)

    def start():
        try:
            owner.start("weight", lambda _: pytest.fail("operation started after close"),
                        lambda *result: results.append(result))
        except Exception as error:
            errors.append(error)

    starter = Thread(target=start)
    starter.start()
    try:
        assert entered.wait(WAIT)
        assert not owner.close(timeout=0)
    finally:
        release.set()
        starter.join(2)
        assert owner.close(timeout=WAIT)
    assert not starter.is_alive() and not errors
    assert results == [(False, "cancelled")]
    with pytest.raises(ValueError, match="downloads_closed"):
        owner.start("other", lambda _: True, lambda *_: None)
