"""Panel press cancellation with fake poses, controller states and native input."""
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import numpy as np
import openvr
import pytest

from models.overlay import overlay as module


@pytest.fixture
def panel(monkeypatch):
    overlay = module.Overlay({module.PANEL: {
        "tracker": module.PLAYSPACE, "opacity": 1.0, "ui_scaling": 1.0,
        "fadeout_duration": 0,
        **dict.fromkeys(("x_pos", "y_pos", "z_pos", "x_rotation", "y_rotation", "z_rotation"), 0.0),
    }})
    overlay.panel_hwnd = 123
    overlay.panel_image_size = overlay.layout["atlas"]
    overlay.layout_applied = overlay.layout
    overlay.handle = {module.PANEL: 10}
    poses = {0, 1, 2}
    states = {hand: SimpleNamespace(ulButtonPressed=0, rAxis=[SimpleNamespace(x=0.0, y=0.0)])
              for hand in (1, 2)}
    available = {1, 2}
    hits = {2}
    corners = {}
    system = MagicMock()
    system.getTrackedDeviceIndexForControllerRole.side_effect = (
        lambda role: 1 if role == openvr.TrackedControllerRole_LeftHand else 2
    )

    def fill_poses(origin, seconds, output):
        for index in poses:
            output[index].bPoseIsValid = True
            for row in range(3):
                output[index].mDeviceToAbsoluteTracking[row][row] = 1.0
            output[index].mDeviceToAbsoluteTracking[0][3] = index

    system.getDeviceToAbsoluteTrackingPose.side_effect = fill_poses
    system.getControllerState.side_effect = lambda hand: (hand in available, states.get(hand))
    overlay.overlay_system = system
    capture = MagicMock()
    monkeypatch.setattr(module, "window_capture", capture)
    monkeypatch.setattr(overlay, "tipOffset", lambda hand, now: np.eye(4))
    hit = SimpleNamespace(fDistance=0.5)
    monkeypatch.setattr(overlay, "intersect", lambda pose, size: hit)
    monkeypatch.setattr(overlay, "pointingOverlay", lambda pose, poseOf:
                        (module.PANEL, hit) if int(pose[0, 3]) in hits else (None, None))
    monkeypatch.setattr(overlay, "intersectToolbar", lambda pose: None)
    monkeypatch.setattr(overlay, "panelCornerAt", lambda hand, pose, poseOf: corners.get(hand))
    monkeypatch.setattr(overlay, "regionWorldPose", lambda size, poseOf: np.eye(4))
    monkeypatch.setattr(overlay, "overlayWorldPose", lambda size, poseOf: np.eye(4))
    monkeypatch.setattr(overlay, "regionPixel", lambda *args: (450, 260))
    monkeypatch.setattr(overlay, "isVisible", lambda size: True)
    for name in ("applyVrWindows", "updateLauncherVisibility", "updateLauncherIntroFlight",
                 "updateLauncherReturn", "updateToolbarFade", "updateToolbarVisibility",
                 "setToolbarVisible", "showPointer", "setHighlight", "wakeOverlay",
                 "setTransform", "commitPosition", "updateResize", "updateGrabScale"):
        monkeypatch.setattr(overlay, name, MagicMock())
    return SimpleNamespace(overlay=overlay, states=states, available=available, poses=poses,
                           hits=hits, corners=corners, capture=capture, hit=hit)


def press(panel, hand=2):
    panel.hits.add(hand)
    panel.states[hand].ulButtonPressed = module._TRIGGER_MASK
    panel.overlay.updateGrab()
    panel.capture.mouseDown.assert_called_once_with(123, 450, 260)
    assert panel.overlay.panel_input[hand] == (True, (450, 260))


def assert_cancelled(panel, hand=2):
    panel.capture.mouseUp.assert_called_once_with(123, -1, -1)
    assert call(123, -1, -1, pressed=True) in panel.capture.mouseMove.call_args_list
    assert hand not in panel.overlay.panel_input
    assert hand in panel.overlay.trigger_blocked


def assert_requires_release(panel, hand=2):
    panel.overlay.updateGrab()
    panel.overlay.updateGrab()
    assert panel.capture.mouseDown.call_count == 1
    assert hand in panel.overlay.trigger_blocked
    panel.states[hand].ulButtonPressed = 0
    panel.overlay.updateGrab()
    assert hand not in panel.overlay.trigger_blocked
    assert panel.capture.mouseUp.call_count == 1
    panel.states[hand].ulButtonPressed = module._TRIGGER_MASK
    panel.overlay.updateGrab()
    assert panel.capture.mouseDown.call_count == 2


@pytest.mark.parametrize("hand", [1, 2])
@pytest.mark.parametrize("loss", ["poses", "available"])
def test_tracking_or_state_loss_cancels_once_and_requires_release(panel, hand, loss):
    press(panel, hand)
    getattr(panel, loss).remove(hand)
    panel.overlay.updateGrab()
    panel.overlay.updateGrab()
    assert_cancelled(panel, hand)
    # An unknown state, even containing zero button bits, is not a release.
    panel.states[hand].ulButtonPressed = 0
    panel.overlay.updateGrab()
    assert hand in panel.overlay.trigger_blocked
    panel.states[hand].ulButtonPressed = module._TRIGGER_MASK
    getattr(panel, loss).add(hand)
    assert_requires_release(panel, hand)


@pytest.mark.parametrize("mode,owner", [("grip", 2), ("grab", 1), ("grab", 2), ("resize", 1), ("resize", 2)])
def test_grip_or_manipulation_cancels_before_early_return(panel, mode, owner):
    press(panel)
    panel.states[owner].ulButtonPressed |= module._GRIP_MASK
    if mode == "grip":
        panel.hits.clear()
    else:
        panel.hits.add(owner)
    if mode == "resize":
        panel.corners[owner] = (-1, 1, panel.hit)
    panel.overlay.updateGrab()
    assert_cancelled(panel)
    assert (panel.overlay.grabbing is not None) == (mode == "grab")
    assert (panel.overlay.resizing is not None) == (mode == "resize")
    panel.overlay.updateGrab()
    assert panel.capture.mouseUp.call_count == 1
    panel.overlay.grabbing = panel.overlay.resizing = None
    panel.corners.clear()
    panel.hits.clear()
    panel.hits.add(2)
    panel.states[owner].ulButtonPressed &= ~module._GRIP_MASK
    assert_requires_release(panel)


@pytest.mark.parametrize("mode", ["grab", "resize"])
def test_second_hand_takeover_cancels_a_press_from_the_same_frame(panel, mode):
    panel.hits.update((1, 2))
    panel.states[1].ulButtonPressed = module._TRIGGER_MASK
    panel.states[2].ulButtonPressed = module._GRIP_MASK
    if mode == "resize":
        panel.corners[2] = (-1, 1, panel.hit)
    panel.overlay.updateGrab()
    panel.capture.mouseDown.assert_called_once_with(123, 450, 260)
    assert_cancelled(panel, 1)


def test_grab_scaling_cancels_any_outstanding_press(panel):
    press(panel)
    panel.states[1].ulButtonPressed = module._GRIP_MASK | module._TRIGGER_MASK
    panel.overlay.grabbing = (module.PANEL, 1, np.eye(4))
    panel.overlay.updateGrab()
    assert_cancelled(panel)
    panel.overlay.updateGrabScale.assert_called_once()


def test_normal_release_stays_at_the_button_and_does_not_block(panel):
    press(panel)
    panel.states[2].ulButtonPressed = 0
    panel.overlay.updateGrab()
    panel.capture.mouseUp.assert_called_once_with(123, 450, 260)
    assert panel.overlay.panel_input[2] == (False, (450, 260))
    assert not panel.overlay.trigger_blocked


def test_pointer_exit_keeps_outside_release_and_reentry_guard(panel):
    press(panel)
    panel.hits.clear()
    panel.overlay.updateGrab()
    panel.overlay.updateGrab()
    assert_cancelled(panel)
    panel.hits.add(2)
    assert_requires_release(panel)


def test_missing_state_in_direct_input_path_cancels_once(panel):
    press(panel)
    panel.overlay.handlePanelInput(2, (450, 260), None)
    panel.overlay.handlePanelInput(2, (450, 260), None)
    assert_cancelled(panel)
    assert_requires_release(panel)


def test_tracking_loss_without_a_press_only_clears_hover(panel):
    panel.overlay.updateGrab()
    panel.poses.remove(2)
    panel.overlay.updateGrab()
    panel.capture.mouseUp.assert_not_called()
    assert 2 not in panel.overlay.panel_input
    assert not panel.overlay.trigger_blocked
