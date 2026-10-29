"""Exercise the real Rust launcher with a small Python stdin/stdout program.

The program replaces only the app workload, not process spawning, termination,
argument forwarding or environment selection. No GUI or model is required.
"""
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux process contract")


@pytest.fixture(scope="module")
def compiled_launcher(tmp_path_factory):
    if shutil.which("rustc") is None:
        pytest.skip("rustc required to test the real dev sidecar")
    binary = tmp_path_factory.mktemp("sidecar-build") / "launcher"
    subprocess.run(["rustc", "--edition=2021", str(ROOT / "utils/dev_sidecar/src/main.rs"),
                    "-o", str(binary)], check=True, capture_output=True, text=True, timeout=60)
    return binary


@pytest.fixture
def project(tmp_path, compiled_launcher):
    root = tmp_path / "project with spaces"
    script = root / "src-python/mainloop.py"
    script.parent.mkdir(parents=True)
    script.write_text('''import json, os, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"message": request["message"], "argv": sys.argv[1:],
                  "cwd": os.getcwd(), "pid": os.getpid(),
                  "unbuffered": os.environ.get("PYTHONUNBUFFERED")}, ensure_ascii=False), flush=True)
if request.get("wait"):
    sys.stdin.read()
raise SystemExit(request.get("exit", 0))
''', encoding="utf-8")
    # The wrapper must find the project when Tauri copies it under target/debug.
    binary = root / "src-tauri/target/debug/vrct-tts-sidecar"
    binary.parent.mkdir(parents=True)
    shutil.copy2(compiled_launcher, binary)
    return root, binary


def install_python(root, venv):
    python = root / venv / "bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)


def launch_env(venv=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("VRCT_DEV_VENV", None)
    if venv is not None:
        env["VRCT_DEV_VENV"] = venv
    return env


@pytest.mark.parametrize("venv", [None, ".venv", ".venv_cuda", ".venv_linux"])
def test_linux_interpreter_preserves_protocol_arguments_and_exit(project, venv):
    root, binary = project
    install_python(root, venv or ".venv")
    result = subprocess.run([str(binary), "日本語", "argument with spaces"], cwd=root.parent,
                            env=launch_env(venv), input='{"message":"こんにちは", "exit":23}\n',
                            capture_output=True, text=True, encoding="utf-8", timeout=5)
    assert result.returncode == 23, result.stderr
    response = json.loads(result.stdout)
    assert response["message"] == "こんにちは"
    assert response["argv"] == ["日本語", "argument with spaces"]
    assert response["cwd"] == str(root / "src-python")
    assert response["unbuffered"] == "1"


def test_terminating_wrapper_terminates_python_without_orphan(project):
    root, binary = project
    install_python(root, ".venv")
    with subprocess.Popen([str(binary)], env=launch_env(), stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8") as process:
        try:
            process.stdin.write('{"message":"待機", "wait":true}\n')
            process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=5), "sidecar failed to respond"
            line = process.stdout.readline()
            assert line, process.stderr.read()
            child_pid = json.loads(line)["pid"]
            # A spawn-and-wait wrapper would leave this PID running after kill.
            assert child_pid == process.pid
            process.terminate()
            process.wait(timeout=3)
            assert not Path(f"/proc/{child_pid}").exists()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)


@pytest.mark.parametrize("venv", ["../outside", "/tmp/untrusted", "", ".venv;false"])
def test_invalid_environment_never_starts_python(project, venv):
    root, binary = project
    install_python(root, ".venv")
    result = subprocess.run([str(binary)], env=launch_env(venv), capture_output=True,
                            text=True, timeout=3)
    assert result.returncode == 127
    assert "VRCT_DEV_VENV" in result.stderr
    assert result.stdout == ""


def test_missing_interpreter_does_not_fall_back_to_system_python(project):
    root, binary = project
    result = subprocess.run([str(binary)], env=launch_env(), capture_output=True,
                            text=True, timeout=3)
    assert result.returncode == 127
    assert str(root / ".venv/bin/python") in result.stderr
    assert result.stdout == ""


def test_invalid_interpreter_reports_exec_failure(project):
    root, binary = project
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("not an executable")
    result = subprocess.run([str(binary)], env=launch_env(), capture_output=True,
                            text=True, timeout=3)
    assert result.returncode == 127
    assert "failed to launch" in result.stderr
    assert result.stdout == ""
