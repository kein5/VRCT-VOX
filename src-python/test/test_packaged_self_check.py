"""`vrct-vox-sidecar --self-check`: the check the build runs on the packaged backend itself."""
import io
from pathlib import Path
import subprocess
import sys

import packaged_self_check as subject

ROOT = Path(__file__).resolve().parents[2]


def test_every_check_runs_and_a_failure_is_named_without_its_message():
    out = io.StringIO()

    def broken():
        raise FileNotFoundError(2, "no such file", r"C:\Users\someone\_internal\transformers\models\__init__.pyc")
    failed = subject.run((("works", lambda: None), ("breaks", broken), ("also works", lambda: 1)), out)
    assert failed == ["breaks"]
    assert out.getvalue().splitlines() == ["ok works", "FAILED breaks: FileNotFoundError", "ok also works"]
    # A build log is public: neither the path nor the message is printed.
    assert "someone" not in out.getvalue() and "no such file" not in out.getvalue()


def test_the_checks_cover_what_translation_and_recognition_import_lazily():
    names = [name for name, _ in subject.CHECKS]
    assert any("transformers" in name for name in names)
    assert any("ctranslate2" in name for name in names)
    assert any("faster-whisper" in name for name in names)
    # In a source checkout with the app's dependencies, they all load.
    out = io.StringIO()
    assert subject.run(out=out) == [], out.getvalue()


def test_the_backend_answers_the_flag_and_starts_nothing_else():
    done = subprocess.run([sys.executable, str(ROOT / "src-python/mainloop.py"), "--self-check"],
                          capture_output=True, text=True, timeout=180, cwd=ROOT / "src-python")
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert lines[-1] == "self-check passed" and len([line for line in lines if line.startswith("ok ")]) == len(subject.CHECKS)
    # None of the backend's own start-up output: the flag is handled before anything is built.
    assert "initialization_complete" not in done.stdout


def test_the_packages_are_built_with_transformers_as_source_files():
    # Inside the PYZ archive Transformers cannot list its own folders, and no tokenizer loads.
    for spec in ("backend.spec", "backend_cuda.spec", "backend_linux.spec"):
        text = (ROOT / "spec" / spec).read_text(encoding="utf-8")
        assert "'transformers': 'py'" in text, spec
