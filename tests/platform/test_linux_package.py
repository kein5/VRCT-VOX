"""Opt-in real relocated/read-only Linux package acceptance, no model download."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.linux_package import check_tree, inspect_tar, inventory  # noqa: E402

pytestmark = pytest.mark.skipif(
    sys.platform != 'linux' or not os.environ.get('VRCT_TEST_LINUX_ARCHIVE'),
    reason='requires built Linux candidate archive',
)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    archive = Path(os.environ['VRCT_TEST_LINUX_ARCHIVE']).resolve()
    inspect_tar(archive)
    location = tmp_path / 'relocated install with spaces'
    location.mkdir()
    with tarfile.open(archive) as src:
        src.extractall(location, filter='data')
    roots = list(location.iterdir())
    assert len(roots) == 1
    root = roots[0]
    check_tree(root, require_runtime=True)
    from tools.speechcpp_bundle import verify_bundle
    verify_bundle(root / '_internal/build/speechcpp')
    paths = [root, *root.rglob('*')]
    for path in paths:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)
    assert not os.access(root, os.W_OK), 'run package acceptance as an unprivileged user'
    before = inventory(root)
    monkeypatch.setenv('VRCT_TEST_SIDECAR', str(root / 'vrct-tts-sidecar'))
    monkeypatch.setenv('VRCT_TEST_APP', str(root / 'vrct-tts'))
    try:
        yield root
        assert inventory(root) == before, 'installation mutated during acceptance'
    finally:
        for path in paths:
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)


def test_relocated_sidecar_settings_restart(installation, tmp_path):
    from test_native_backend import test_real_startup_settings_and_restart_without_models
    test_real_startup_settings_and_restart_without_models(tmp_path)
    assert (tmp_path / 'native-state/data/vrct-tts').is_dir()


def test_frozen_router_and_bundled_engine_entrypoints(installation, tmp_path):
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / 'config'),
               XDG_DATA_HOME=str(tmp_path / 'data'), XDG_CACHE_HOME=str(tmp_path / 'cache'))
    # Invalid control must fail closed, without a missing-module traceback.
    result = subprocess.run([str(installation / 'vrct-tts-sidecar'), '--voice-router-worker'],
                            input=b'', capture_output=True, timeout=10, env=env, cwd=tmp_path)
    assert result.returncode == 1
    assert b'Traceback' not in result.stderr
    result = subprocess.run([str(installation / '_internal/build/speechcpp/speech'), '--help'],
                            capture_output=True, timeout=10, cwd=tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_GUI') != '1', reason='requires WebKit driver/display')
def test_relocated_native_gui(installation, tmp_path):
    from test_native_ui import test_model_free_native_app_renders_text_input_without_fatal_warning
    test_model_free_native_app_renders_text_input_without_fatal_warning(tmp_path)


@pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_GUI') != '1', reason='requires WebKit driver/display')
@pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_ROUTE') != '1', reason='opt-in private PipeWire/WirePlumber 0.5 graph')
def test_relocated_managed_route_restart_muted(installation, tmp_path):
    from test_native_ui import test_native_voice_settings_survive_restart_with_managed_route_muted
    test_native_voice_settings_survive_restart_with_managed_route_muted(tmp_path)
