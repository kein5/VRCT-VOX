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


def test_private_graph_failure_restores_environment_and_reaps_processes(tmp_path, monkeypatch):
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux-only harness")
    monkeypatch.setenv("PIPEWIRE_REMOTE", "existing-desktop")
    monkeypatch.delenv("PIPEWIRE_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(acceptance.shutil, "which", lambda _: "installed")
    process = MagicMock()
    process.poll.return_value = None
    monkeypatch.setattr(acceptance.subprocess, "Popen", lambda *a, **kw: process)
    def timeout(*a, **kw):
        raise TimeoutError("daemon_start_timeout")
    monkeypatch.setattr(acceptance, "wait_for", timeout)
    with pytest.raises(TimeoutError):
        with acceptance.private_graph():
            pass
    assert acceptance.os.environ["PIPEWIRE_REMOTE"] == "existing-desktop"
    assert "PIPEWIRE_RUNTIME_DIR" not in acceptance.os.environ
    process.terminate.assert_called_once()
