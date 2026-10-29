"""Actual Type2 runtime -> AppRun -> Tauri -> frozen sidecar acceptance."""
import os
from pathlib import Path
import shutil
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != 'linux' or not os.environ.get('VRCT_TEST_APPIMAGE')
    or os.environ.get('VRCT_TEST_NATIVE_GUI') != '1',
    reason='opt-in built AppImage and GUI driver/display',
)


@pytest.fixture(params=[
    pytest.param('fuse', marks=pytest.mark.skipif(os.environ.get('VRCT_TEST_APPIMAGE_FUSE') != '1',
                                                reason='opt-in host FUSE mount')),
    'extract',
])
def appimage(request, tmp_path, monkeypatch):
    root = tmp_path / 'AppImage with spaces'
    root.mkdir()
    image = root / 'VRCT-TTS.AppImage'
    shutil.copyfile(Path(os.environ['VRCT_TEST_APPIMAGE']), image)
    image.chmod(0o755)
    monkeypatch.setenv('VRCT_TEST_APP', str(image))
    if request.param == 'extract':
        monkeypatch.setenv('APPIMAGE_EXTRACT_AND_RUN', '1')
    else:
        monkeypatch.delenv('APPIMAGE_EXTRACT_AND_RUN', raising=False)
    return image


def test_appimage_gui_renders_and_exits(appimage, tmp_path):
    from test_native_ui import test_model_free_native_app_renders_text_input_without_fatal_warning
    test_model_free_native_app_renders_text_input_without_fatal_warning(tmp_path)


@pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_ROUTE') != '1', reason='private WirePlumber0.5 graph')
def test_appimage_settings_restart_muted(appimage, tmp_path):
    from test_native_ui import test_native_voice_settings_survive_restart_with_managed_route_muted
    test_native_voice_settings_survive_restart_with_managed_route_muted(tmp_path)
