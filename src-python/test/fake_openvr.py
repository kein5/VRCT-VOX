"""SteamVR を使わずに VR の処理を動かすための、偽の OpenVR ランタイム。

pyopenvr の定数と ctypes の構造体 (HmdMatrix34_t、VREvent_t など) は本物を使い、SteamVR に
つながる入口 (openvr.init / shutdown、IVRSystem / IVROverlay などのインターフェース) だけを
差し替える。製品のコードには手を入れない。

試験での使い方:

    with FakeOpenVR() as vr:
        overlay.startOverlay()
        ...
        vr.overlay_by_key("VRCT0").visible

アプリ全体に差し込むときは tools/fake_vr/sitecustomize.py が sidecar の Python で
install() を呼ぶ (docs/fake_vr.md)。

本物と同じにしているもの:
- 呼び出しの形 (引数の名前と順序、戻り値)。test_fake_openvr.py が本物のクラスと突き合わせる
- 失敗のしかた。SteamVR が動いていなければ init は InitError を、知らないハンドルには
  OverlayError を出す (pyopenvr の例外クラスをそのまま使う)
- getDeviceToAbsoluteTrackingPose に None を渡すと、配列を確保せず None を返す
- computeOverlayIntersection の UV の向き (models/overlay/overlay.py の uvToPixel で実機に合わせた向き)

本物より厳しくしているもの:
- shutdown の後で古いインターフェースを使うと FakeOpenVRMisuse を出し、misuse に記録する
  (本物は未定義の動作で、落ちることがある)。製品のコードは例外を広く捕まえるので、試験では
  vr.misuse が空であることを確かめる
- shutdown のときに消されていないオーバーレイを leaked に記録する
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from unittest import mock

import numpy as np
import openvr
import openvr.error_code as error_code

HMD = openvr.k_unTrackedDeviceIndex_Hmd
LEFT_HAND = 1
RIGHT_HAND = 2
# 本物のハンドルは 64bit の大きな値。小さな整数だと決めつけるコードに気づけるよう、大きな値から数える
_FIRST_HANDLE = 0x1000_0000_0001
_STEAMVR_PROCESSES = ("vrmonitor.exe", "vrmonitor", "vrserver.exe", "vrserver")


class FakeOpenVRMisuse(RuntimeError):
    """本物なら未定義の動作になる使い方 (shutdown の後で古いインターフェースを使うなど)。"""


def raise_openvr_error(cls: type, message: str = "") -> None:
    """pyopenvr の例外 (OverlayError_UnknownOverlay など) を、本物と同じエラー値で出す。"""
    for base in cls.__mro__[1:]:
        index = base.__dict__.get("error_index")
        if index:
            value = next(v for v, c in index.items() if c is cls)
            raise cls(value, message)
    raise cls(0, message)


def pose_matrix(position=(0.0, 0.0, 0.0), yaw_deg: float = 0.0, pitch_deg: float = 0.0) -> np.ndarray:
    """空間座標の 4x4。yaw は上 (+Y) 軸まわり、pitch は横 (+X) 軸まわり (正で上を向く)。前方は -Z。"""
    yaw, pitch = np.radians(yaw_deg), np.radians(pitch_deg)
    cy, sy, cp, sp = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch)
    r_yaw = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    r_pitch = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
    m = np.eye(4)
    m[:3, :3] = r_yaw @ r_pitch
    m[:3, 3] = position
    return m


def look_at(position, target) -> np.ndarray:
    """position から target の方を向いた (前方 -Z が target を指す) 4x4。"""
    position = np.asarray(position, dtype=float)
    forward = np.asarray(target, dtype=float) - position
    forward /= np.linalg.norm(forward)
    z = -forward
    up = np.array([0.0, 1.0, 0.0]) if abs(z[1]) < 0.99 else np.array([0.0, 0.0, 1.0])
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, position
    return m


def matrix34(m4: np.ndarray) -> Any:
    m = openvr.HmdMatrix34_t()
    for i in range(3):
        for j in range(4):
            m.m[i][j] = float(m4[i][j])
    return m


def matrix44(m34: Any) -> np.ndarray:
    m = np.eye(4)
    for i in range(3):
        for j in range(4):
            m[i][j] = m34.m[i][j]
    return m


@dataclass
class FakeDevice:
    device_class: int
    pose: np.ndarray
    role: Optional[int] = None
    connected: bool = True
    pose_valid: bool = True
    render_model: str = ""
    buttons: int = 0  # VRControllerState_t.ulButtonPressed
    axes: List[Tuple[float, float]] = field(default_factory=lambda: [(0.0, 0.0)] * 5)
    activity: int = openvr.k_EDeviceActivityLevel_UserInteraction
    tip: Optional[np.ndarray] = field(default_factory=lambda: np.eye(4))  # render model の "tip"。None なら見つからない

    def press(self, *buttons: int) -> None:
        for button in buttons:
            self.buttons |= 1 << button

    def release(self, *buttons: int) -> None:
        for button in buttons:
            self.buttons &= ~(1 << button)


@dataclass
class FakeOverlayState:
    handle: int
    key: str
    name: str
    visible: bool = False
    alpha: float = 1.0
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    width_m: float = 1.0
    sort_order: int = 0
    # ("absolute", 原点, 4x4) か ("device", 追従するデバイスの番号, 4x4)。未設定なら None
    transform: Optional[tuple] = None
    raw: Optional[Tuple[bytes, int, int, int]] = None  # (画素, 幅, 高さ, 1画素のバイト数)
    texture: Optional[Tuple[int, int, int]] = None  # (handle, eType, eColorSpace)
    bounds: Tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0)  # (uMin, uMax, vMin, vMax)
    raw_updates: int = 0
    texture_updates: int = 0

    def image(self):
        """setOverlayRaw で渡された画像 (PIL)。渡されていなければ None。"""
        if self.raw is None:
            return None
        from PIL import Image

        data, width, height, depth = self.raw
        mode = {1: "L", 3: "RGB", 4: "RGBA"}[depth]
        return Image.frombytes(mode, (width, height), data)


class _Interface:
    """インターフェースは、作ったときの接続でしか使えない (shutdown 後は無効)。"""

    def __init__(self, runtime: "FakeOpenVR") -> None:
        self._runtime = runtime
        self._connection = runtime.connection
        runtime.check_connected(type(self).__name__)

    def _check(self, method: str) -> "FakeOpenVR":
        runtime = self._runtime
        if not runtime.connected or runtime.connection != self._connection:
            runtime.misuse_of(f"{type(self).__name__}.{method} after shutdown")
        return runtime


class FakeVRSystem(_Interface):
    def getTrackedDeviceIndexForControllerRole(self, deviceType):
        vr = self._check("getTrackedDeviceIndexForControllerRole")
        with vr.lock:
            for index, device in vr.devices.items():
                if device.role == deviceType and device.connected:
                    return index
        return openvr.k_unTrackedDeviceIndexInvalid

    def isTrackedDeviceConnected(self, deviceIndex):
        vr = self._check("isTrackedDeviceConnected")
        with vr.lock:
            device = vr.devices.get(deviceIndex)
            return bool(device and device.connected)

    def getTrackedDeviceClass(self, deviceIndex):
        vr = self._check("getTrackedDeviceClass")
        with vr.lock:
            device = vr.devices.get(deviceIndex)
            return device.device_class if device else openvr.TrackedDeviceClass_Invalid

    def getDeviceToAbsoluteTrackingPose(self, origin, predictedSecondsToPhotonsFromNow: float, trackedDevicePoseArray):
        vr = self._check("getDeviceToAbsoluteTrackingPose")
        if trackedDevicePoseArray is None:
            return None  # 本物も、None なら何も書かずに None を返す
        if not isinstance(trackedDevicePoseArray, ctypes.Array):
            trackedDevicePoseArray = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
        with vr.lock:
            for index in range(len(trackedDevicePoseArray)):
                pose = trackedDevicePoseArray[index]
                device = vr.devices.get(index)
                pose.bDeviceIsConnected = bool(device and device.connected)
                pose.bPoseIsValid = bool(device and device.connected and device.pose_valid)
                pose.eTrackingResult = openvr.TrackingResult_Running_OK if pose.bPoseIsValid else openvr.TrackingResult_Uninitialized
                m = device.pose if device is not None else np.eye(4)
                for i in range(3):
                    for j in range(4):
                        pose.mDeviceToAbsoluteTracking[i][j] = float(m[i][j])
        return trackedDevicePoseArray

    def getControllerState(self, controllerDeviceIndex):
        vr = self._check("getControllerState")
        state = openvr.VRControllerState_t()
        with vr.lock:
            device = vr.devices.get(controllerDeviceIndex)
            if device is None or not device.connected or device.device_class != openvr.TrackedDeviceClass_Controller:
                return False, state
            vr.packet += 1
            state.unPacketNum = vr.packet
            state.ulButtonPressed = device.buttons
            for i, (x, y) in enumerate(device.axes[:5]):
                state.rAxis[i].x, state.rAxis[i].y = x, y
        return True, state

    def getStringTrackedDeviceProperty(self, deviceIndex, prop):
        vr = self._check("getStringTrackedDeviceProperty")
        with vr.lock:
            device = vr.devices.get(deviceIndex)
            if device is None or not device.connected:
                raise_openvr_error(error_code.TrackedProp_InvalidDevice)
            if prop == openvr.Prop_RenderModelName_String:
                return device.render_model
        raise_openvr_error(error_code.TrackedProp_UnknownProperty)

    def getTrackedDeviceActivityLevel(self, deviceId):
        vr = self._check("getTrackedDeviceActivityLevel")
        with vr.lock:
            device = vr.devices.get(deviceId)
            return device.activity if device else openvr.k_EDeviceActivityLevel_Unknown

    def pollNextEvent(self, event):
        vr = self._check("pollNextEvent")
        with vr.lock:
            if not vr.events:
                return False
            event_type, device_index = vr.events.popleft()
        event.eventType = event_type
        event.trackedDeviceIndex = device_index
        event.eventAgeSeconds = 0.0
        return True


class FakeVROverlay(_Interface):
    def _overlay(self, method: str, overlayHandle) -> FakeOverlayState:
        vr = self._check(method)
        state = vr.overlays.get(overlayHandle)
        if state is None:
            raise_openvr_error(error_code.OverlayError_UnknownOverlay, f"{method}({overlayHandle})")
        return state

    def createOverlay(self, overlayKey: str, overlayName: str):
        vr = self._check("createOverlay")
        with vr.lock:
            if any(state.key == overlayKey for state in vr.overlays.values()):
                raise_openvr_error(error_code.OverlayError_KeyInUse, overlayKey)
            handle = vr.next_handle
            vr.next_handle += 1
            vr.overlays[handle] = FakeOverlayState(handle, overlayKey, overlayName)
            vr.created.append(overlayKey)
        return handle

    def destroyOverlay(self, overlayHandle) -> None:
        vr = self._check("destroyOverlay")
        with vr.lock:
            self._overlay("destroyOverlay", overlayHandle)
            vr.destroyed.append(vr.overlays.pop(overlayHandle))

    def findOverlay(self, overlayKey: str):
        vr = self._check("findOverlay")
        with vr.lock:
            for state in vr.overlays.values():
                if state.key == overlayKey:
                    return state.handle
        raise_openvr_error(error_code.OverlayError_UnknownOverlay, overlayKey)

    def showOverlay(self, overlayHandle) -> None:
        with self._runtime.lock:
            self._overlay("showOverlay", overlayHandle).visible = True

    def hideOverlay(self, overlayHandle) -> None:
        with self._runtime.lock:
            self._overlay("hideOverlay", overlayHandle).visible = False

    def setOverlayAlpha(self, overlayHandle, alpha: float) -> None:
        with self._runtime.lock:
            self._overlay("setOverlayAlpha", overlayHandle).alpha = float(alpha)

    def setOverlayColor(self, overlayHandle, red: float, green: float, blue: float) -> None:
        with self._runtime.lock:
            self._overlay("setOverlayColor", overlayHandle).color = (float(red), float(green), float(blue))

    def setOverlayWidthInMeters(self, overlayHandle, widthInMeters: float) -> None:
        if widthInMeters <= 0:
            raise_openvr_error(error_code.OverlayError_InvalidParameter, f"width {widthInMeters}")
        with self._runtime.lock:
            self._overlay("setOverlayWidthInMeters", overlayHandle).width_m = float(widthInMeters)

    def setOverlaySortOrder(self, overlayHandle, sortOrder) -> None:
        with self._runtime.lock:
            self._overlay("setOverlaySortOrder", overlayHandle).sort_order = int(sortOrder)

    def setOverlayRaw(self, overlayHandle, buffer, width, height, bytesPerPixel) -> None:
        if bytesPerPixel not in (1, 3, 4) or width <= 0 or height <= 0:
            raise_openvr_error(error_code.OverlayError_InvalidParameter, f"{width}x{height}x{bytesPerPixel}")
        size = width * height * bytesPerPixel
        if ctypes.sizeof(buffer) < size:
            # 本物は足りない分を読みに行く (落ちることがある)
            self._runtime.misuse_of(f"setOverlayRaw buffer {ctypes.sizeof(buffer)} < {size}")
        data = ctypes.string_at(ctypes.addressof(buffer), size)
        with self._runtime.lock:
            state = self._overlay("setOverlayRaw", overlayHandle)
            state.raw = (data, int(width), int(height), int(bytesPerPixel))
            state.texture = None
            state.raw_updates += 1

    def setOverlayTexture(self, overlayHandle, texture) -> None:
        vr = self._runtime
        with vr.lock:
            state = self._overlay("setOverlayTexture", overlayHandle)
            state.texture = (int(texture.handle or 0), int(texture.eType), int(texture.eColorSpace))
            state.raw = None
            state.texture_updates += 1
        if vr.on_texture is not None:
            vr.on_texture(state, texture)  # 渡した側のスレッド (OpenGL の環境が今のもの) で呼ぶ

    def setOverlayTextureBounds(self, overlayHandle, overlayTextureBounds) -> None:
        b = overlayTextureBounds
        with self._runtime.lock:
            self._overlay("setOverlayTextureBounds", overlayHandle).bounds = (b.uMin, b.uMax, b.vMin, b.vMax)

    def setOverlayTransformAbsolute(self, overlayHandle, trackingOrigin, trackingOriginToOverlayTransform) -> None:
        with self._runtime.lock:
            state = self._overlay("setOverlayTransformAbsolute", overlayHandle)
            state.transform = ("absolute", int(trackingOrigin), matrix44(trackingOriginToOverlayTransform))

    def setOverlayTransformTrackedDeviceRelative(self, overlayHandle, trackedDevice, trackedDeviceToOverlayTransform) -> None:
        vr = self._runtime
        with vr.lock:
            state = self._overlay("setOverlayTransformTrackedDeviceRelative", overlayHandle)
            if trackedDevice not in vr.devices:
                raise_openvr_error(error_code.OverlayError_InvalidTrackedDevice, str(trackedDevice))
            state.transform = ("device", int(trackedDevice), matrix44(trackedDeviceToOverlayTransform))

    def computeOverlayIntersection(self, overlayHandle, params):
        vr = self._runtime
        results = openvr.VROverlayIntersectionResults_t()
        with vr.lock:
            state = self._overlay("computeOverlayIntersection", overlayHandle)
            hit = vr.intersect(state, [params.vSource.v[i] for i in range(3)], [params.vDirection.v[i] for i in range(3)])
        if hit is None:
            return False, results
        point, normal, uv, distance = hit
        for i in range(3):
            results.vPoint.v[i] = point[i]
            results.vNormal.v[i] = normal[i]
        results.vUVs.v[0], results.vUVs.v[1] = uv
        results.fDistance = distance
        return True, results


class FakeVRRenderModels(_Interface):
    def getComponentState(self, renderModelName: str, componentName: str, controllerState, state):
        vr = self._check("getComponentState")
        component = openvr.RenderModel_ComponentState_t()
        with vr.lock:
            device = next((d for d in vr.devices.values() if d.render_model and d.render_model == renderModelName), None)
            tip = device.tip if device is not None and componentName == "tip" else None
        if tip is None:
            return False, component
        for i in range(3):
            for j in range(4):
                component.mTrackingToComponentLocal[i][j] = float(tip[i][j])
                component.mTrackingToComponentRenderModel[i][j] = float(tip[i][j])
        return True, component


class FakeVRApplications(_Interface):
    def getApplicationCount(self):
        return len(self._check("getApplicationCount").applications)

    def getApplicationKeyByIndex(self, applicationIndex):
        apps = self._check("getApplicationKeyByIndex").applications
        if not 0 <= applicationIndex < len(apps):
            raise_openvr_error(error_code.ApplicationError_InvalidIndex)
        return apps[applicationIndex][0]

    def getApplicationPropertyString(self, appKey: str, property_):
        apps = dict(self._check("getApplicationPropertyString").applications)
        if appKey not in apps:
            raise_openvr_error(error_code.ApplicationError_UnknownApplication, appKey)
        if property_ != openvr.VRApplicationProperty_Name_String:
            raise_openvr_error(error_code.ApplicationError_UnknownProperty)
        return apps[appKey]


class FakeVRCompositor(_Interface):
    """ヘッドセットに映っている画像 (ミラー) を、OpenGL のテクスチャで渡す (Linux の OCR の VR の撮影)。

    本物と同じく、テクスチャは lock と unlock の間だけ読める。読んだかどうかは偽物には分からないので、
    lock・unlock・release の順番だけを確かめる。
    """

    def getLastFrameRenderer(self):
        return self._check("getLastFrameRenderer").scene_pid

    def getCurrentSceneFocusProcess(self):
        return self._check("getCurrentSceneFocusProcess").scene_pid

    def getMirrorTextureGL(self, eye):
        vr = self._check("getMirrorTextureGL")
        with vr.lock:
            if vr.mirror is None:
                raise_openvr_error(error_code.CompositorError_InvalidTexture, "fake openvr shows nothing in the headset")
            texture = vr.make_mirror_texture(vr.mirror)
            vr.next_handle += 1
            vr.mirror_textures[vr.next_handle] = [texture, False]  # [テクスチャ番号, lock 中か]
            return texture, vr.next_handle

    def _entry(self, method: str, handle):
        vr = self._check(method)
        entry = vr.mirror_textures.get(int(getattr(handle, "value", handle) or 0))
        if entry is None:
            vr.misuse_of(f"{method} with an unknown shared texture handle")
        return vr, entry

    def lockGLSharedTextureForAccess(self, sharedTextureHandle) -> None:
        vr, entry = self._entry("lockGLSharedTextureForAccess", sharedTextureHandle)
        if entry[1]:
            vr.misuse_of("lockGLSharedTextureForAccess twice")
        entry[1] = True
        vr.mirror_locks += 1

    def unlockGLSharedTextureForAccess(self, sharedTextureHandle) -> None:
        vr, entry = self._entry("unlockGLSharedTextureForAccess", sharedTextureHandle)
        if not entry[1]:
            vr.misuse_of("unlockGLSharedTextureForAccess without a lock")
        entry[1] = False

    def releaseSharedGLTexture(self, textureId, sharedTextureHandle):
        vr, entry = self._entry("releaseSharedGLTexture", sharedTextureHandle)
        if entry[1]:
            vr.misuse_of("releaseSharedGLTexture while locked")
        del vr.mirror_textures[int(getattr(sharedTextureHandle, "value", sharedTextureHandle))]
        return True


def gl_texture_from_rgb(image: np.ndarray) -> int:
    """今の OpenGL の環境に、画像 (高さ, 幅, RGB。上の行が先) のテクスチャを作る。"""
    from OpenGL import GL

    height, width = image.shape[:2]
    texture = int(GL.glGenTextures(1))
    GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
    GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
    # OpenGL は下の行から並べる
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB8, width, height, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE,
                    np.ascontiguousarray(image[::-1, :, :3]).tobytes())
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return texture


class FakeOpenVR:
    """SteamVR の代わり。デバイスの姿勢・ボタン、オーバーレイの状態、イベントを持つ。

    既定では頭 (番号 0) が 1.6m の高さで前 (-Z) を向き、左手 (1)・右手 (2) は下ろしている。
    """

    def __init__(self, *, steamvr_running: bool = True, hmd_present: bool = True,
                 applications: Optional[List[Tuple[str, str]]] = None,
                 on_texture: Optional[Callable[[FakeOverlayState, Any], None]] = None) -> None:
        self.lock = threading.RLock()
        self.steamvr_running = steamvr_running
        self.hmd_present = hmd_present
        self.applications = list(applications if applications is not None else [("steam.app.438100", "VRChat")])
        self.on_texture = on_texture
        self.texture_sizes: Dict[int, Tuple[int, int]] = {}  # OpenGL のテクスチャ番号 -> (幅, 高さ)。当たり判定の縦横比に使う
        self.texture_size_of: Optional[Callable[[int], Optional[Tuple[int, int]]]] = None
        self.devices: Dict[int, FakeDevice] = {
            HMD: FakeDevice(openvr.TrackedDeviceClass_HMD, pose_matrix((0.0, 1.6, 0.0)), render_model="generic_hmd", tip=None),
            # 手は下ろして床を指している (既定ではどのオーバーレイにも当たらない)
            LEFT_HAND: FakeDevice(openvr.TrackedDeviceClass_Controller, pose_matrix((-0.2, 1.0, -0.2), pitch_deg=-80),
                                  role=openvr.TrackedControllerRole_LeftHand, render_model="fake_controller_left"),
            RIGHT_HAND: FakeDevice(openvr.TrackedDeviceClass_Controller, pose_matrix((0.2, 1.0, -0.2), pitch_deg=-80),
                                   role=openvr.TrackedControllerRole_RightHand, render_model="fake_controller_right"),
        }
        self.overlays: Dict[int, FakeOverlayState] = {}
        self.created: List[str] = []
        self.destroyed: List[FakeOverlayState] = []
        self.leaked: List[FakeOverlayState] = []  # shutdown の時点で消されていなかったオーバーレイ
        self.events: Deque[Tuple[int, int]] = deque()
        self.misuse: List[str] = []
        # ヘッドセットに映っている画像 (高さ, 幅, RGB)。None の間はミラーを渡さない (IVRCompositor が無いのと同じ)
        self.mirror: Optional[np.ndarray] = None
        self.scene_pid = 0  # 今 SteamVR に映しているアプリのプロセス番号
        self.make_mirror_texture: Callable[[np.ndarray], int] = gl_texture_from_rgb
        self.mirror_textures: Dict[int, list] = {}
        self.mirror_locks = 0
        self.connected = False
        self.connection = 0
        self.init_calls = 0
        self.shutdown_calls = 0
        self.next_handle = _FIRST_HANDLE
        self.packet = 0
        self._stack: Optional[ExitStack] = None

    # --- 差し込み ---

    def install(self) -> "FakeOpenVR":
        if self._stack is not None:
            raise RuntimeError("FakeOpenVR is already installed")
        stack = ExitStack()
        try:
            for name, value in self.replacements().items():
                stack.enter_context(mock.patch.object(openvr, name, value))
            self._patchSteamvrProcess(stack)
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        return self

    def uninstall(self) -> None:
        stack, self._stack = self._stack, None
        if stack is not None:
            stack.close()

    def __enter__(self) -> "FakeOpenVR":
        return self.install()

    def __exit__(self, *exc) -> None:
        self.uninstall()

    def replacements(self) -> Dict[str, Any]:
        return {
            "init": self.init,
            "shutdown": self.shutdown,
            "VRSystem": lambda: FakeVRSystem(self),
            "IVRSystem": lambda: FakeVRSystem(self),
            "VROverlay": lambda: FakeVROverlay(self),
            "IVROverlay": lambda: FakeVROverlay(self),
            "VRRenderModels": lambda: FakeVRRenderModels(self),
            "IVRRenderModels": lambda: FakeVRRenderModels(self),
            "VRApplications": lambda: FakeVRApplications(self),
            "IVRApplications": lambda: FakeVRApplications(self),
            # ミラー画面 (OCR の VR の撮影) は、mirror に画像を入れたときだけ渡す (OpenGL の読み取り。Linux)。
            # 入れていなければ、つながらないときと同じ失敗にする
            "VRCompositor": self.compositor,
            "IVRCompositor": self.compositor,
        }

    def _patchSteamvrProcess(self, stack: ExitStack) -> None:
        """SteamVR のプロセス (vrmonitor) が動いているかを、steamvr_running で答えるようにする。"""
        try:
            from models import process_check
        except ImportError:
            return
        original = process_check.isProcessRunning

        def isProcessRunning(name: str) -> bool:
            if name.lower() in _STEAMVR_PROCESSES:
                return self.steamvr_running
            return original(name)

        stack.enter_context(mock.patch.object(process_check, "isProcessRunning", isProcessRunning))
        # `from models.process_check import isProcessRunning` で読み込み済みのモジュールも差し替える
        for module in list(sys.modules.values()):
            namespace = getattr(module, "__dict__", None) or {}
            if module is not process_check and namespace.get("isProcessRunning") is original:
                stack.enter_context(mock.patch.object(module, "isProcessRunning", isProcessRunning))

    # --- openvr の入口 ---

    def init(self, applicationType, pStartupInfo=None):
        with self.lock:
            if not self.steamvr_running:
                raise_openvr_error(error_code.InitError_Init_NoServerForBackgroundApp)
            if not self.hmd_present:
                raise_openvr_error(error_code.InitError_Init_HmdNotFound)
            self.connected = True
            self.connection += 1
            self.init_calls += 1
        return FakeVRSystem(self)

    def shutdown(self) -> None:
        with self.lock:
            if self.connected:
                # SteamVR は、つないでいたアプリのオーバーレイを接続を閉じたときに消す
                self.leaked.extend(self.overlays.values())
                self.overlays.clear()
            self.connected = False
            self.shutdown_calls += 1

    def compositor(self):
        self.check_connected("IVRCompositor")
        if self.mirror is None:
            raise_openvr_error(error_code.InitError_Init_InterfaceNotFound, "fake openvr has no compositor")
        return FakeVRCompositor(self)

    def check_connected(self, name: str) -> None:
        if not self.connected:
            raise_openvr_error(error_code.InitError_Init_NotInitialized, name)

    def misuse_of(self, what: str) -> None:
        with self.lock:
            self.misuse.append(what)
        raise FakeOpenVRMisuse(what)

    # --- 試験から操作する ---

    def quit(self, *, stop_steamvr: bool = True) -> None:
        """SteamVR を終える。VREvent_Quit を送り、既定では vrmonitor も止まったことにする。"""
        with self.lock:
            self.events.append((openvr.VREvent_Quit, HMD))
            if stop_steamvr:
                self.steamvr_running = False

    def overlay_by_key(self, key: str) -> Optional[FakeOverlayState]:
        with self.lock:
            return next((state for state in self.overlays.values() if state.key == key), None)

    def world_pose(self, state: FakeOverlayState) -> Optional[np.ndarray]:
        """オーバーレイの空間座標の 4x4。追従先の姿勢が無ければ None。"""
        with self.lock:
            if state.transform is None:
                return None
            kind, target, relative = state.transform
            if kind == "absolute":
                return relative.copy()
            device = self.devices.get(target)
            if device is None or not device.connected or not device.pose_valid:
                return None
            return device.pose @ relative

    def aspect(self, state: FakeOverlayState) -> float:
        """オーバーレイの 高さ/幅。テクスチャの大きさが分からなければ正方形とみなす。"""
        u0, u1, v0, v1 = state.bounds
        if state.raw is not None:
            width, height = state.raw[1] * abs(u1 - u0), state.raw[2] * abs(v1 - v0)
        else:
            size = None
            if state.texture is not None:
                size = self.texture_sizes.get(state.texture[0])
                if size is None and self.texture_size_of is not None:
                    size = self.texture_size_of(state.texture[0])
            tw, th = size or (1, 1)
            width, height = tw * abs(u1 - u0), th * abs(v1 - v0)
        return height / width if width > 0 else 1.0

    def intersect(self, state: FakeOverlayState, source, direction) -> Optional[tuple]:
        """光線とオーバーレイの交点 (点, 法線, UV, 距離)。見えているかどうかは見ない。"""
        pose = self.world_pose(state)
        if pose is None:
            return None
        source, direction = np.asarray(source, float), np.asarray(direction, float)
        length = np.linalg.norm(direction)
        if length == 0:
            return None
        direction = direction / length
        normal = pose[:3, 2]
        denominator = float(np.dot(direction, normal))
        if abs(denominator) < 1e-9:
            return None
        distance = float(np.dot(pose[:3, 3] - source, normal)) / denominator
        if distance < 0:
            return None
        point = source + distance * direction
        local = np.linalg.inv(pose) @ np.append(point, 1.0)
        width = state.width_m
        height = width * self.aspect(state)
        if abs(local[0]) > width / 2 or abs(local[1]) > height / 2:
            return None
        # UV は左下が原点で、縦も横幅を 1 とした長さで中心から測る (実機の向き。overlay.py の uvToPixel)
        uv = (local[0] / width + 0.5, 0.5 + local[1] / width)
        return point, normal, uv, distance

    def aim(self, device_index: int, state: FakeOverlayState, *, at=(0.0, 0.0), distance: float = 0.4,
            laser_pitch_deg: float = 0.0) -> None:
        """コントローラを、オーバーレイの表側 distance m から指させる。at はオーバーレイの中心からの (x, y) m。

        アプリがレーザーを本体の前方から laser_pitch_deg 度上げて出すなら、その分だけ本体を下に向ける
        (overlay.py の _LASER_PITCH_UP_DEG)。
        """
        pose = self.world_pose(state)
        if pose is None:
            raise ValueError(f"overlay {state.key} has no pose")
        target = (pose @ np.array([at[0], at[1], 0.0, 1.0]))[:3]
        with self.lock:
            self.devices[device_index].pose = (look_at(target + pose[:3, 2] * distance, target)
                                               @ pose_matrix(pitch_deg=-laser_pitch_deg))
