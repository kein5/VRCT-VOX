import os
from pathlib import Path
import sys

import pytest


def test_resource_root_relocates_with_frozen_sidecar(monkeypatch, tmp_path):
    import runtime_paths as paths
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "moved/_internal"), raising=False)
    assert paths.resource_root() == tmp_path / "moved/_internal"


def test_source_resource_root_still_points_to_checkout(monkeypatch):
    import runtime_paths as paths
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.resource_root() == Path(__file__).resolve().parents[2]


def test_linux_state_paths_use_xdg_and_ignore_relative_xdg_values(tmp_path):
    import runtime_paths as paths
    home = tmp_path / "home"
    result = paths.linux_directories({"XDG_CONFIG_HOME": "relative", "XDG_DATA_HOME": str(tmp_path / "data"),
                                      "XDG_CACHE_HOME": str(tmp_path / "cache")}, home)
    assert result == {"config": home / ".config/vrct-tts", "data": tmp_path / "data/vrct-tts",
                      "cache": tmp_path / "cache/vrct-tts"}


def test_explicit_state_override_keeps_existing_directory_contract(tmp_path):
    import runtime_paths as paths
    result = paths.linux_directories({"VRCT_CONFIG_DIR": str(tmp_path / "state"),
                                      "VRCT_DATA_DIR": str(tmp_path / "models"),
                                      "VRCT_CACHE_DIR": str(tmp_path / "cache")}, tmp_path / "home")
    assert result == {"config": tmp_path / "state", "data": tmp_path / "models", "cache": tmp_path / "cache"}


@pytest.mark.parametrize("platform,frozen", [("linux", False), ("win32", True)])
def test_bootstrap_leaves_development_and_windows_unchanged(monkeypatch, platform, frozen):
    import runtime_paths as paths
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    before = dict(os.environ), Path.cwd()
    paths.bootstrap_linux_frozen()
    assert (dict(os.environ), Path.cwd()) == before


def test_frozen_bootstrap_creates_only_user_state(monkeypatch, tmp_path):
    import runtime_paths as paths
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for key in ("VRCT_CONFIG_DIR", "VRCT_DATA_DIR", "VRCT_CACHE_DIR", "HF_HOME"):
        monkeypatch.delenv(key, raising=False)
    for key, suffix in [("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")]:
        monkeypatch.setenv(key, str(tmp_path / suffix))
    # Preserve changes made by bootstrap inside this test's monkeypatch scope.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    paths.bootstrap_linux_frozen()
    assert Path.cwd() == tmp_path / "data/vrct-tts"
    assert Path(os.environ["VRCT_CONFIG_DIR"]) == tmp_path / "config/vrct-tts"
    assert Path(os.environ["HF_HOME"]).is_relative_to(tmp_path / "cache/vrct-tts")
    assert (tmp_path / "config/vrct-tts/logs").is_dir()


@pytest.mark.parametrize("original", [None, "/opt/user-libs"])
def test_external_child_does_not_inherit_frozen_library_override(monkeypatch, original):
    import runtime_paths as paths
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/moved/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    if original:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)
    env = paths.external_process_env()
    assert env.get("LD_LIBRARY_PATH") == original
    assert os.environ["LD_LIBRARY_PATH"] == "/moved/_internal"


def test_model_storage_moves_but_prompts_stay_bundled(monkeypatch, tmp_path):
    from config import Config
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "readonly/sidecar"))
    monkeypatch.setenv("VRCT_CONFIG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VRCT_DATA_DIR", str(tmp_path / "data"))
    cfg = object.__new__(Config)
    cfg.init_config()
    assert cfg.PATH_LOCAL == str(tmp_path / "readonly")
    assert cfg.PATH_DATA == str(tmp_path / "data")
    assert cfg.PATH_CONFIG == str(tmp_path / "state/config.json")
