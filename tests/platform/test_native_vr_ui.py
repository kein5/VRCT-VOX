"""Opt-in: the VR UI of the built Linux app, seen and operated through a fake SteamVR.

Needs a graphical session and a build with the embedded UI (VRCT_TEST_APP). No headset: what the
headset would show is read from the overlays the app hands to tools/fake_vr_site.
"""
import os
import sys
import time

import pytest

from native_fake_vr import LAUNCHER, LOG, POPUP, TOOLBAR, FakeVrApp

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE_GUI") != "1",
    reason="requires built native Tauri and a graphical session",
)

# Button centres in page pixels, inside their region.
TRANSLATION, LOG_WINDOW, LANGUAGES = (67, 60), (567, 60), (687, 60)
FONT_LARGER = (580, 45)


def shown(app, target):
    row = app.overlay(target[0])
    return bool(row and row["visible"] and row["texture"])


def ready(app):
    app.wait(lambda: shown(app, LAUNCHER), 90, "the launcher on an overlay")
    # The launcher takes input once its intro has played.
    app.wait(lambda: app.log_lines("launcher intro playing"), 30, "the launcher's intro")
    time.sleep(4)


def test_the_launcher_is_drawn_and_a_trigger_pull_reaches_its_button(tmp_path):
    with FakeVrApp(tmp_path) as app:
        ready(app)
        assert app.state()["misuse"] == []
        idle = app.image(LAUNCHER)
        app.aim(LAUNCHER, TRANSLATION)
        app.wait(lambda: app.overlay("VRCT_pointer_dot")["visible"], 10, "the laser's dot on the launcher")
        app.wait(lambda: app.image(LAUNCHER) != idle, 10, "the hover highlight")
        app.wait(lambda: shown(app, ("VRCT_tooltip", None)), 10, "the button's tooltip")
        app.click()
        # No translation model here: the request arriving is what shows the click got through.
        app.wait(lambda: app.log_lines("'endpoint': '/set/enable/translation'"), 10, "the translation switch")
        assert not app.log_lines("OVERLAY_RUNTIME_FAILED")


def test_windows_open_and_the_stick_scrolls_them(tmp_path):
    with FakeVrApp(tmp_path) as app:
        ready(app)
        assert not shown(app, LOG)
        app.aim(LAUNCHER, LOG_WINDOW)
        app.click()
        app.wait(lambda: shown(app, LOG), 10, "the log window")
        app.aim(LOG, (450, 350))
        app.wait(lambda: shown(app, TOOLBAR), 10, "the toolbar under the log")
        app.aim(TOOLBAR, FONT_LARGER)
        app.click()
        app.wait(lambda: app.log_lines("'endpoint': '/set/data/overlay_vr_panel_font_size', 'result': 18"), 10, "a larger log font")
        app.aim(LAUNCHER, LANGUAGES)
        app.click()
        app.wait(lambda: shown(app, POPUP), 10, "the language window")
        app.aim(POPUP, (360, 400))
        before = app.image(POPUP)
        app.stick(0, -1)
        app.stick(0, 0)
        app.wait(lambda: app.image(POPUP) != before, 10, "the list to scroll")
        assert not app.log_lines("OVERLAY_RUNTIME_FAILED")
