import asyncio
import importlib
import json
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]


def test_fork_identity_and_sidecar_contract():
    conf = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert conf["productName"] == "VRCT-VOX"
    assert conf["mainBinaryName"] == "vrct-vox"
    # Branding changes must not orphan existing Tauri data or OS integration.
    assert conf["identifier"] == "io.github.kein5.vrct-tts"
    assert conf["bundle"]["publisher"] == "kein5"
    assert "m's software" in conf["bundle"]["copyright"]
    assert conf["app"]["windows"][0]["title"] == "VRCT-VOX"
    assert conf["bundle"]["externalBin"] == ["bin/vrct-vox-sidecar"]
    assert 'Command.sidecar("bin/vrct-vox-sidecar")' in (ROOT / "src-ui/views/app/_app_controllers/StartPythonController.jsx").read_text(encoding="utf-8")


def test_build_metadata_and_launchers_agree_on_renamed_binaries():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    cargo = tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads((ROOT / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
    assert package["name"] == lock["name"] == lock["packages"][""]["name"] == cargo["package"]["name"] == "vrct-vox"
    assert any(p["name"] == "vrct-vox" and p["version"] == cargo["package"]["version"] for p in cargo_lock["package"])
    desktop = (ROOT / "packaging/appimage/vrct-vox.desktop").read_text(encoding="utf-8")
    assert "Name=VRCT-VOX\n" in desktop and "Exec=vrct-vox\n" in desktop
    assert "usr/lib/vrct-vox/vrct-vox-sidecar" in (ROOT / "packaging/appimage/sidecar").read_text(encoding="utf-8")
    for spec in ("backend.spec", "backend_cuda.spec", "backend_linux.spec"):
        assert "name='vrct-vox-sidecar" in (ROOT / "spec" / spec).read_text(encoding="utf-8")


def test_windows_rename_preserves_install_location_and_retires_legacy_binary_only_after_unpack():
    script = (ROOT / "src-tauri/nsis/template.nsi").read_text(encoding="utf-8")
    assert '!define INSTALLREGNAME "VRCT-TTS"' in script
    assert 'Uninstall\\${INSTALLREGNAME}"' in script
    assert 'Software\\${MANUFACTURER}\\${INSTALLREGNAME}"' in script
    assert 'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"' in script
    install = script[script.index("\nSection Install\n"):script.index("SectionEnd", script.index("\nSection Install\n"))]
    for name in ("vrct-tts.exe", "vrct-tts-sidecar.exe"):
        assert install.index(f'!insertmacro RequireLegacyProcessClosed "$INSTDIR" "{name}"') < install.index("install_ready:")
        assert install.index(f'Delete "$INSTDIR\\{name}"') > install.index("install_ready:")
    assert 'Delete "$INSTDIR\\config.json"' not in install
    reinstall = script[script.index("Function PageLeaveReinstall"):script.index("FunctionEnd", script.index("Function PageLeaveReinstall"))]
    for name in ("vrct-tts.exe", "vrct-tts-sidecar.exe"):
        assert reinstall.index('ReadRegStr $4 SHCTX') < reinstall.index(f'!insertmacro RequireLegacyProcessClosed "$4" "{name}"') < reinstall.index("ExecWait '$R1 /P")


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


def test_download_sources_belong_to_fork():
    from config import config
    assert "/repos/kein5/VRCT-VOX/releases" in config.GITHUB_URL
    assert "/repos/kein5/VRCT-VOX/releases" in config.GITHUB_RELEASES_LIST_URL
    assert config.setupDownloadUrl("3.6.0", tag="v3.6.0") == "https://github.com/kein5/VRCT-VOX/releases/download/v3.6.0/VRCT-VOX_setup.exe"
    script = (ROOT / "src-tauri/nsis/template.nsi").read_text(encoding="utf-8")
    assert "ms-software/VRCT" not in script
    assert "https://github.com/kein5/VRCT-VOX/releases/download/" in script


def test_release_workflow_cannot_publish_or_inject_upstream_keys():
    import yaml
    workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    text = json.dumps(workflow)
    for forbidden in ("HF_TOKEN", "TELEMETRY_KEY", "hf upload", "create-release", "upload-release-asset", "ms-software/VRCT"):
        assert forbidden not in text
    assert "--nsis" in text
    assert "VRCT-VOX.zip" in text and "VRCT-VOX_cuda.zip" in text
