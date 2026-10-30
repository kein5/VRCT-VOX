"""Real controller/IPC routing with only unrelated OS/model services injected."""

import ast
from dataclasses import replace
import io
from pathlib import Path

import pytest

from test_controller_integration import controller_module as controller_module
from test_model_downloads import setup as setup, start as start, finish as finish

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['controller_module', 'setup']


def test_apply_updates_only_stopped_profile_path_and_preserves_options(
    controller_module, setup
):
    c = controller_module.Controller()
    assert hasattr(c, "applyModelDownload"), "model download IPC missing"
    m, entry, _, _ = setup
    c.model_downloads = m
    c._speech_settings["profiles"]["japanese"].update(
        model="/old.gguf", low_latency=True, device="cpu"
    )
    start(m)
    job = finish(m)
    result = c.applyModelDownload(
        {"id": entry.id, "job_id": job["job_id"], "expected": {"model": "/old.gguf"}}
    )
    assert result["status"] == 200
    row = c.getSpeechServerSettings()["result"]["profiles"]["japanese"]
    assert (
        row["model"] == job["paths"]["model"]
        and row["low_latency"]
        and row["device"] == "cpu"
    )
    assert c.speech_servers.state()["japanese"]["state"] == "stopped"
    assert c.voice_events.status()["accepted"] == 0
    assert not c.direct_voice.health()["requested"]


def test_stale_settings_and_running_server_cannot_be_overwritten(
    controller_module, setup, monkeypatch
):
    c = controller_module.Controller()
    assert hasattr(c, "applyModelDownload")
    m, entry, _, _ = setup
    c.model_downloads = m
    start(m)
    job = finish(m)
    req = {"id": entry.id, "job_id": job["job_id"], "expected": {"model": "/old.gguf"}}
    result = c.applyModelDownload(req)
    assert (
        result["status"] == 409 and result["result"]["error_code"] == "settings_changed"
    )
    req["expected"]["model"] = ""
    monkeypatch.setattr(
        c.speech_servers, "state", lambda: {"japanese": {"state": "ready"}}
    )
    assert c.applyModelDownload(req)["result"]["error_code"] == "model_target_busy"
    assert c.getSpeechServerSettings()["result"]["profiles"]["japanese"]["model"] == ""
    assert m.state()["jobs"][entry.id]["phase"] == "ready"


def test_rvc_apply_sets_both_paths_without_loading_or_changing_runtime(
    controller_module, setup
):
    from models.voice_conversion.settings import DirectSettings

    c = controller_module.Controller()
    m, entry, content, _ = setup
    c.model_downloads = m
    pth = replace(entry.artifacts[0], filename="voice.pth")
    index = replace(pth, filename="voice.index", role="index")
    m.entries[entry.id] = replace(entry, target="rvc", artifacts=(pth, index))
    m.transport = lambda _: io.BytesIO(content)
    c._direct_settings = DirectSettings(
        rvc_runtime="/owned/runtime", rvc_pitch=3, rvc_index_rate=0.2
    )
    start(m)
    job = finish(m)
    result = c.applyModelDownload(
        {
            "id": entry.id,
            "job_id": job["job_id"],
            "expected": {"model": "", "index": ""},
        }
    )
    assert result["status"] == 200
    saved = c._direct_settings
    assert (
        saved.rvc_model == job["paths"]["model"]
        and saved.rvc_index == job["paths"]["index"]
    )
    assert (saved.rvc_runtime, saved.rvc_pitch, saved.rvc_index_rate) == (
        "/owned/runtime",
        3,
        0.2,
    )
    assert saved.mode == "passthrough" and saved.engine == "seed-vc"
    assert (
        not c.direct_voice.health()["requested"]
        and c.voice_events.status()["accepted"] == 0
    )


@pytest.mark.parametrize(
    "method,payload",
    [
        ("startModelDownload", {}),
        ("startModelDownload", {"id": []}),
        ("cancelModelDownload", {"id": "x"}),
        ("applyModelDownload", None),
    ],
)
def test_malformed_download_requests_fail_without_side_effects(
    controller_module, method, payload
):
    c = controller_module.Controller()
    assert hasattr(c, method)
    assert getattr(c, method)(payload)["status"] == 400
    assert c.model_downloads.state()["jobs"] == {}


def test_download_routes_are_stdio_only_and_registered():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "src-python/mainloop.py").read_text())
    paths = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    for path in (
        "/get/data/model_download_catalog",
        "/get/data/model_download_state",
        "/run/start_model_download",
        "/run/cancel_model_download",
        "/run/apply_model_download",
        "/get/data/model_download_hardware",
        "/run/refresh_model_download_hardware",
    ):
        assert path in paths


def test_hardware_snapshot_and_refresh_do_not_start_models(
    controller_module, monkeypatch
):
    c = controller_module.Controller()
    assert c.getModelDownloadHardware()["result"]["phase"] == "unknown"
    calls = []
    monkeypatch.setattr(
        c.model_hardware, "refresh", lambda: (calls.append(1) or {"phase": "probing"})
    )
    assert c.refreshModelDownloadHardware({})["result"][
        "phase"
    ] == "probing" and calls == [1]
    assert c.refreshModelDownloadHardware({"binary": "arbitrary"})["status"] == 400
    assert (
        c.voice_events.status()["accepted"] == 0
        and not c.direct_voice.health()["requested"]
    )
    assert c.model_hardware.close()
