"""CI dependency isolation and failure gates; no download or audio device."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tools import voice_acceptance

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/ci/setup_pipewire.sh"


@pytest.fixture
def policy_prefix(tmp_path, monkeypatch):
    binary = tmp_path / "isolated/bin/wireplumber"
    binary.parent.mkdir(parents=True)
    binary.touch()
    binary.chmod(0o755)
    config = tmp_path / "isolated/share/wireplumber"
    (config / "scripts/lib").mkdir(parents=True)
    (config / "wireplumber.conf").touch()
    monkeypatch.setattr(shutil, "which", lambda name: str(binary))
    return binary.parent.parent


def add_modules(prefix, layout):
    directory = prefix / layout / "wireplumber-0.5"
    directory.mkdir(parents=True)
    (directory / "libwireplumber-module-lua-scripting.so").touch()
    return directory


@pytest.mark.parametrize("layout", ["lib", "lib/x86_64-linux-gnu", "lib/aarch64-linux-gnu"])
def test_policy_paths_follow_selected_daemon_prefix(policy_prefix, monkeypatch, layout):
    module = add_modules(policy_prefix, layout)
    for variable in ("WIREPLUMBER_CONFIG_DIR", "WIREPLUMBER_DATA_DIR", "WIREPLUMBER_MODULE_DIR"):
        monkeypatch.setenv(variable, "/unrelated/host")
    binary, environment = voice_acceptance.policy_installation()
    assert binary == str(policy_prefix / "bin/wireplumber")
    assert environment == {
        "WIREPLUMBER_CONFIG_DIR": str(policy_prefix / "share/wireplumber"),
        "WIREPLUMBER_DATA_DIR": str(policy_prefix / "share/wireplumber"),
        "WIREPLUMBER_MODULE_DIR": str(module),
    }


@pytest.mark.parametrize("missing, error", [
    ("share/wireplumber/wireplumber.conf", "missing_wireplumber_policy_config"),
    ("share/wireplumber/scripts", "missing_wireplumber_policy_data"),
    ("lib/wireplumber-0.5", "missing_wireplumber_policy_modules"),
    ("lib/wireplumber-0.5/libwireplumber-module-lua-scripting.so", "missing_wireplumber_policy_modules"),
])
def test_missing_policy_paths_fail_before_start_without_host_fallback(policy_prefix, monkeypatch, missing, error):
    add_modules(policy_prefix, "lib")
    path = policy_prefix / missing
    shutil.rmtree(path) if path.is_dir() else path.unlink()
    monkeypatch.setattr(voice_acceptance.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("must reject missing policy paths before spawning"))
    if not sys.platform.startswith("linux"):
        with pytest.raises(RuntimeError, match=error):
            voice_acceptance.policy_installation()
    else:
        with pytest.raises(RuntimeError, match=error):
            with voice_acceptance.private_graph():
                pytest.fail("missing installation must not be accepted")


def test_multiple_module_directories_are_rejected(policy_prefix):
    add_modules(policy_prefix, "lib")
    add_modules(policy_prefix, "lib/x86_64-linux-gnu")
    with pytest.raises(RuntimeError, match="ambiguous_wireplumber_policy_modules"):
        voice_acceptance.policy_installation()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux installation symlinks")
@pytest.mark.parametrize("path, error", [
    ("share/wireplumber", "missing_wireplumber_policy_config"),
    ("share/wireplumber/scripts", "missing_wireplumber_policy_data"),
    ("lib/wireplumber-0.5", "missing_wireplumber_policy_modules"),
])
def test_policy_directory_symlink_cannot_escape_prefix(policy_prefix, tmp_path, path, error):
    add_modules(policy_prefix, "lib")
    original = policy_prefix / path
    outside = tmp_path / "host"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match=error):
        voice_acceptance.policy_installation()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux installation symlinks")
def test_daemon_symlink_uses_real_installation(policy_prefix, tmp_path, monkeypatch):
    module = add_modules(policy_prefix, "lib")
    alias = tmp_path / "wireplumber"
    alias.symlink_to(policy_prefix / "bin/wireplumber")
    monkeypatch.setattr(shutil, "which", lambda name: str(alias))
    binary, environment = voice_acceptance.policy_installation()
    assert binary == str(policy_prefix / "bin/wireplumber")
    assert environment["WIREPLUMBER_MODULE_DIR"] == str(module)


@pytest.mark.skipif(sys.platform != "linux", reason="CI shell setup is Linux-only")
def test_ci_setup_preserves_existing_directory(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep"
    sentinel.write_text("user file")
    result = subprocess.run(["bash", str(SCRIPT), str(destination)], capture_output=True, timeout=5)
    assert result.returncode == 2
    assert sentinel.read_text() == "user file"
    assert list(destination.iterdir()) == [sentinel]


@pytest.mark.skipif(sys.platform != "linux", reason="CI shell setup is Linux-only")
def test_bad_archive_hash_stops_before_extract_or_build(tmp_path):
    commands = tmp_path / "commands"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text('#!/bin/bash\nwhile (( $# )); do\n'
                    'if [[ "$1" == "--output" ]]; then printf corrupt > "$2"; exit 0; fi\n'
                    'shift\ndone\nexit 1\n')
    curl.chmod(0o755)
    destination = tmp_path / "isolated"
    result = subprocess.run(["bash", str(SCRIPT), str(destination)],
                            env=dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"]),
                            capture_output=True, timeout=5)
    assert result.returncode != 0
    assert (destination / "source.tar.gz").read_bytes() == b"corrupt"
    assert not (destination / "source").exists()
    assert not (destination / "prefix").exists()
