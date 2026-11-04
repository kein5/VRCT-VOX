"""Overlay ownership/publication races; no runtime, GL, capture or device calls.

Events order the real delivery threads. Fake threads cover owner reconnects and
blocked capture without sleeping or starting native workers.
"""
from threading import Event, Thread, get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

import controller as controller_module
import model as model_module
from controller import Controller
from model import Model
from models.overlay import overlay as module
from models.overlay.overlay import Overlay, PANEL
from models.overlay.overlay_image import OverlayImage


def settings():
    return dict(x_pos=0, y_pos=0, z_pos=0, x_rotation=0, y_rotation=0, z_rotation=0,
                tracker="HMD", opacity=1.0, ui_scaling=1.0, display_duration=5, fadeout_duration=2)


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    monkeypatch.setattr(module, "errorLogging", Mock())
    monkeypatch.setattr(module, "printLog", Mock())
    monkeypatch.setattr(module, "raiseThreadPriority", Mock())
    monkeypatch.setattr(module.openvr_session, "acquire", Mock(return_value=object()))
    monkeypatch.setattr(module.openvr_session, "release", Mock())
    monkeypatch.setattr(module.openvr, "IVRSystem", Mock())
    monkeypatch.setattr(module, "window_capture", Mock())


def destination():
    overlay = Overlay({"small": settings(), "large": settings()})
    overlay.initialized = True
    overlay.overlay = Mock()
    overlay.handle = {"small": 1, "large": 2}
    return overlay


class InlineThread:
    """Run owner synchronously, without pretending the owner is still alive."""
    def __init__(self, target, args=(), daemon=False):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass


@pytest.mark.parametrize("failure", ["second_handle", "pointer_upload", "alpha"])
def test_owner_releases_partial_construction_once_and_next_on_works(monkeypatch, failure):
    overlay = Overlay({"small": settings(), "large": settings()})
    overlay.vr_panel_enabled = False
    native = Mock()
    serial = iter(range(1, 50))
    created, destroyed = [], []
    fail = [True]

    def create(*args):
        if failure == "second_handle" and len(created) == 1 and fail[0]:
            raise RuntimeError("construction")
        handle = next(serial)
        created.append(handle)
        return handle

    def upload(*args):
        if failure == "pointer_upload" and fail[0]:
            raise RuntimeError("pointer upload")

    def alpha(*args):
        if failure == "alpha" and fail[0]:
            raise RuntimeError("alpha")

    native.createOverlay.side_effect = create
    native.setOverlayRaw.side_effect = upload
    native.setOverlayAlpha.side_effect = alpha
    native.destroyOverlay.side_effect = destroyed.append
    monkeypatch.setattr(module.openvr, "IVROverlay", lambda: native)
    monkeypatch.setattr(module, "Thread", InlineThread)
    monkeypatch.setattr(overlay, "checkSteamvrRunning", lambda: True)
    monkeypatch.setattr(overlay, "mainloop", lambda: setattr(overlay, "start_cancelled", True))
    overlay.failure_callback = Mock()
    assert overlay.startOverlay() is False
    assert destroyed == created
    assert len(destroyed) == len(set(destroyed))
    assert not overlay.initialized and not overlay.init_process
    overlay.failure_callback.assert_called_once_with("runtime")
    module.openvr_session.release.assert_called_once()
    overlay.shutdownOverlay()
    fail[0] = False
    assert overlay.startOverlay() is True
    assert module.openvr_session.acquire.call_count == 2
    assert module.openvr_session.release.call_count == 2
    assert destroyed == created


@pytest.mark.parametrize("stage", ["window_hint", "make_context_current", "glTexParameteri", "glTexImage2D"])
def test_partial_gl_is_registered_and_released_on_owner(monkeypatch, stage):
    overlay = Overlay({PANEL: settings()})
    glfw, gl = Mock(), Mock()
    glfw.init.return_value = True
    glfw.create_window.return_value = "window"
    gl.glGenTextures.side_effect = [11, 12]
    cleanup = []
    glfw.destroy_window.side_effect = lambda value: cleanup.append(("window", get_ident()))
    glfw.terminate.side_effect = lambda: cleanup.append(("glfw", get_ident()))
    gl.glDeleteTextures.side_effect = lambda values: cleanup.append((tuple(values), get_ident()))
    target = glfw if stage in ("window_hint", "make_context_current") else gl
    getattr(target, stage).side_effect = RuntimeError(stage)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(__import__('sys').modules, "glfw", glfw)
    monkeypatch.setitem(__import__('sys').modules, "OpenGL", SimpleNamespace(GL=gl))
    monkeypatch.setattr(overlay, "checkSteamvrRunning", lambda: True)
    monkeypatch.setattr(overlay, "init", overlay.initPanelTexture)
    owner = get_ident()
    overlay.main()
    assert overlay.gl is None and overlay.failure == "runtime"
    assert all(thread == owner for _, thread in cleanup)
    assert sum(kind == "glfw" for kind, _ in cleanup) == 1
    expected_textures = [11, 12] if stage == "glTexImage2D" else [11] if stage == "glTexParameteri" else []
    if expected_textures:
        gl.glDeleteTextures.assert_called_once_with(expected_textures)
    overlay.teardown()
    assert sum(kind == "glfw" for kind, _ in cleanup) == 1


def test_frame_alpha_failure_cleans_owner_and_stops_watcher(monkeypatch):
    overlay = Overlay({"small": settings()})
    native = Mock()
    failure = Mock()
    overlay.failure_callback = failure
    stops = []

    class Watcher:
        def __init__(self, target, args, daemon):
            self.stop = args[-1]
            stops.append(self.stop)
        def start(self):
            pass
        def join(self, timeout):
            assert self.stop.is_set() and timeout == module._SHUTDOWN_JOIN_TIMEOUT_SEC

    def init():
        overlay.system = object()
        overlay.overlay = native
        overlay.handle = {"small": 1}
        overlay.owned_handles = [1]
        overlay.initialized = True
        native.setOverlayAlpha.side_effect = RuntimeError("frame alpha")

    monkeypatch.setattr(module, "Thread", Watcher)
    monkeypatch.setattr(overlay, "init", init)
    monkeypatch.setattr(overlay, "checkSteamvrRunning", lambda: True)
    monkeypatch.setattr(overlay, "checkActive", lambda: True)
    overlay.main()
    native.destroyOverlay.assert_called_once_with(1)
    module.openvr_session.release.assert_called_once()
    failure.assert_called_once_with("runtime")
    assert not overlay.initialized and not overlay.loop and not overlay.init_process
    assert len(stops) == 1 and stops[0].is_set()


@pytest.mark.parametrize("revoke", ["delivery", "off", "off_on", "shutdown"])
def test_failed_upload_after_revocation_never_reconnects_or_retries(revoke, monkeypatch):
    overlay = destination()
    enabled = [True]
    current = [True]
    def failed(*args):
        if revoke == "delivery":
            current[0] = False
        elif revoke in ("off", "off_on"):
            enabled[0] = False
            overlay.output_generations["large"] = 1
            if revoke == "off_on":
                enabled[0] = True
        else:
            overlay.shutdownOverlay()
        raise RuntimeError("upload")
    overlay.overlay.setOverlayRaw.side_effect = failed
    monkeypatch.setattr(overlay, "reStartOverlay", Mock())
    assert overlay.updateImage(Image.new("RGBA", (2, 2)), "large",
                               current=lambda: current[0] and enabled[0]) is False
    overlay.reStartOverlay.assert_not_called()
    overlay.overlay.setOverlayRaw.assert_called_once()
    assert "large" not in overlay.images


def test_revoked_during_serialization_is_not_uploaded():
    overlay = destination()
    current = [True]
    image = Mock(size=(1, 1))
    def serialize():
        current[0] = False
        return bytes(4)
    image.tobytes.side_effect = serialize
    assert overlay.updateImage(image, "large", current=lambda: current[0]) is False
    overlay.overlay.setOverlayRaw.assert_not_called()


def test_off_during_retry_wait_cancels_upload(monkeypatch):
    overlay = destination()
    native = overlay.overlay
    native.setOverlayRaw.side_effect = RuntimeError("lost")
    monkeypatch.setattr(module.time, "sleep", lambda _: overlay.shutdownOverlay())
    assert overlay.updateImage(Image.new("RGBA", (2, 2)), "large") is False
    native.setOverlayRaw.assert_called_once()
    assert overlay.start_cancelled


def test_guarded_retry_accepts_only_once(monkeypatch):
    overlay = destination()
    overlay.overlay.setOverlayRaw.side_effect = [RuntimeError("lost"), None]
    def reconnect(*, current):
        assert current()
        return True
    monkeypatch.setattr(overlay, "reStartOverlay", reconnect)
    assert overlay.updateImage(Image.new("RGBA", (2, 2)), "large") is True
    assert overlay.overlay.setOverlayRaw.call_count == 2


def model_destination(monkeypatch):
    backend = object.__new__(Model)
    backend.ensure_initialized = lambda: None
    backend.overlay = destination()
    backend.overlay_image = OverlayImage()
    backend.overlay_image.createTextboxLargeLog = lambda *a, **kw: Image.new("RGBA", (40, 20))
    cfg = SimpleNamespace(OVERLAY_LARGE_LOG=True, OVERLAY_SMALL_LOG=True, OVERLAY_VR_PANEL=True)
    monkeypatch.setattr(model_module, "config", cfg)
    monkeypatch.setattr(controller_module, "config", cfg)
    return backend, cfg


@pytest.mark.parametrize("realtime", [False, True])
@pytest.mark.parametrize("success", [False, True])
def test_history_commits_only_on_explicit_publication_success(monkeypatch, realtime, success):
    backend, cfg = model_destination(monkeypatch)
    backend.overlay.updateImage = Mock(return_value=success)
    if realtime:
        backend.publishRealtimeCaptionOverlay(dict(source="mic", namespace="n", item_id="i", revision=1,
            state="final", text="message", translations=[]), "English", {}, lambda: True)
    else:
        backend.publishMessageOverlayLargeLog("send", "message", "English", [], current=lambda: True)
    assert bool(backend.overlay_image.message_log) is success


def test_realtime_cleanup_retains_history_without_upload_when_disabled(monkeypatch):
    backend, cfg = model_destination(monkeypatch)
    backend.publishMessageOverlayLargeLog("send", "history", "English", [], current=lambda: True)
    backend.overlay.overlay.reset_mock()
    cfg.OVERLAY_LARGE_LOG = False
    backend.clearRealtimeCaptionOverlay("mic", "n")
    backend.overlay.overlay.setOverlayRaw.assert_not_called()
    assert [row["message"] for row in backend.overlay_image.message_log] == ["history"]


@pytest.mark.parametrize("size", ["small", "large"])
def test_off_against_outstanding_delivery_finishes_cleared(monkeypatch, size):
    backend, cfg = model_destination(monkeypatch)
    monkeypatch.setattr(controller_module, "model", backend)
    monkeypatch.setattr(Controller, "syncOverlayRunning", lambda: True)
    started, release, clearing = Event(), Event(), Event()
    sizes, result = [], []
    def native(handle, raw, width, height, channels):
        if width > 1:
            started.set()
            assert release.wait(2)
        sizes.append((width, height))
    backend.overlay.overlay.setOverlayRaw.side_effect = native
    original = backend.overlay.clearImage
    def clear(which):
        assert not getattr(cfg, "OVERLAY_" + size.upper() + "_LOG")
        clearing.set()
        original(which)
    backend.overlay.clearImage = clear
    publish = backend.updateOverlaySmallLog if size == "small" else backend.updateOverlayLargeLog
    disable = Controller.setDisableOverlaySmallLog if size == "small" else Controller.setDisableOverlayLargeLog
    worker = Thread(target=lambda: result.append(publish(Image.new("RGBA", (2, 2)))))
    off = Thread(target=disable)
    try:
        worker.start()
        assert started.wait(2)
        off.start()
        assert clearing.wait(2)
    finally:
        release.set()
        worker.join(2)
        if off.ident is not None:
            off.join(2)
    assert not worker.is_alive() and not off.is_alive()
    assert sizes == [(2, 2), (1, 1)] and result == [False]


@pytest.mark.parametrize("size", ["small", "large"])
def test_sample_off_during_render_does_not_upload(monkeypatch, size):
    backend, cfg = model_destination(monkeypatch)
    cfg.OVERLAY_SMALL_LOG = size == "small"
    cfg.OVERLAY_LARGE_LOG = size == "large"
    monkeypatch.setattr(controller_module, "model", backend)
    def render(data):
        cfg.OVERLAY_SMALL_LOG = cfg.OVERLAY_LARGE_LOG = False
        return Image.new("RGBA", (2, 2))
    backend.createOverlayImageSmallMessage = render
    backend.createOverlayImageLargeMessage = render
    Controller.sendTextOverlay("sample")
    backend.overlay.overlay.setOverlayRaw.assert_not_called()


def test_hung_capture_slot_survives_toggle_and_discards_stale_result(monkeypatch):
    overlay = Overlay({PANEL: settings()})
    overlay.gl = {}
    overlay.vr_resources_tried = True
    overlay.panel_hwnd = 123
    jobs = []
    monkeypatch.setattr(overlay, "panelStream", lambda: None)
    monkeypatch.setattr(overlay, "startCaptureJob", jobs.append)
    module.window_capture.resizeClient.side_effect = lambda hwnd, w, h: (w, h)
    overlay.startCapture(100)
    job = jobs[0]
    for i in range(3):
        overlay.setVrPanelEnabled(False)
        overlay.setVrPanelEnabled(True)
        overlay.applyVrPanelEnabled()
        assert overlay.collectCapture(104 + i) is None
        overlay.startCapture(104 + i)
        assert overlay.capture_job is job
    assert len(jobs) == 1 and job.reported
    job.done, job.result = True, (b"stale", None, (0, 0, 2, 2))
    assert overlay.collectCapture(110) is None
    overlay.startCapture(111)
    assert len(jobs) == 2 and jobs[1].generation != job.generation


@pytest.mark.parametrize("stage", ["convert", "upload", "transfer", "layout"])
def test_identical_atlas_retries_after_failure(monkeypatch, stage):
    overlay = Overlay({PANEL: settings()})
    overlay.overlay = Mock()
    overlay.handle = {PANEL: 10}
    overlay.gl = {"GL": Mock(), "texture": 1, "vr_texture": object(), "size": (4, 4)}
    overlay.window_size = (2, 2)
    overlay.layout_rendered = overlay.layout["regions"][PANEL][2:]
    pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    capture = (b"unchanged", None, (0, 0, 2, 2))
    module.window_capture.bgraFromCapture.return_value = pixels
    monkeypatch.setattr(module, "atlasMaskArray", lambda *args: np.ones((2, 2), dtype=np.uint8))
    monkeypatch.setattr(overlay, "collectCapture", lambda now: capture)
    monkeypatch.setattr(overlay, "prepareGl", lambda: overlay.gl["GL"])
    monkeypatch.setattr(overlay, "applyLayout", Mock())
    target = {"convert": module.window_capture.bgraFromCapture, "upload": overlay.gl["GL"].glTexSubImage2D,
              "transfer": overlay.overlay.setOverlayTexture, "layout": overlay.applyLayout}[stage]
    target.side_effect = [RuntimeError(stage), pixels if stage == "convert" else None]
    with pytest.raises(RuntimeError):
        overlay.updatePanel()
    overlay.onPanelError(RuntimeError(stage))
    assert overlay.panel_last_raw is None and overlay.panel_errors == 1
    overlay.updatePanel()
    assert target.call_count == 2 and overlay.panel_last_raw == b"unchanged"
    assert overlay.panel_errors == 0


def test_repeated_transfer_failure_reaches_error_threshold(monkeypatch):
    overlay = Overlay({})
    overlay.failure_callback = Mock()
    monkeypatch.setattr(module, "_PANEL_ERROR_LIMIT", 2)
    overlay.onPanelError(RuntimeError("transfer"))
    overlay.onPanelError(RuntimeError("transfer"))
    assert overlay.panel_stopped and overlay.panel_errors == 2
    overlay.failure_callback.assert_called_once_with("capture")


def test_reconnects_stop_each_watcher_and_off_cancels_pending_reconnect(monkeypatch):
    overlay = Overlay({})
    watchers = []
    class Watcher:
        def __init__(self, target, args, daemon):
            assert all(w.stop.is_set() for w in watchers)
            self.stop = args[-1]
            self.joined = False
            watchers.append(self)
        def start(self):
            pass
        def join(self, timeout):
            assert self.stop.is_set()
            self.joined = True
    monkeypatch.setattr(module, "Thread", Watcher)
    monkeypatch.setattr(overlay, "checkSteamvrRunning", lambda: True)
    monkeypatch.setattr(overlay, "checkActive", lambda: False)
    monkeypatch.setattr(overlay, "init", lambda: setattr(overlay, "initialized", True))
    def wait(seconds):
        if seconds and len(watchers) == 3:
            overlay.shutdownOverlay()
        return overlay.start_cancelled
    monkeypatch.setattr(overlay, "waitUnlessCancelled", wait)
    overlay.main()
    assert len(watchers) == 3 and all(w.joined and w.stop.is_set() for w in watchers)
    assert overlay.start_cancelled and not overlay.initialized


def test_scaling_200_to_50_applies_meters(monkeypatch):
    backend, cfg = model_destination(monkeypatch)
    backend.overlay.settings["large"]["ui_scaling"] = 0.5
    cfg.OVERLAY_LARGE_LOG_SETTINGS = {**settings(), "ui_scaling": 0.5}
    backend.updateOverlayLargeLogSettings()
    assert backend.overlay.settings["large"]["ui_scaling"] == 0.125
    backend.overlay.overlay.setOverlayWidthInMeters.assert_called_once_with(2, 0.125)


def test_opacity_change_keeps_fresh_text_visible(monkeypatch):
    overlay = destination()
    overlay.fadeRatio["small"] = 0.0
    monkeypatch.setattr(module.time, "monotonic", lambda: 100)
    assert overlay.updateImage(Image.new("RGBA", (2, 2)), "small")
    assert overlay.fadeRatio["small"] == 1.0
    overlay.updateOpacity(0.5, "small", True)
    overlay.update("small")
    overlay.overlay.setOverlayAlpha.assert_called_with(1, 0.5)
    assert overlay.isVisible("small")


def test_runtime_failure_notifies_ui_and_clears_switches(monkeypatch):
    backend, cfg = model_destination(monkeypatch)
    backend.setVrPanelEnabled = Mock()
    controller = object.__new__(Controller)
    controller._model = backend
    controller.run_mapping = {}
    controller.run = Mock()
    controller._onOverlayFailure("runtime")
    assert not any((cfg.OVERLAY_SMALL_LOG, cfg.OVERLAY_LARGE_LOG, cfg.OVERLAY_VR_PANEL))
    status, endpoint, result = controller.run.call_args.args
    assert status == 400 and endpoint == "/run/message_output_error"
    assert result["error_code"] == "OVERLAY_RUNTIME_FAILED"


def test_enable_does_not_report_success_for_failed_start(monkeypatch):
    backend, cfg = model_destination(monkeypatch)
    cfg.OVERLAY_SMALL_LOG = False
    monkeypatch.setattr(Controller, "syncOverlayRunning", lambda: False)
    response = Controller.setEnableOverlaySmallLog()
    assert response["status"] == 400 and response["result"]["data"] is False
    assert not cfg.OVERLAY_SMALL_LOG


def test_destroy_failure_does_not_skip_other_handles_or_release_twice():
    overlay = destination()
    native = overlay.overlay
    overlay.system = object()
    overlay.owned_handles = [1, 2, 3]
    native.destroyOverlay.side_effect = [RuntimeError("destroy"), None, None]
    overlay.teardown()
    overlay.teardown()
    assert [call.args[0] for call in native.destroyOverlay.call_args_list] == [1, 2, 3]
    module.openvr_session.release.assert_called_once()


def test_failed_clear_stops_owner_without_reconnecting():
    overlay = destination()
    overlay.failure_callback = Mock()
    overlay.overlay.setOverlayRaw.side_effect = RuntimeError("clear")
    overlay.clearImage("large")
    assert overlay.start_cancelled and not overlay.initialized and overlay.run_stop.is_set()
    overlay.failure_callback.assert_called_once_with("runtime")
    assert not overlay.reconnect_requested


def test_other_thread_cannot_publish_while_owner_is_constructing():
    overlay = destination()
    overlay.initialized = False
    overlay._constructing = True
    overlay.owner_thread_id = get_ident() + 1
    assert overlay.updateImage(Image.new("RGBA", (2, 2)), "small") is False
    overlay.overlay.setOverlayRaw.assert_not_called()


def test_revocation_during_alpha_is_not_a_successful_publication():
    overlay = destination()
    current = [True]
    overlay.overlay.setOverlayAlpha.side_effect = lambda *args: current.__setitem__(0, False)
    assert overlay.updateImage(Image.new("RGBA", (2, 2)), "small", current=lambda: current[0]) is False


def test_shutdown_releases_gl_on_creating_thread_not_caller(monkeypatch):
    overlay = Overlay({})
    glfw, gl, native = Mock(), Mock(), Mock()
    glfw.init.return_value = True
    glfw.create_window.return_value = "window"
    gl.glGenTextures.side_effect = [11, 12]
    native.createOverlay.return_value = 1
    ready, released = Event(), []
    owner_ids = []
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(__import__('sys').modules, "glfw", glfw)
    monkeypatch.setitem(__import__('sys').modules, "OpenGL", SimpleNamespace(GL=gl))
    monkeypatch.setattr(overlay, "checkSteamvrRunning", lambda: True)
    native.destroyOverlay.side_effect = lambda handle: released.append(("overlay", get_ident()))
    module.openvr_session.release.side_effect = lambda: released.append(("session", get_ident()))
    gl.glDeleteTextures.side_effect = lambda values: released.append(("textures", get_ident()))
    glfw.destroy_window.side_effect = lambda window: released.append(("window", get_ident()))
    glfw.terminate.side_effect = lambda: released.append(("glfw", get_ident()))

    def init():
        owner_ids.append(get_ident())
        overlay.system, overlay.overlay = object(), native
        overlay.createOverlay("key", "name")
        overlay.initPanelTexture()
        overlay.initialized = True

    def loop():
        overlay.loop = True
        ready.set()
        assert overlay.run_stop.wait(2)

    monkeypatch.setattr(overlay, "init", init)
    monkeypatch.setattr(overlay, "mainloop", loop)
    try:
        assert overlay.startOverlay()
        assert ready.wait(2)
    finally:
        overlay.shutdownOverlay()
    assert owner_ids[0] != get_ident()
    assert released == [(kind, owner_ids[0]) for kind in ("overlay", "session", "textures", "window", "glfw")]
    assert overlay.thread_overlay is None and not overlay.initialized


def test_failed_texture_reallocation_does_not_register_old_texture_twice():
    overlay = Overlay({})
    gl, glfw = Mock(), Mock()
    overlay.gl = {"GL": gl, "glfw": glfw, "window": "window", "texture": 11,
                  "ghost_texture": 12, "size": (2, 2), "old_textures": []}
    gl.glGenTextures.side_effect = RuntimeError("allocate")
    with pytest.raises(RuntimeError):
        overlay.newPanelTexture(gl, (4, 4))
    overlay.teardown()
    gl.glDeleteTextures.assert_called_once_with([11, 12])
