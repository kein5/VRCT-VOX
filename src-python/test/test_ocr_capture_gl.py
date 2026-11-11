"""Linux の OCR の VR の撮影: OpenVR のミラーを OpenGL で読む。OpenGL と GLFW は偽物に差し替える。"""
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from fake_openvr import FakeOpenVR, FakeOpenVRMisuse
from models import openvr_session
from models.ocr import ocr_capture
from models.ocr.ocr_capture_gl import GlMirror
from models.ocr.ocr_capture_openvr import OpenVRMirrorCapture

# 上の行が赤、下の行が青の 2x2
PICTURE = np.array([[[255, 0, 0], [255, 0, 0]], [[0, 0, 255], [0, 0, 255]]], np.uint8)


class FakeGl:
    """テクスチャ番号ごとに画像を持ち、OpenGL と同じく下の行から返す。"""

    GL_TEXTURE_2D, GL_TEXTURE_WIDTH, GL_TEXTURE_HEIGHT = "2d", "width", "height"
    GL_RGB, GL_UNSIGNED_BYTE, GL_PACK_ALIGNMENT = "rgb", "ubyte", "pack"

    def __init__(self):
        self.textures, self.bound, self.calls = {}, 0, []

    def make(self, image):
        number = len(self.textures) + 7
        self.textures[number] = image
        return number

    def glBindTexture(self, target, texture):
        self.bound = texture
        self.calls.append(("bind", texture))

    def glGetTexLevelParameteriv(self, target, level, name):
        height, width = self.textures[self.bound].shape[:2]
        return width if name == self.GL_TEXTURE_WIDTH else height

    def glPixelStorei(self, name, value):
        self.calls.append(("pack", value))

    def glGetTexImage(self, target, level, fmt, kind):
        self.calls.append(("read", self.bound))
        return np.ascontiguousarray(self.textures[self.bound][::-1])


class FakeGlfw:
    VISIBLE = "visible"

    def __init__(self, *, window="window"):
        self.window, self.calls = window, []

    def init(self):
        return True

    def window_hint(self, name, value):
        self.calls.append(("hint", name, value))

    def create_window(self, *args):
        return self.window

    def make_context_current(self, window):
        self.calls.append(("current", window))

    def destroy_window(self, window):
        self.calls.append(("destroy", window))


@pytest.fixture
def rig():
    gl, glfw = FakeGl(), FakeGlfw()
    vr = FakeOpenVR()
    vr.mirror, vr.make_mirror_texture, vr.scene_pid = PICTURE, gl.make, 4321
    vr.install()
    with patch.dict(sys.modules, {"glfw": glfw, "OpenGL": SimpleNamespace(GL=gl)}):
        yield SimpleNamespace(vr=vr, gl=gl, glfw=glfw)
    vr.uninstall()


def test_the_mirror_is_read_between_lock_and_unlock_top_row_first(rig):
    import openvr

    openvr.init(openvr.VRApplication_Background)
    mirror = GlMirror(None, openvr.IVRCompositor(), openvr.Eye_Left)
    assert ("hint", "visible", False) in rig.glfw.calls
    frame = mirror.read()
    assert frame.shape == (2, 2, 3)
    np.testing.assert_array_equal(frame, PICTURE)  # 上の行が先
    assert rig.vr.mirror_locks == 1 and [locked for _, locked in rig.vr.mirror_textures.values()] == [False]
    mirror.read()
    assert rig.vr.mirror_locks == 2 and len(rig.vr.mirror_textures) == 1  # 取り直さず、同じテクスチャを読む
    mirror.close()
    assert rig.vr.mirror_textures == {} and rig.glfw.calls[-1] == ("destroy", "window")
    mirror.close()  # 2回目は何もしない
    assert rig.vr.misuse == []
    openvr.shutdown()


def test_a_failed_read_still_unlocks(rig):
    import openvr

    openvr.init(openvr.VRApplication_Background)
    mirror = GlMirror(None, openvr.IVRCompositor(), openvr.Eye_Left)
    with patch.object(rig.gl, "glGetTexImage", side_effect=RuntimeError("gl lost")), pytest.raises(RuntimeError):
        mirror.read()
    assert [locked for _, locked in rig.vr.mirror_textures.values()] == [False]
    mirror.close()
    assert rig.vr.misuse == []
    openvr.shutdown()


def test_no_window_means_no_mirror(rig):
    import openvr

    rig.glfw.window = None
    openvr.init(openvr.VRApplication_Background)
    with pytest.raises(RuntimeError, match="create_window"):
        GlMirror(None, openvr.IVRCompositor(), openvr.Eye_Left)
    assert rig.vr.mirror_textures == {}
    openvr.shutdown()


def test_the_fake_compositor_reports_misuse(rig):
    import openvr

    openvr.init(openvr.VRApplication_Background)
    compositor = openvr.IVRCompositor()
    texture, handle = compositor.getMirrorTextureGL(openvr.Eye_Left)
    with pytest.raises(FakeOpenVRMisuse):
        compositor.unlockGLSharedTextureForAccess(handle)
    compositor.lockGLSharedTextureForAccess(handle)
    with pytest.raises(FakeOpenVRMisuse):
        compositor.releaseSharedGLTexture(texture, handle)
    openvr.shutdown()


def test_on_linux_the_capture_reads_vrchats_headset_view_as_bgr(rig):
    capture = OpenVRMirrorCapture()
    with patch("models.ocr.ocr_capture_openvr.sys.platform", "linux"), \
         patch("models.ocr.ocr_capture_openvr._glAvailable", return_value=True), \
         patch("models.ocr.ocr_capture_openvr.Process", lambda pid: SimpleNamespace(name=lambda: "VRChat.exe")):
        assert capture.isAvailable()
        frame = capture.capture()
        np.testing.assert_array_equal(frame, PICTURE[:, :, ::-1])
        rig.vr.scene_pid = 0  # VRChat を映していない (SteamVR Home など)
        assert capture.capture() is None
        capture.close()
    assert rig.vr.mirror_textures == {} and rig.vr.misuse == []
    assert not openvr_session.is_active()


def test_the_headset_view_is_a_source_wherever_it_can_be_read():
    with patch.object(OpenVRMirrorCapture, "isAvailable", return_value=True):
        assert ocr_capture.availableCaptureSources() == ["window", "vr"]
    with patch.object(OpenVRMirrorCapture, "isAvailable", return_value=False):
        assert ocr_capture.availableCaptureSources() == ["window"]


def test_linux_needs_the_gl_libraries_for_the_headset_view():
    with patch("models.ocr.ocr_capture_openvr.sys.platform", "linux"):
        with patch("models.ocr.ocr_capture_openvr._glAvailable", return_value=False):
            assert not OpenVRMirrorCapture().isAvailable()
        with patch("models.ocr.ocr_capture_openvr._glAvailable", return_value=True):
            assert OpenVRMirrorCapture().isAvailable()
    with patch("models.ocr.ocr_capture_openvr.sys.platform", "darwin"):
        assert not OpenVRMirrorCapture().isAvailable()


def test_on_linux_a_failed_start_is_not_repeated_at_once(rig):
    rig.vr.mirror = None  # the compositor hands out nothing
    capture = OpenVRMirrorCapture()
    with patch("models.ocr.ocr_capture_openvr.sys.platform", "linux"), \
         patch("models.ocr.ocr_capture_openvr._glAvailable", return_value=True), \
         patch("models.ocr.ocr_capture_openvr.errorLogging"), patch("models.ocr.ocr_capture_openvr.printLog"):
        assert capture.capture() is None
        attempts = rig.vr.init_calls
        assert capture.capture() is None
        assert rig.vr.init_calls == attempts  # waits before it opens OpenVR and OpenGL again
        capture._retry_at = 0.0
        rig.vr.mirror = PICTURE
        with patch("models.ocr.ocr_capture_openvr.Process", lambda pid: SimpleNamespace(name=lambda: "vrchat.exe")):
            assert capture.capture() is not None
        capture.close()
    assert not openvr_session.is_active()
