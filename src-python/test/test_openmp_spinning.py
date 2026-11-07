"""CTranslate2 must not spin or yield on a busy PC, and the settings must stay in this process."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

import runtime_paths

NAMES = ("KMP_BLOCKTIME", "KMP_USE_YIELD")


@pytest.fixture
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runtime_paths, "_backend_only_env", set())


def test_threads_sleep_at_once_and_never_yield(clean_env):
    runtime_paths.limit_openmp_spinning()
    assert [os.environ[name] for name in NAMES] == ["0", "0"]


@pytest.mark.parametrize("name", NAMES)
def test_a_value_the_user_set_is_kept_and_reaches_child_processes(clean_env, monkeypatch, name):
    monkeypatch.setenv(name, "50")
    runtime_paths.limit_openmp_spinning()
    assert os.environ[name] == "50"
    assert runtime_paths.external_process_env()[name] == "50"


def test_child_processes_do_not_inherit_our_settings(clean_env):
    runtime_paths.limit_openmp_spinning()
    child = runtime_paths.external_process_env()
    assert not set(NAMES) & set(child)


def test_it_applies_before_ctranslate2_loads():
    code = ("import sys, runtime_paths; calls = []; original = runtime_paths.limit_openmp_spinning\n"
            "runtime_paths.limit_openmp_spinning = lambda: calls.append('ctranslate2' in sys.modules) or original()\n"
            "import utils; print(calls)")
    env = {k: v for k, v in os.environ.items() if k not in NAMES}
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "[False]"
