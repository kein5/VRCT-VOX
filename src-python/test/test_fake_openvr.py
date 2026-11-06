"""偽の OpenVR (fake_openvr.py) が、本物の pyopenvr と同じ形で呼べ、SteamVR と同じように振る舞うか。

偽物が本物とずれると、偽物を使った試験は本物では起きる失敗を見逃す。ここで呼び出しの形と、
製品のコードが呼ぶメソッドがすべて偽物にあることを確かめる。
"""

import ctypes
import inspect
import re
import unittest
from pathlib import Path

import numpy as np
import openvr
import openvr.error_code as error_code

from fake_openvr import (
    HMD,
    RIGHT_HAND,
    FakeOpenVR,
    FakeOpenVRMisuse,
    FakeVRApplications,
    FakeVROverlay,
    FakeVRRenderModels,
    FakeVRSystem,
    matrix34,
    pose_matrix,
)

SRC = Path(__file__).resolve().parents[1]
PAIRS = (
    (FakeVRSystem, openvr.IVRSystem),
    (FakeVROverlay, openvr.IVROverlay),
    (FakeVRRenderModels, openvr.IVRRenderModels),
    (FakeVRApplications, openvr.IVRApplications),
)


def _public_methods(cls):
    return {name: fn for name, fn in vars(cls).items() if not name.startswith("_") and callable(fn)}


class SignatureTest(unittest.TestCase):
    def test_every_fake_method_has_the_real_signature(self):
        for fake, real in PAIRS:
            for name, fn in _public_methods(fake).items():
                with self.subTest(method=f"{real.__name__}.{name}"):
                    self.assertTrue(hasattr(real, name), "the real interface has no such method")
                    self.assertEqual(list(inspect.signature(fn).parameters),
                                     list(inspect.signature(getattr(real, name)).parameters))

    def test_entry_points_have_the_real_signature(self):
        vr = FakeOpenVR()
        self.assertEqual(list(inspect.signature(vr.init).parameters), list(inspect.signature(openvr.init).parameters))
        self.assertEqual(list(inspect.signature(vr.shutdown).parameters), list(inspect.signature(openvr.shutdown).parameters))
        for name in vr.replacements():
            self.assertTrue(hasattr(openvr, name), name)

    def test_every_call_the_product_makes_is_faked(self):
        """製品のコードが IVROverlay・IVRSystem・IVRApplications に対して呼ぶメソッドが、偽物にすべてある。"""
        overlay = (SRC / "models/overlay/overlay.py").read_text(encoding="utf-8")
        clipboard = (SRC / "models/clipboard/clipboard.py").read_text(encoding="utf-8")
        used = {
            FakeVROverlay: set(re.findall(r"self\.overlay\.(\w+)\(", overlay))
            | set(re.findall(r'submitOverlay\(\s*"(\w+)"', overlay)),
            FakeVRSystem: set(re.findall(r"self\.(?:overlay_system|system)\.(\w+)\(", overlay)),
            FakeVRRenderModels: set(re.findall(r"openvr\.VRRenderModels\(\)\.(\w+)\(", overlay)),
            FakeVRApplications: set(re.findall(r"\bapps\.(\w+)\(", clipboard)),
        }
        for fake, methods in used.items():
            self.assertTrue(methods, fake.__name__)  # 探し方が古くなって何も見つけなくなったら気づく
            with self.subTest(fake=fake.__name__):
                self.assertEqual(methods - set(_public_methods(fake)), set())


class RuntimeTest(unittest.TestCase):
    def test_init_fails_like_steamvr_when_it_is_not_running(self):
        with FakeOpenVR(steamvr_running=False) as vr:
            with self.assertRaises(error_code.InitError):
                openvr.init(openvr.VRApplication_Background)
            vr.steamvr_running, vr.hmd_present = True, False
            with self.assertRaises(error_code.InitError_Init_HmdNotFound):
                openvr.init(openvr.VRApplication_Background)
            with self.assertRaises(error_code.InitError_Init_NotInitialized):
                openvr.IVROverlay()

    def test_install_is_undone(self):
        real_init = openvr.init
        with FakeOpenVR():
            self.assertIsNot(openvr.init, real_init)
        self.assertIs(openvr.init, real_init)

    def test_steamvr_process_check_follows_the_fake(self):
        from models.overlay import overlay as overlay_module

        with FakeOpenVR(steamvr_running=False) as vr:
            self.assertFalse(overlay_module.Overlay.checkSteamvrRunning())
            vr.steamvr_running = True
            self.assertTrue(overlay_module.Overlay.checkSteamvrRunning())
        self.assertEqual(overlay_module.isProcessRunning.__module__, "models.process_check")

    def test_tracking_pose_array_is_filled_and_none_returns_none(self):
        with FakeOpenVR() as vr:
            system = openvr.init(openvr.VRApplication_Background)
            self.assertIsNone(system.getDeviceToAbsoluteTrackingPose(openvr.TrackingUniverseStanding, 0, None))
            poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
            system.getDeviceToAbsoluteTrackingPose(openvr.TrackingUniverseStanding, 0, poses)
            self.assertTrue(poses[HMD].bPoseIsValid)
            self.assertAlmostEqual(poses[HMD].mDeviceToAbsoluteTracking[1][3], 1.6)
            self.assertFalse(poses[5].bDeviceIsConnected)
            vr.devices[RIGHT_HAND].press(openvr.k_EButton_Grip)
            ok, state = system.getControllerState(RIGHT_HAND)
            self.assertTrue(ok)
            self.assertTrue(state.ulButtonPressed & (1 << openvr.k_EButton_Grip))
            self.assertFalse(system.getControllerState(HMD)[0])

    def _overlay_in_front(self, vr):
        overlay = openvr.IVROverlay()
        handle = overlay.createOverlay("test", "test")
        raw = bytes(200 * 100 * 4)
        overlay.setOverlayRaw(handle, (ctypes.c_char * len(raw)).from_buffer_copy(raw), 200, 100, 4)
        overlay.setOverlayWidthInMeters(handle, 0.5)
        overlay.setOverlayTransformAbsolute(handle, openvr.TrackingUniverseStanding, matrix34(pose_matrix((0.0, 1.6, -1.0))))
        return overlay, handle

    def _ray(self, overlay, handle, source, target):
        params = openvr.VROverlayIntersectionParams_t()
        params.eOrigin = openvr.TrackingUniverseStanding
        direction = np.subtract(target, source)
        for i in range(3):
            params.vSource.v[i], params.vDirection.v[i] = source[i], direction[i]
        return overlay.computeOverlayIntersection(handle, params)

    def test_intersection_uses_the_size_and_uv_of_the_real_runtime(self):
        with FakeOpenVR() as vr:
            openvr.init(openvr.VRApplication_Background)
            overlay, handle = self._overlay_in_front(vr)
            hit, results = self._ray(overlay, handle, (0.0, 1.6, 0.0), (0.0, 1.6, -1.0))
            self.assertTrue(hit)
            self.assertAlmostEqual(results.fDistance, 1.0)
            self.assertAlmostEqual(results.vUVs.v[0], 0.5)
            self.assertAlmostEqual(results.vUVs.v[1], 0.5)
            hit, results = self._ray(overlay, handle, (0.0, 1.6, 0.0), (0.2, 1.65, -1.0))
            self.assertAlmostEqual(results.vUVs.v[0], 0.9)
            self.assertAlmostEqual(results.vUVs.v[1], 0.6)  # 縦も横幅を 1 とした長さ (uvToPixel)
            # 高さは 0.5 x 100/200 = 0.25m。上端 (0.125m) より上は当たらない
            self.assertFalse(self._ray(overlay, handle, (0.0, 1.6, 0.0), (0.0, 1.74, -1.0))[0])
            self.assertFalse(self._ray(overlay, handle, (0.0, 1.6, 0.0), (0.0, 1.6, 1.0))[0])  # 後ろ向き

    def test_unknown_handles_and_duplicate_keys_fail_like_steamvr(self):
        with FakeOpenVR():
            openvr.init(openvr.VRApplication_Background)
            overlay = openvr.IVROverlay()
            handle = overlay.createOverlay("key", "name")
            with self.assertRaises(error_code.OverlayError_KeyInUse):
                overlay.createOverlay("key", "other")
            overlay.destroyOverlay(handle)
            with self.assertRaises(error_code.OverlayError_UnknownOverlay):
                overlay.showOverlay(handle)

    def test_use_after_shutdown_is_reported(self):
        with FakeOpenVR() as vr:
            openvr.init(openvr.VRApplication_Background)
            overlay = openvr.IVROverlay()
            overlay.createOverlay("left over", "left over")
            openvr.shutdown()
            self.assertEqual([state.key for state in vr.leaked], ["left over"])
            openvr.init(openvr.VRApplication_Background)  # つなぎ直しても、前の接続のインターフェースは使えない
            with self.assertRaises(FakeOpenVRMisuse):
                overlay.createOverlay("again", "again")
            self.assertEqual(len(vr.misuse), 1)

    def test_applications_and_render_models(self):
        with FakeOpenVR(applications=[("system.desktop", "Desktop"), ("steam.app.438100", "VRChat")]):
            openvr.init(openvr.VRApplication_Background)
            apps = openvr.VRApplications()
            keys = [apps.getApplicationKeyByIndex(i) for i in range(apps.getApplicationCount())]
            self.assertEqual(apps.getApplicationPropertyString(keys[1], openvr.VRApplicationProperty_Name_String), "VRChat")
            system = openvr.IVRSystem()
            name = system.getStringTrackedDeviceProperty(RIGHT_HAND, openvr.Prop_RenderModelName_String)
            ok, state = system.getControllerState(RIGHT_HAND)
            found, component = openvr.VRRenderModels().getComponentState(name, "tip", state, openvr.RenderModel_ControllerMode_State_t())
            self.assertTrue(found)
            self.assertEqual(component.mTrackingToComponentLocal[0][0], 1.0)


if __name__ == "__main__":
    unittest.main()
