"""Native setter counts and invalidation without an OpenVR runtime."""
from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import openvr
import pytest
from PIL import Image

from models.overlay import overlay as module
from models.overlay.overlay import LAUNCHER, PANEL, TOOLBAR, Overlay, mat34Id, pointerHit


SETTERS = (
    "setOverlayAlpha", "showOverlay", "hideOverlay", "setOverlayWidthInMeters",
    "setOverlayTextureBounds", "setOverlayTransformAbsolute",
    "setOverlayTransformTrackedDeviceRelative",
)


class CountingOverlay(openvr.IVROverlay):
    def __init__(self):
        # Deliberately do not call IVROverlay.__init__ (it loads the native interface).
        self.calls = []
        self.handles = {}
        self.fail = None
        self.fail_always = None

    def createOverlay(self, key, name):
        return self.handles.setdefault(key, len(self.handles) + 1)

    def count(self, method, handle=None):
        return sum(name == method and (handle is None or args[0] == handle) for name, args in self.calls)

    def counts(self):
        return Counter(name for name, _ in self.calls if name in SETTERS)


def counted(method):
    def call(self, *args):
        self.calls.append((method, args))
        if self.fail == method or self.fail_always == method:
            self.fail = None
            raise openvr.error_code.OverlayError_RequestFailed(23)
    return call


for _method in (*SETTERS, "setOverlayColor", "setOverlayRaw", "setOverlayTexture", "setOverlaySortOrder", "destroyOverlay"):
    setattr(CountingOverlay, _method, counted(_method))


def settings():
    return dict(tracker="Playspace", ui_scaling=0.952, opacity=0.8,
                x_pos=0, y_pos=0, z_pos=0, x_rotation=0, y_rotation=0, z_rotation=0,
                display_duration=5, fadeout_duration=0)


def ready_tooltip(overlay, region=LAUNCHER):
    overlay.tooltip_state = dict(epoch=overlay.tooltip_epoch, revision=1, visible=True,
                                 region=region, button=[10, 20, 64, 64], size=[360, 60],
                                 arrow_x=42, mode="focus")
    overlay.tooltip_ready = True


def overlay_fixture(overlay_class=Overlay):
    overlay = overlay_class({LAUNCHER: settings()})
    overlay.overlay = CountingOverlay()
    overlay.overlay_system = MagicMock()
    overlay.initialized = True
    overlay.handle = {LAUNCHER: 1}
    overlay.tooltip_handle = 90
    overlay.pointer_handles = dict(dot=91, plus=92, minus=93)
    overlay.gl = dict(size=overlay.layout["atlas"], texture=10, vr_texture=SimpleNamespace(handle=10))
    overlay.panel_image_size = overlay.layout["atlas"]
    overlay.layout_applied = overlay.layout
    overlay.launcher_interactive = True
    ready_tooltip(overlay)
    return overlay


def idle_frame(overlay):
    overlay.update(LAUNCHER)
    overlay.showPointer(None, (1, 1, 1))
    overlay.updateTooltip()


def test_idle_minute_only_submits_initial_values():
    overlay = overlay_fixture()
    for _ in range(16 * 60):
        idle_frame(overlay)
    assert overlay.overlay.counts() == Counter(setOverlayAlpha=1, hideOverlay=3,
                                               setOverlayTransformAbsolute=1,
                                               setOverlayWidthInMeters=1,
                                               setOverlayTextureBounds=1, showOverlay=1)
    first_minute = overlay.overlay.counts()
    for _ in range(16 * 60):
        idle_frame(overlay)
    assert overlay.overlay.counts() == first_minute


def test_caption_fade_submits_each_step_then_stops_and_wakes():
    overlay = overlay_fixture()
    overlay.settings[LAUNCHER].update(display_duration=1, fadeout_duration=1)
    overlay.lastUpdate[LAUNCHER] = 0
    overlay.updateOpacity(0.8, LAUNCHER)
    for now in (1.25, 1.5, 1.75, 2, 3, 4, 5):
        with patch.object(module.time, "monotonic", return_value=now):
            overlay.update(LAUNCHER)
    alphas = [args[1] for method, args in overlay.overlay.calls if method == "setOverlayAlpha"]
    assert alphas == pytest.approx([0.8, 0.6, 0.4, 0.2, 0])
    overlay.wakeOverlay(LAUNCHER)
    overlay.updateOpacity(0.8, LAUNCHER)
    assert overlay.overlay.count("setOverlayAlpha") == 6
    overlay.fadeRatio[LAUNCHER] = 0
    overlay.updateOpacity(0.8, LAUNCHER, with_fade=True)
    assert overlay.overlay.calls[-1][1][1] == 0.8  # Fresh age overrides the expired cached ratio.


def test_launcher_fade_and_motion_preserve_every_changing_frame():
    overlay = overlay_fixture()
    for frame in range(61):
        overlay.launcher_alpha = frame / 60
        overlay.update(LAUNCHER)
        pose = np.eye(4)[:3, :]
        pose[0, 3] = frame * 0.000001
        overlay.setTransform(LAUNCHER, module._PLAYSPACE_INDEX, pose)
    for _ in range(60):
        overlay.update(LAUNCHER)
        overlay.setTransform(LAUNCHER, module._PLAYSPACE_INDEX, pose)
    assert overlay.overlay.count("setOverlayAlpha") == 61
    assert overlay.overlay.count("setOverlayTransformAbsolute") == 61


@pytest.mark.parametrize("setting", ["opacity", "size", "position", "controller"])
def test_settings_invalidate_tooltip_and_resubmit(setting):
    overlay = overlay_fixture()
    idle_frame(overlay)
    if setting == "opacity":
        overlay.updateOpacity(0.5, LAUNCHER)
    elif setting == "size":
        overlay.updateUiScaling(0.5, LAUNCHER)
    else:
        overlay.overlay_system.getTrackedDeviceIndexForControllerRole.return_value = 7
        overlay.updatePosition(0.1 if setting == "position" else 0, 0, 0, 0, 0, 0,
                               "RightHand" if setting == "controller" else "Playspace", LAUNCHER)
    overlay.updateTooltip()
    assert overlay.overlay.count("showOverlay", 90) == 2
    assert overlay.overlay.count("setOverlayWidthInMeters", 90) == 2
    counts = overlay.overlay.counts()
    overlay.updateTooltip()
    assert overlay.overlay.counts() == counts


def test_relative_device_and_transform_mode_share_one_cache_entry():
    overlay = overlay_fixture()
    overlay.settings[LAUNCHER]["tracker"] = "LeftHand"
    for index in (2, 2, 5, 5):
        overlay.overlay_system.getTrackedDeviceIndexForControllerRole.return_value = index
        overlay.updateTooltip()
    assert overlay.overlay.count("setOverlayTransformTrackedDeviceRelative", 90) == 2
    assert overlay.overlay.count("showOverlay", 90) == 2
    overlay.settings[LAUNCHER]["tracker"] = "Playspace"
    overlay.updateTooltip()
    overlay.settings[LAUNCHER]["tracker"] = "LeftHand"
    overlay.updateTooltip()
    assert overlay.overlay.count("setOverlayTransformTrackedDeviceRelative", 90) == 3
    assert overlay.overlay.count("setOverlayTransformAbsolute", 90) == 1
    assert overlay.overlay.count("showOverlay", 90) == 4


def test_panel_anchor_moves_toolbar_and_tooltip():
    overlay = overlay_fixture()
    overlay.settings[PANEL] = settings()
    overlay.handle[PANEL] = 2
    overlay.toolbar_handle = 80
    overlay.toolbar_visible = True
    overlay.setTransform(PANEL, module._PLAYSPACE_INDEX, np.eye(4)[:3, :])
    ready_tooltip(overlay, TOOLBAR)
    overlay.updateTooltip()
    overlay.setAnchor(lambda index: np.eye(4), "HMD")
    overlay.updateTooltip()
    for handle in (2, 80, 90):
        assert overlay.overlay.count("setOverlayTransformAbsolute", handle) == 1
        assert overlay.overlay.count("setOverlayTransformTrackedDeviceRelative", handle) == 1


@pytest.mark.parametrize("change", ["layout", "capture_size", "texture_size"])
def test_layout_and_texture_sizes_resubmit_unchanged_tooltip_properties(change):
    overlay = overlay_fixture()
    overlay.updateTooltip()
    if change == "layout":
        overlay.setPanelSize(1000, 700)
        overlay.applyLayout()
        ready_tooltip(overlay)
    elif change == "capture_size":
        overlay.panel_image_size = tuple(value * 2 for value in overlay.panel_image_size)
        overlay.applyLayout()
    else:
        overlay.newPanelTexture(MagicMock(), tuple(value * 2 for value in overlay.gl["size"]))
    overlay.updateTooltip()
    assert overlay.overlay.count("setOverlayTransformAbsolute", 90) == 2
    assert overlay.overlay.count("setOverlayWidthInMeters", 90) == 2
    assert overlay.overlay.count("setOverlayTextureBounds", 90) == 2
    assert overlay.overlay.count("showOverlay", 90) == 2


def test_caption_image_size_invalidates_but_identical_size_does_not():
    overlay = overlay_fixture()
    overlay.images[LAUNCHER] = Image.new("RGBA", (1, 1))
    overlay.update(LAUNCHER)
    overlay.updateImage(Image.new("RGBA", (1, 1)), LAUNCHER)
    assert overlay.overlay.count("setOverlayAlpha", 1) == 1
    overlay.updateImage(Image.new("RGBA", (2, 2)), LAUNCHER)
    assert overlay.overlay.count("setOverlayAlpha", 1) == 2


def test_reused_handle_and_destruction_forget_every_property():
    overlay = overlay_fixture()
    api = overlay.overlay
    api.handles["tooltip"] = 90
    overlay.updateTooltip()
    overlay.tooltip_handle = overlay.createOverlay("tooltip", "tooltip")
    overlay.updateTooltip()
    for method in ("setOverlayTransformAbsolute", "setOverlayWidthInMeters", "setOverlayTextureBounds", "showOverlay"):
        assert api.count(method, 90) == 2
    overlay.destroyOverlays()
    assert not overlay.overlay_state
    assert api.count("destroyOverlay", 90) == 1
    overlay.overlay = api
    overlay.tooltip_handle = 90
    ready_tooltip(overlay)
    overlay.updateTooltip()
    assert api.count("showOverlay", 90) == 3


@pytest.mark.parametrize("method", SETTERS)
def test_failed_setter_invalidates_the_handle_even_for_previous_value(method):
    overlay = overlay_fixture()
    api = overlay.overlay
    matrix = mat34Id(np.eye(4)[:3, :])
    bounds = openvr.VRTextureBounds_t(0, 0, 1, 1)
    args = {
        "setOverlayAlpha": (0.5,), "showOverlay": (), "hideOverlay": (),
        "setOverlayWidthInMeters": (0.4,), "setOverlayTextureBounds": (bounds,),
        "setOverlayTransformAbsolute": (openvr.TrackingUniverseStanding, matrix),
        "setOverlayTransformTrackedDeviceRelative": (2, matrix),
    }[method]
    overlay.submitOverlay("setOverlayAlpha", 90, 0.8)
    api.fail = method
    with pytest.raises(openvr.error_code.OpenVRError):
        overlay.submitOverlay(method, 90, *args)
    overlay.submitOverlay(method, 90, *args)
    overlay.submitOverlay(method, 90, *args)
    assert api.count(method, 90) == (3 if method == "setOverlayAlpha" else 2)
    if method != "setOverlayAlpha":
        overlay.submitOverlay("setOverlayAlpha", 90, 0.8)
        assert api.count("setOverlayAlpha", 90) == 2


@pytest.mark.parametrize("method", ["setOverlayTransformAbsolute", "setOverlayWidthInMeters", "setOverlayTextureBounds", "showOverlay"])
def test_persistent_tooltip_failure_logs_once_until_a_new_request(method):
    overlay = overlay_fixture()
    overlay.overlay.fail_always = method
    with patch.object(module, "errorLogging") as errors:
        for _ in range(100):
            overlay.safeUpdateTooltip()
    errors.assert_called_once()  # The original path logs once and drops the request.
    assert overlay.tooltip_state is None
    assert not overlay.tooltip_ready
    assert 90 not in overlay.overlay_state
    assert overlay.overlay.count(method, 90) == 1
    overlay.overlay.fail_always = None
    ready_tooltip(overlay)  # A later request has arrived and its capture is ready.
    overlay.safeUpdateTooltip()
    assert overlay.tooltip_shown
    assert overlay.overlay.count(method, 90) == 2
    counts = overlay.overlay.counts()
    overlay.safeUpdateTooltip()
    assert overlay.overlay.counts() == counts


def test_failed_tooltip_hide_waits_for_the_next_visibility_transition():
    overlay = overlay_fixture()
    overlay.updateTooltip()
    overlay.overlay.fail_always = "hideOverlay"
    with patch.object(module, "errorLogging") as errors:
        for _ in range(100):
            overlay.hideTooltip()
            overlay.safeUpdateTooltip()
    errors.assert_called_once()
    assert not overlay.tooltip_shown
    assert 90 not in overlay.overlay_state
    assert overlay.overlay.count("hideOverlay", 90) == 1
    overlay.overlay.fail_always = None
    ready_tooltip(overlay)
    overlay.updateTooltip()
    overlay.hideTooltip()
    assert overlay.overlay.count("hideOverlay", 90) == 2


def test_hidden_pointers_show_again_and_share_visibility_state():
    overlay = overlay_fixture()
    hit = pointerHit(np.array([0, 0, 1]), np.array([0, 0, 1]), 1)
    for _ in range(100):
        overlay.showPointer(None, (1, 1, 1))
    assert overlay.overlay.count("hideOverlay") == 3
    for _ in range(100):
        overlay.showPointer(hit, (1, 1, 1))
    assert overlay.overlay.count("showOverlay", 91) == 1
    assert overlay.overlay.count("setOverlayTransformAbsolute", 91) == 1
    overlay.showPointer(None, (1, 1, 1))
    overlay.showPointer(hit, (1, 1, 1))
    overlay.showPointer(hit, (1, 1, 1), kind="plus")
    assert overlay.overlay.count("showOverlay", 91) == 2
    assert overlay.overlay.count("hideOverlay", 91) == 3
    assert overlay.overlay.count("showOverlay", 92) == 1


def test_mutable_matrices_and_bounds_are_snapshotted():
    overlay = overlay_fixture()
    matrix = mat34Id(np.eye(4)[:3, :])
    bounds = openvr.VRTextureBounds_t(0, 0, 1, 1)
    for value in (0.0, 0.25, 0.25, 0.5):
        matrix.m[0][3] = value
        bounds.uMin = value
        overlay.submitOverlay("setOverlayTransformAbsolute", 1, 1, matrix)
        overlay.submitOverlay("setOverlayTextureBounds", 1, bounds)
    assert overlay.overlay.count("setOverlayTransformAbsolute") == 3
    assert overlay.overlay.count("setOverlayTextureBounds") == 3


def toolbar_fixture():
    overlay = overlay_fixture()
    overlay.settings[PANEL] = settings()
    overlay.handle[PANEL] = 2
    overlay.toolbar_handle = 80
    return overlay


@pytest.mark.parametrize("method", ["setOverlayAlpha", "hideOverlay"])
def test_toolbar_fade_failure_at_target_waits_for_a_new_fade(method):
    overlay = toolbar_fixture()
    overlay.toolbar_alpha = 1
    overlay.toolbar_faded_at = 0
    overlay.overlay.fail_always = method
    with pytest.raises(openvr.error_code.OpenVRError):
        overlay.updateToolbarFade(1)
    assert 80 not in overlay.overlay_state
    counts = overlay.overlay.counts()
    for now in range(2, 102):
        overlay.updateToolbarFade(now)
    assert overlay.overlay.counts() == counts
    assert overlay.overlay.count(method, 80) == 1
    overlay.overlay.fail_always = None
    overlay.setToolbarVisible(True)
    overlay.updateToolbarFade(102)
    overlay.setToolbarVisible(False)
    overlay.updateToolbarFade(103)
    assert overlay.overlay.count(method, 80) > 1


def test_failed_toolbar_show_does_not_repeat_tracker_or_pose_work():
    overlay = toolbar_fixture()
    overlay.settings[PANEL]["tracker"] = "LeftHand"
    overlay.overlay_system.getTrackedDeviceIndexForControllerRole.return_value = 2
    overlay.overlay.fail_always = "showOverlay"
    with patch.object(overlay, "panelRelative", wraps=overlay.panelRelative) as relative:
        with pytest.raises(openvr.error_code.OpenVRError):
            overlay.setToolbarVisible(True)
        assert 80 not in overlay.overlay_state
        counts = overlay.overlay.counts()
        tracker_calls = overlay.overlay_system.getTrackedDeviceIndexForControllerRole.call_count
        for frame in range(100):
            overlay.updateToolbarVisibility(100 + frame, pointing_log=True)
        assert overlay.overlay.counts() == counts
        assert overlay.overlay_system.getTrackedDeviceIndexForControllerRole.call_count == tracker_calls
        relative.assert_called_once()
    overlay.overlay.fail_always = None
    overlay.setToolbarVisible(False)
    overlay.setToolbarVisible(True)
    assert overlay.overlay.count("showOverlay", 80) == 2


def test_failed_immediate_toolbar_hide_does_not_repeat_at_zero_alpha():
    overlay = toolbar_fixture()
    overlay.toolbar_alpha = 1
    overlay.toolbar_visible = True
    overlay.overlay.fail_always = "hideOverlay"
    with pytest.raises(openvr.error_code.OpenVRError):
        overlay.hideToolbarNow()
    assert overlay.toolbar_alpha == 0
    assert 80 not in overlay.overlay_state
    for _ in range(100):
        overlay.hideToolbarNow()
    assert overlay.overlay.count("hideOverlay", 80) == 1
    overlay.overlay.fail_always = None
    overlay.setToolbarVisible(True)
    overlay.updateToolbarFade(1)
    overlay.updateToolbarFade(2)
    overlay.hideToolbarNow()
    assert overlay.overlay.count("hideOverlay", 80) == 2


def test_failed_connected_position_waits_for_an_explicit_update():
    overlay = overlay_fixture()
    overlay.overlay.fail_always = "setOverlayTransformAbsolute"
    with pytest.raises(openvr.error_code.OpenVRError):
        overlay.updatePosition(0.1, 0, 0, 0, 0, 0, "Playspace", LAUNCHER)
    assert LAUNCHER not in overlay.position_pending
    assert 1 not in overlay.overlay_state
    for _ in range(100):
        overlay.retryPendingPositions()
    assert overlay.overlay.count("setOverlayTransformAbsolute", 1) == 1
    overlay.overlay.fail_always = None
    overlay.updatePosition(0.1, 0, 0, 0, 0, 0, "Playspace", LAUNCHER)
    assert overlay.overlay.count("setOverlayTransformAbsolute", 1) == 2


@pytest.mark.parametrize("visible", [True, False])
def test_failed_window_visibility_waits_for_a_new_transition(visible):
    overlay = overlay_fixture()
    overlay.vr_panel_enabled = visible
    if visible:
        overlay.vr_windows_hidden.add(LAUNCHER)
    method = "showOverlay" if visible else "hideOverlay"
    overlay.overlay.fail_always = method
    with pytest.raises(openvr.error_code.OpenVRError):
        overlay.applyVrWindows(lambda index: np.eye(4))
    assert 1 not in overlay.overlay_state
    assert (LAUNCHER not in overlay.vr_windows_hidden) == visible
    for _ in range(100):
        overlay.applyVrWindows(lambda index: np.eye(4))
    assert overlay.overlay.count(method, 1) == 1
    overlay.overlay.fail_always = None
    overlay.vr_panel_enabled = not visible
    overlay.applyVrWindows(lambda index: np.eye(4))
    overlay.vr_panel_enabled = visible
    overlay.applyVrWindows(lambda index: np.eye(4))
    assert overlay.overlay.count(method, 1) == 2


def test_failed_ghost_bounds_wait_for_changed_geometry():
    overlay = overlay_fixture()
    overlay.ghost_handle = 80
    overlay.gl.update(ghost_texture=20, ghost_vr_texture=object())
    overlay.resizing = dict(size=(400, 300), center=(0, 0), pose=np.eye(4), m_per_px=0.001)
    overlay.overlay.fail_always = "setOverlayTextureBounds"
    GL = MagicMock()
    with patch.object(overlay, "prepareGl", return_value=GL):
        with pytest.raises(openvr.error_code.OpenVRError):
            overlay.showResizeGhost(False)
        assert 80 not in overlay.overlay_state
        for _ in range(100):
            overlay.showResizeGhost(False)
        assert overlay.overlay.count("setOverlayTextureBounds", 80) == 1
        GL.glTexSubImage2D.assert_called_once()
        overlay.overlay.fail_always = None
        overlay.resizing["size"] = (404, 300)
        overlay.showResizeGhost(False)
    assert overlay.overlay.count("setOverlayTextureBounds", 80) == 2


def test_quit_mainloop_reconnect_resubmits_with_reused_native_handles():
    overlay = Overlay({LAUNCHER: settings()})
    apis = []

    class FakeOverlay(CountingOverlay):
        def __init__(self):
            super().__init__()
            apis.append(self)

    class FakeSystem(openvr.IVRSystem):
        def __init__(self):
            self.quit = False

        def pollNextEvent(self, event):
            if self.quit:
                event.eventType = openvr.VREvent_Quit
                self.quit = False
                return True
            return False

    system = FakeSystem()
    real_init = overlay.init

    def init():
        real_init()
        overlay.gl = dict(size=overlay.layout["atlas"], glfw=MagicMock(), window=object())
        overlay.layout_applied = overlay.layout
        overlay.panel_image_size = overlay.layout["atlas"]
        overlay.launcher_interactive = True
        ready_tooltip(overlay)

    def grab():
        overlay.applyVrWindows(lambda index: np.eye(4))
        overlay.showPointer(None, (1, 1, 1))
        system.quit = True
        overlay.run_stop.set()  # No real frame wait; next connection gets its own event.
        if len(apis) == 2:
            overlay.loop = False

    with patch.object(module.openvr, "IVROverlay", FakeOverlay), \
            patch.object(module.openvr, "IVRSystem", FakeSystem), \
            patch.object(module.openvr_session, "acquire", return_value=system), \
            patch.object(module.openvr_session, "release"), \
            patch.object(module, "Thread"), patch.object(module, "raiseThreadPriority"), \
            patch.object(module, "printLog"), patch.object(module, "errorLogging") as errors, \
            patch.object(overlay, "initPanelTexture"), patch.object(overlay, "shutdownPanelTexture"), \
            patch.object(overlay, "checkSteamvrRunning", return_value=True), \
            patch.object(overlay, "waitUnlessCancelled", return_value=False), \
            patch.object(overlay, "init", side_effect=init), \
            patch.object(overlay, "updateGrab", side_effect=grab), \
            patch.object(overlay, "updatePanel", side_effect=overlay.updateTooltip), \
            patch.object(module.time, "sleep", side_effect=lambda seconds: setattr(system, "quit", True)):
        overlay.main()
    errors.assert_not_called()
    assert len(apis) == 2
    assert apis[0].handles == apis[1].handles
    assert apis[0].counts() == apis[1].counts()
    for api in apis:
        for method in ("setOverlayAlpha", "showOverlay", "hideOverlay", "setOverlayWidthInMeters",
                       "setOverlayTextureBounds", "setOverlayTransformAbsolute"):
            assert api.count(method) > 0
    assert not overlay.overlay_state


def test_disconnected_controller_resubmits_same_transform_after_recovery():
    overlay = overlay_fixture()
    overlay.overlay_system.getTrackedDeviceIndexForControllerRole.return_value = 2
    overlay.updatePosition(0, 0, 0, 0, 0, 0, "LeftHand", LAUNCHER)
    overlay.overlay_system.isTrackedDeviceConnected.return_value = False
    overlay.updatePosition(0, 0, 0, 0, 0, 0, "LeftHand", LAUNCHER)
    assert LAUNCHER in overlay.position_pending
    overlay.overlay_system.isTrackedDeviceConnected.return_value = True
    overlay.retryPendingPositions()
    assert overlay.overlay.count("setOverlayTransformTrackedDeviceRelative", 1) == 2


def test_failed_tooltip_show_does_not_schedule_a_hide():
    overlay = overlay_fixture()
    overlay.overlay.fail_always = "showOverlay"
    with patch.object(module, "errorLogging") as errors:
        overlay.safeUpdateTooltip()
        assert not overlay.tooltip_shown
        for _ in range(100):
            overlay.hideTooltip()
            overlay.safeUpdateTooltip()
    errors.assert_called_once()
    assert overlay.overlay.count("showOverlay", 90) == 1
    assert overlay.overlay.count("hideOverlay", 90) == 0
