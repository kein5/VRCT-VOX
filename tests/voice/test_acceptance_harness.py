from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from tools import voice_acceptance as acceptance


def test_measurement_requires_live_silence_and_discards_pcm():
    observation = acceptance.PCMObservation()
    observation.feed(b"\x01\x00", 10_000_000)
    assert not observation.quiet(0)
    # A stopped/dead capture cannot qualify as silent just because time passed.
    assert not observation.quiet(200_000_000)
    observation.feed(bytes(960), 200_000_000)
    assert observation.quiet(0)
    assert not observation.quiet(190_000_000)
    snapshot = observation.snapshot()
    assert snapshot["bytes"] == 962
    assert snapshot["first_nonzero_ns"] == snapshot["last_nonzero_ns"] == 10_000_000
    assert not any(isinstance(value, bytes) for value in snapshot.values())
    observation.reset()
    assert observation.snapshot()["first_nonzero_ns"] is None
    assert not observation.quiet(0)


def test_cleanup_escalates_only_owned_process_after_timeout():
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("owned", 1), 0]
    acceptance.stop_process(process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2


def test_partial_failure_still_writes_failure_report_and_cleans_graph(tmp_path, monkeypatch):
    cleaned = []
    @contextmanager
    def graph():
        try:
            raise TimeoutError("private_policy_not_ready")
            yield
        finally:
            cleaned.append(True)
    monkeypatch.setattr(acceptance, "private_graph", graph)
    output = tmp_path / "failed"
    assert acceptance.main(["--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["failure_code"] == "private_policy_not_ready"
    assert not report["vrchat_verified"] and not report["raw_audio_saved"]
    assert cleaned == [True]
    assert (output / "latency.csv").read_text().splitlines() == ["metric,environment,warm,start_ns,end_ns"]


def test_refuses_to_overwrite_previous_evidence(tmp_path):
    with pytest.raises(FileExistsError):
        acceptance.main(["--output", str(tmp_path)])


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_speak_exits_instead_of_waiting_forever(text):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "tools/voice_cli.py", "speak", "--device", "never-open",
                             "--text", text], cwd=root, capture_output=True, text=True, timeout=3)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"error": "invalid_text"}
    assert not result.stderr


@pytest.mark.parametrize("failure_at", ["startup", "policy", "body", "cleanup", None])
def test_private_graph_failure_restores_environment_and_reaps_processes(tmp_path, monkeypatch, failure_at):
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux-only harness")
    prefix = tmp_path / "policy"
    binary = prefix / "bin/wireplumber"
    binary.parent.mkdir(parents=True)
    binary.touch()
    binary.chmod(0o755)
    data = prefix / "share/wireplumber"
    (data / "scripts/lib").mkdir(parents=True)
    (data / "wireplumber.conf").touch()
    module = prefix / "lib/wireplumber-0.5"
    module.mkdir(parents=True)
    (module / "libwireplumber-module-lua-scripting.so").touch()
    shadow = tmp_path / "host-data"
    (shadow / "wireplumber/scripts/lib").mkdir(parents=True)
    (shadow / "wireplumber/scripts/lib/common-utils.lua").write_text("error('host script')")
    monkeypatch.setenv("PIPEWIRE_REMOTE", "existing-desktop")
    monkeypatch.delenv("PIPEWIRE_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(shadow))
    monkeypatch.setenv("XDG_DATA_DIRS", str(shadow))
    monkeypatch.setenv("WIREPLUMBER_DATA_DIR", str(shadow / "wireplumber"))
    monkeypatch.setenv("WIREPLUMBER_MODULE_DIR", str(tmp_path / "host-modules"))
    monkeypatch.delenv("WIREPLUMBER_CONFIG_DIR", raising=False)
    monkeypatch.setattr(acceptance.shutil, "which",
                        lambda name: str(binary) if name == "wireplumber" else "installed")
    before = dict(acceptance.os.environ)
    selected = {"WIREPLUMBER_CONFIG_DIR": str(data), "WIREPLUMBER_DATA_DIR": str(data),
                "WIREPLUMBER_MODULE_DIR": str(module)}
    processes = []
    commands = []

    def assert_policy_paths():
        assert {key: acceptance.os.environ.get(key) for key in selected} == selected

    def terminate():
        assert_policy_paths()
        if failure_at == "cleanup":
            raise OSError("injected_cleanup_failure")

    def popen(command, **kwargs):
        assert_policy_paths()
        commands.append(command)
        if failure_at == "startup":
            raise OSError("injected_startup_failure")
        process = MagicMock(pid=100 + len(processes))
        process.poll.return_value = None
        process.terminate.side_effect = terminate
        processes.append(process)
        return process

    waits = 0

    def wait_for(*args, **kwargs):
        nonlocal waits
        waits += 1
        if failure_at == "policy" and waits == 2:
            raise TimeoutError("injected_policy_failure")

    monkeypatch.setattr(acceptance.subprocess, "Popen", popen)
    monkeypatch.setattr(acceptance, "wait_for", wait_for)

    def run():
        with acceptance.private_graph():
            assert_policy_paths()
            if failure_at == "body":
                raise ValueError("injected_body_failure")

    if failure_at:
        with pytest.raises((OSError, TimeoutError, ValueError), match="injected_"):
            run()
    else:
        run()
    assert dict(acceptance.os.environ) == before
    for process in processes:
        process.terminate.assert_called_once()
    if len(commands) == 2:
        assert commands[1] == [str(binary.resolve()), "--profile", "policy"]
