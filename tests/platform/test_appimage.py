"""Actual Type2 runtime -> AppRun -> Tauri -> frozen sidecar acceptance."""
import os
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

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
    image = root / 'VRCT-VOX.AppImage'
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


def test_normal_launch_keeps_window_painted_after_idle_and_hover(appimage, tmp_path):
    """WebDriver screenshots missed ordinary-launch corruption; inspect X11 pixels."""
    import psutil
    from PIL import Image, ImageStat
    from native_webdriver import check_displays_on, matches_launched_app
    from test_native_ui import initial_state

    capture = ([shutil.which('magick'), 'import'] if shutil.which('magick')
               else [shutil.which('import')])
    assert capture[0] and shutil.which('xdotool'), 'install ImageMagick and xdotool for real-window acceptance'
    state = initial_state(tmp_path)
    env = dict(os.environ, VRCT_CONFIG_DIR=str(state), VRCT_DATA_DIR=str(tmp_path/'data'),
               VRCT_CACHE_DIR=str(tmp_path/'cache'), XDG_DATA_HOME=str(tmp_path/'xdg-data'),
               XDG_CACHE_HOME=str(tmp_path/'xdg-cache'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    check_displays_on()
    pointer = dict(re.findall(r'^(X|Y)=(\d+)$', subprocess.check_output(
        ['xdotool', 'getmouselocation', '--shell'], text=True, timeout=3), re.M))
    with (tmp_path/'normal-launch.log').open('w') as log:
        process = subprocess.Popen([appimage], env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 30
            window = None
            while time.monotonic() < deadline:
                assert process.poll() is None, 'AppImage exited before drawing'
                leader = psutil.Process(process.pid)
                for child in [leader, *leader.children(recursive=True)]:
                    try:
                        if not matches_launched_app(child.exe(), child.environ(), appimage, appimage=True):
                            continue
                        found = subprocess.run(['xdotool', 'search', '--all', '--onlyvisible',
                                                '--pid', str(child.pid), '--name', '^VRCT-VOX$'],
                                               capture_output=True, text=True, timeout=3)
                        ids = found.stdout.split()
                        if len(ids) == 1:
                            geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', ids[0]], text=True, timeout=3)
                            values = dict(re.findall(r'^(WIDTH|HEIGHT)=(\d+)$', geometry, re.M))
                            if int(values.get('WIDTH', 0)) >= 500 and int(values.get('HEIGHT', 0)) >= 300:
                                window = ids[0]
                    # A helper running with other credentials (such as WebKit's
                    # bubblewrap sandbox) hides its environment; it is not the app.
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if window:
                    break
                time.sleep(.1)
            assert window, 'main window did not reach its normal geometry'
            # Startup screenshots alone missed this bug. Let the window idle,
            # then move the real pointer without requesting a WebKit screenshot.
            time.sleep(5)
            reports = []
            for index, position in enumerate([None, (100, 15), (90, 150), (350, 200)]):
                if position:
                    subprocess.run(['xdotool', 'mousemove', '--window', window, *map(str, position)],
                                   check=True, timeout=3)
                    time.sleep(.3)
                check_displays_on()
                image_path = tmp_path/f'normal-window-{index}.png'
                subprocess.run([*capture, '-silent', '-window', window, str(image_path)], check=True, timeout=8)
                with Image.open(image_path) as image:
                    rgb = image.convert('RGB')
                    interior = rgb.crop((8, 8, rgb.width-8, rgb.height-8))
                    histogram = interior.convert('L').histogram()
                    painted = sum(histogram[8:]) / sum(histogram)
                    report = {'size': list(rgb.size), 'painted_fraction': painted,
                              'variance': max(ImageStat.Stat(interior).var)}
                reports.append(report)
                (tmp_path/'normal-window-metrics.json').write_text(json.dumps(reports, indent=2))
                # With the deterministic default theme/100% opacity, the entire
                # interior has a nonblack background; the old window was ~0.1%.
                assert painted > .98 and report['variance'] > 10, report
        finally:
            try:
                owned = [psutil.Process(process.pid), *psutil.Process(process.pid).children(recursive=True)]
            except psutil.NoSuchProcess:
                owned = []
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for child in owned:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(owned, timeout=3)
            for child in alive:
                try:
                    if child.status() != psutil.STATUS_ZOMBIE:
                        child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            process.wait(timeout=3)
            _, alive = psutil.wait_procs(alive, timeout=3)
            assert all(p.status() == psutil.STATUS_ZOMBIE for p in alive), 'owned app survived cleanup'
            subprocess.run(['xdotool', 'mousemove', pointer['X'], pointer['Y']], check=True, timeout=3)
