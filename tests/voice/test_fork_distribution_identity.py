import asyncio
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]


def test_fork_identity_and_sidecar_contract():
    conf = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text())
    assert conf["productName"] == "VRCT-TTS"
    assert conf["mainBinaryName"] == "vrct-tts"
    assert conf["identifier"] == "io.github.kein5.vrct-tts"
    assert conf["bundle"]["publisher"] == "kein5"
    assert "m's software" in conf["bundle"]["copyright"]
    assert conf["app"]["windows"][0]["title"] == "VRCT-TTS"
    assert conf["bundle"]["externalBin"] == ["bin/vrct-tts-sidecar"]
    assert 'Command.sidecar("bin/vrct-tts-sidecar")' in (ROOT / "src-ui/views/app/_app_controllers/StartPythonController.jsx").read_text()


def test_telemetry_stays_disabled_even_with_stale_upstream_key(monkeypatch):
    # Deliberately simulate an ignored key file left behind by an old build.
    sdk = Mock()
    monkeypatch.setitem(sys.modules, "telemetry_keys", SimpleNamespace(APP_KEYS={"stable": "test", "beta": "test"}))
    monkeypatch.setitem(sys.modules, "aptabase", SimpleNamespace(Aptabase=sdk))
    import models.telemetry.client as client
    importlib.reload(client)
    wrapper = client.AptabaseWrapper()
    async def lifecycle():
        await wrapper.start("test")
        await wrapper.track("test", {})
        await wrapper.stop()
    asyncio.run(lifecycle())
    sdk.assert_not_called()


def test_fork_updater_makes_no_request_and_never_starts_installer(monkeypatch):
    import model
    request, spawn = Mock(), Mock()
    monkeypatch.setattr(model, "requests_get", request)
    monkeypatch.setattr(model, "Popen", spawn)
    assert model.Model.checkSoftwareUpdated()["is_update_available"] is False
    assert model.Model.listAvailableReleases() == []
    assert model.Model.updateSoftware() == model.SETUP_DOWNLOAD_FAILED
    assert model.Model.updateCudaSoftware("3.6.0") == model.SETUP_DOWNLOAD_FAILED
    request.assert_not_called()
    spawn.assert_not_called()


def test_download_sources_belong_to_fork():
    from config import config
    assert "/repos/kein5/VRCT-TTS/releases" in config.GITHUB_URL
    assert "/repos/kein5/VRCT-TTS/releases" in config.GITHUB_RELEASES_LIST_URL
    assert config.setupDownloadUrl("3.6.0", tag="v3.6.0") == "https://github.com/kein5/VRCT-TTS/releases/download/v3.6.0/VRCT-TTS_setup.exe"
    script = (ROOT / "src-tauri/nsis/template.nsi").read_text()
    assert "ms-software/VRCT" not in script
    assert "https://github.com/kein5/VRCT-TTS/releases/download/" in script


def test_release_workflow_cannot_publish_or_inject_upstream_keys():
    import yaml
    workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    text = json.dumps(workflow)
    for forbidden in ("HF_TOKEN", "TELEMETRY_KEY", "hf upload", "create-release", "upload-release-asset", "ms-software/VRCT"):
        assert forbidden not in text
    assert "--nsis" in text
    assert "VRCT-TTS.zip" in text and "VRCT-TTS_cuda.zip" in text
