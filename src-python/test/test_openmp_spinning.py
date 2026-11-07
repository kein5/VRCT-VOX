"""CTranslate2 must not spin on a busy PC, and the setting must stay in this process."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

import runtime_paths


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("KMP_BLOCKTIME", raising=False)
    monkeypatch.setattr(runtime_paths, "_backend_only_env", set())


def test_threads_sleep_at_once(clean_env):
    runtime_paths.limit_openmp_spinning()
    assert os.environ["KMP_BLOCKTIME"] == "0"


def test_a_value_the_user_set_is_kept_and_reaches_child_processes(clean_env, monkeypatch):
    monkeypatch.setenv("KMP_BLOCKTIME", "50")
    runtime_paths.limit_openmp_spinning()
    assert os.environ["KMP_BLOCKTIME"] == "50"
    assert runtime_paths.external_process_env()["KMP_BLOCKTIME"] == "50"


def test_child_processes_do_not_inherit_our_setting(clean_env):
    runtime_paths.limit_openmp_spinning()
    assert "KMP_BLOCKTIME" not in runtime_paths.external_process_env()


def test_it_applies_before_ctranslate2_loads():
    code = ("import sys, runtime_paths; calls = []; original = runtime_paths.limit_openmp_spinning\n"
            "runtime_paths.limit_openmp_spinning = lambda: calls.append('ctranslate2' in sys.modules) or original()\n"
            "import utils; print(calls)")
    env = {k: v for k, v in os.environ.items() if k != "KMP_BLOCKTIME"}
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "[False]"
