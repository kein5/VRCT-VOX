"""偽の SteamVR (fake_openvr.py) につないで、オーバーレイのスレッドを本物のまま動かす。

ほかの overlay の試験は1つの関数を MagicMock で切り出して確かめる。ここでは startOverlay から
shutdownOverlay まで、つなぐ・描く・指す・掴む・SteamVR が終わる・つなぎ直すの流れを通し、
最後にオーバーレイと接続が残っていないことを確かめる。VR UI (OpenGL と画面の撮影) は使わない。
"""

import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import openvr
from PIL import Image

from fake_openvr import RIGHT_HAND, FakeOpenVR, pose_matrix
from models import openvr_session
from models.overlay.overlay import Overlay

_TIMEOUT_SEC = 5.0


def _settings() -> dict:
    return {"small": {
        "x_pos": 0.0, "y_pos": 0.0, "z_pos": 0.0,
        "x_rotation": 0.0, "y_rotation": 0.0, "z_rotation": 0.0,
        "display_duration": 5, "fadeout_duration": 2,
        "opacity": 1.0, "ui_scaling": 0.5, "tracker": "HMD",
    }}


class FakeSteamvrTestCase(unittest.TestCase):
    def setUp(self) -> None:
        for name, value in (("_STEAMVR_POLL_SEC", 0.02), ("_START_CANCEL_POLL_SEC", 0.01), ("_LASER_PITCH_UP_DEG", 0.0)):
            patcher = patch(f"models.overlay.overlay.{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("printLog", "errorLogging"):
            patcher = patch(f"models.overlay.overlay.{name}")
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.vr = FakeOpenVR()
        self.vr.install()
        self.addCleanup(self.vr.uninstall)
        self.overlay = Overlay(_settings())
        self.addCleanup(self.overlay.shutdownOverlay)

    def wait(self, condition, message: str) -> None:
        deadline = time.monotonic() + _TIMEOUT_SEC
        while not condition():
            if time.monotonic() > deadline:
                self.fail(f"timed out: {message}")
            time.sleep(0.01)

    def start(self) -> None:
        self.assertTrue(self.overlay.startOverlay())
        self.wait(lambda: self.overlay.initialized, "overlay connected")

    def stop_and_check_clean(self) -> None:
        self.overlay.shutdownOverlay()
        self.assertIsNone(self.overlay.thread_overlay)
        self.assertEqual(self.vr.overlays, {})  # すべて自分で消した
        self.assertEqual(self.vr.leaked, [])
        self.assertFalse(self.vr.connected)
        self.assertFalse(openvr_session.is_active())
        self.assertEqual(self.vr.misuse, [])

    def subtitle(self, color=(255, 0, 0, 255)) -> Image.Image:
        return Image.new("RGBA", (200, 100), color)


class LifecycleTest(FakeSteamvrTestCase):
    def test_subtitle_overlay_is_drawn_in_front_of_the_head_and_removed_on_stop(self):
        self.start()
        small = self.vr.overlay_by_key("VRCT0")
        self.assertTrue(small.visible)
        kind, device, relative = small.transform
        self.assertEqual((kind, device), ("device", openvr.k_unTrackedDeviceIndex_Hmd))
        np.testing.assert_allclose(relative[:3, 3], (0.0, -0.4, -1.0), atol=1e-6)  # 頭の 1m 前、0.4m 下
        self.assertAlmostEqual(small.width_m, 0.5)
        for kind in ("dot", "plus", "minus"):
            pointer = self.vr.overlay_by_key(f"VRCT_pointer_{kind}")
            self.assertFalse(pointer.visible)
            self.assertEqual(pointer.raw[1:3], (64, 64))

        self.assertTrue(self.overlay.updateImage(self.subtitle(), "small"))
        self.assertEqual(small.raw[1:3], (200, 100))
        self.assertEqual(small.image().getpixel((100, 50)), (255, 0, 0, 255))
        self.stop_and_check_clean()
        self.errorLogging.assert_not_called()

    def test_waits_for_steamvr_and_for_the_headset(self):
        self.vr.steamvr_running = False
        self.assertTrue(self.overlay.startOverlay())
        time.sleep(0.1)
        self.assertEqual(self.vr.init_calls, 0)  # SteamVR が動くまではつながない
        self.vr.steamvr_running, self.vr.hmd_present = True, False
        self.wait(lambda: self.overlay.connect_failed, "first connection attempt failed")
        self.vr.hmd_present = True
        self.wait(lambda: self.overlay.initialized, "connected after the headset appeared")
        self.assertEqual(self.errorLogging.call_count, 1)  # つながらない間の記録は最初の1回だけ
        self.stop_and_check_clean()

    def test_steamvr_quit_releases_everything_and_reconnects(self):
        self.start()
        self.vr.quit()
        self.wait(lambda: not self.vr.connected, "disconnected after VREvent_Quit")
        self.assertEqual(self.vr.leaked, [])  # 接続を閉じる前にオーバーレイを消した
        self.assertFalse(self.overlay.initialized)
        self.assertFalse(self.overlay.updateImage(self.subtitle(), "small"))  # つないでいない間は描かない

        self.vr.steamvr_running = True
        self.wait(lambda: self.overlay.initialized, "reconnected")
        self.assertEqual(self.vr.init_calls, 2)
        self.assertTrue(self.vr.overlay_by_key("VRCT0").visible)
        self.assertTrue(self.overlay.updateImage(self.subtitle(), "small"))
        self.stop_and_check_clean()
        self.errorLogging.assert_not_called()

    def test_clipboard_shares_the_session_without_closing_it(self):
        from models.clipboard.clipboard import Clipboard

        self.start()
        clipboard = Clipboard.__new__(Clipboard)  # 監視のスレッドは起こさない
        clipboard.app_name = None
        with patch("models.clipboard.clipboard.printLog"):
            clipboard._setup_vr_app_name()
        self.assertEqual(clipboard.app_name, "VRChat")
        self.assertEqual(self.vr.shutdown_calls, 0)  # オーバーレイが使っている間は閉じない
        self.assertTrue(self.overlay.updateImage(self.subtitle(), "small"))
        self.stop_and_check_clean()
        self.assertEqual(self.vr.shutdown_calls, 1)


class ControllerTest(FakeSteamvrTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.start()
        self.assertTrue(self.overlay.updateImage(self.subtitle(), "small"))
        self.small = self.vr.overlay_by_key("VRCT0")
        self.dot = self.vr.overlay_by_key("VRCT_pointer_dot")

    def test_laser_shows_the_pointer_only_on_the_overlay(self):
        self.vr.aim(RIGHT_HAND, self.small)
        self.wait(lambda: self.dot.visible, "pointer shown on the overlay")
        pointer_at = self.vr.world_pose(self.dot)[:3, 3]
        np.testing.assert_allclose(pointer_at, self.vr.world_pose(self.small)[:3, 3], atol=0.01)

        self.vr.devices[RIGHT_HAND].pose = pose_matrix((0.2, 1.0, -0.2), pitch_deg=80)  # 上を指す
        self.wait(lambda: not self.dot.visible, "pointer hidden off the overlay")
        self.stop_and_check_clean()
        self.errorLogging.assert_not_called()

    def test_aim_allows_for_the_raised_laser(self):
        """アプリはレーザーを本体の前方から上げて出す。aim がその分だけ本体を下げれば、狙った点に当たる。"""
        with patch("models.overlay.overlay._LASER_PITCH_UP_DEG", 12.0):
            self.vr.aim(RIGHT_HAND, self.small, at=(0.1, 0.0), laser_pitch_deg=12.0)
            self.wait(lambda: self.dot.visible, "pointer shown on the overlay")
            target = (self.vr.world_pose(self.small) @ np.array([0.1, 0.0, 0.0, 1.0]))[:3]
            np.testing.assert_allclose(self.vr.world_pose(self.dot)[:3, 3], target, atol=0.01)
        self.stop_and_check_clean()

    def test_grip_moves_the_overlay_and_saves_the_position(self):
        moved = MagicMock()
        self.overlay.position_changed_callback = moved
        before = self.vr.world_pose(self.small)[:3, 3].copy()
        self.vr.aim(RIGHT_HAND, self.small)
        self.wait(lambda: self.dot.visible, "pointing")
        hand = self.vr.devices[RIGHT_HAND]
        hand.press(openvr.k_EButton_Grip)
        self.wait(lambda: self.overlay.grabbing is not None, "grabbed")
        start = hand.pose.copy()
        for step in range(1, 11):  # 0.5秒かけて右へ 20cm 動かす
            hand.pose = start.copy()
            hand.pose[0, 3] += 0.02 * step
            time.sleep(0.05)
        hand.release(openvr.k_EButton_Grip)
        self.wait(lambda: moved.called, "position saved after release")
        size, position = moved.call_args.args
        self.assertEqual(size, "small")
        self.assertEqual(position["tracker"], "HMD")
        after = self.vr.world_pose(self.small)[:3, 3]
        self.assertGreater(after[0] - before[0], 0.1)  # 右へ動いた
        self.stop_and_check_clean()
        self.errorLogging.assert_not_called()


if __name__ == "__main__":
    unittest.main()
