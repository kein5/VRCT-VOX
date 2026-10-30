"""Read-only model hardware inspection; all subprocesses are owned fakes."""

import json
import sys
import time

import pytest


def devices():
    return {
        "devices": [
            {
                "name": "CPU",
                "description": "host CPU",
                "kind": "cpu",
                "memory_total": 0,
                "memory_free": 0,
            },
            {
                "name": "Vulkan0",
                "description": "test GPU",
                "kind": "gpu",
                "memory_total": 8 * 1024**3,
                "memory_free": 3 * 1024**3,
            },
        ]
    }


def test_device_memory_preserves_zero_and_missing_without_summing_gpus():
    from models.model_downloads.hardware import parse_devices

    data = devices()
    data["devices"][1]["memory_free"] = 0
    data["devices"].append(
        {
            "name": "Vulkan1",
            "description": "shared",
            "kind": "igpu",
            "memory_total": None,
        }
    )
    rows = parse_devices(data)
    assert rows[1]["memory_free"] == 0
    assert rows[2]["memory_total"] is None and rows[2]["memory_free"] is None
    assert [r["name"] for r in rows] == ["CPU", "Vulkan0", "Vulkan1"]


@pytest.mark.parametrize(
    "change",
    [
        {"memory_free": -1},
        {"memory_free": True},
        {"memory_free": 9 * 1024**3},
        {"memory_total": "8 GB"},
        {"name": "bad\nname"},
        {"kind": "mystery"},
    ],
)
def test_bad_device_values_do_not_create_optimistic_capacity(change):
    from models.model_downloads.hardware import parse_devices

    data = devices()
    data["devices"][1].update(change)
    with pytest.raises(ValueError):
        parse_devices(data)


def test_duplicate_device_names_are_rejected():
    from models.model_downloads.hardware import parse_devices

    data = devices()
    data["devices"].append(data["devices"][1])
    with pytest.raises(ValueError):
        parse_devices(data)


def wait_done(probe):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        state = probe.state()
        if state["phase"] != "probing":
            return state
        time.sleep(0.005)
    raise AssertionError(probe.state())


def executable(tmp_path, body, monkeypatch):
    from models.model_downloads import hardware

    path = tmp_path / "speech-fake"
    path.write_text(body, encoding="utf-8")
    popen = hardware.subprocess.Popen

    def launch(command, **kwargs):
        assert command == [str(path), "devices", "--json"]
        # Keep a real child/pipe, without relying on POSIX shebang execution.
        return popen([sys.executable, str(path), *command[1:]], **kwargs)

    monkeypatch.setattr(hardware.subprocess, "Popen", launch)
    return path


def test_refresh_is_async_fixed_command_and_never_loads_model(tmp_path, monkeypatch):
    from models.model_downloads.hardware import HardwareProbe

    path = executable(
        tmp_path,
        'import sys,os,json,time\nassert sys.argv[1:]==["devices","--json"]\nassert os.environ["SPEECH_NO_UPDATE_CHECK"]=="1"\ntime.sleep(.1)\nprint('
        + repr(json.dumps(devices()))
        + ")\n",
        monkeypatch,
    )
    calls = []
    probe = HardwareProbe(binary=lambda: (calls.append(1) or path))
    try:
        assert probe.state()["phase"] == "unknown" and not calls
        start = time.monotonic()
        probe.refresh()
        assert time.monotonic() - start < 0.1
        probe.refresh()  # concurrent requests do not launch duplicate probes
        state = wait_done(probe)
        assert (
            state["phase"] == "ready"
            and state["devices"][1]["memory_free"] == 3 * 1024**3
        )
        assert len(calls) == 1 and state["measured_at_ms"] > 0
    finally:
        assert probe.close()


@pytest.mark.parametrize(
    "body,error",
    [
        ("import time;time.sleep(30)", "hardware_timeout"),
        ('print("not json")', "hardware_invalid"),
        ("import sys;sys.exit(1)", "hardware_failed"),
    ],
)
def test_bad_or_stalled_probe_is_not_cpu_only_or_ready(tmp_path, monkeypatch, body, error):
    from models.model_downloads.hardware import HardwareProbe

    path = executable(tmp_path, body, monkeypatch)
    # Only the stalled-child case measures the deadline. Invalid output/exit
    # cases allow interpreter startup on Windows before asserting their error.
    probe = HardwareProbe(binary=lambda: path, timeout=0.1 if error == "hardware_timeout" else 1)
    try:
        probe.refresh()
        state = wait_done(probe)
        assert (
            state["phase"] == "failed"
            and state["error_code"] == error
            and state["devices"] == []
        )
    finally:
        assert probe.close()


def test_close_reaps_only_owned_probe_and_cannot_restart(tmp_path, monkeypatch):
    from models.model_downloads.hardware import HardwareProbe

    path = executable(tmp_path, "import time;time.sleep(30)", monkeypatch)
    probe = HardwareProbe(binary=lambda: path)
    probe.refresh()
    end = time.monotonic() + 2
    while probe.child is None and time.monotonic() < end:
        time.sleep(0.005)
    child = probe.child
    assert child is not None
    assert probe.close() and child.poll() is not None
    assert probe.state()["phase"] == "closed"
    with pytest.raises(ValueError):
        probe.refresh()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows terminate bypasses Python SIGTERM handlers")
def test_shutdown_escalates_if_owned_probe_ignores_termination(tmp_path, monkeypatch):
    from models.model_downloads.hardware import HardwareProbe

    ready = tmp_path / "ready"
    path = executable(
        tmp_path,
        "import signal,time\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nPath("
        + repr(str(ready))
        + ').write_text("ready")\ntime.sleep(30)',
        monkeypatch,
    )
    probe = HardwareProbe(binary=lambda: path, timeout=3)
    try:
        probe.refresh()
        end = time.monotonic() + 2
        while not ready.exists() and time.monotonic() < end:
            time.sleep(0.005)
        assert ready.exists()
        child = probe.child
        assert probe.close(timeout=0.5)
        assert child.poll() is not None
    finally:
        probe.close(timeout=4)
