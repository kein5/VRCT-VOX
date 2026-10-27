"""Opt-in actual Tauri/WebKitGTK -> shell sidecar -> full Model startup."""
import json
import os
import sys

import pytest

from native_webdriver import NativeWebDriver


pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE_GUI") != "1",
    reason="requires built native Tauri, tauri-driver and a graphical session",
)


def test_model_free_native_app_renders_text_input_without_fatal_warning(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.json").write_text(json.dumps({
        "AUTO_DOWNLOAD_MODELS": False, "ENABLE_TELEMETRY": False,
        "AUTO_MIC_SELECT": False, "AUTO_SPEAKER_SELECT": False,
        "SEND_MESSAGE_TO_VRC": False, "VRC_MIC_MUTE_SYNC": False,
        "OSC_IP_ADDRESS": "127.0.0.2", "WEBSOCKET_SERVER": False,
        "UI_LANGUAGE": "en",
    }))
    with NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state)}) as ui:
        ui.wait("return document.querySelector('textarea') !== null")
        assert "An error occurred" not in ui.evaluate("return document.body.innerText")
        assert "download automatically, normally" not in ui.evaluate("return document.body.innerText")
        # A responsive DOM alone did not prove rendering on WebKitGTK/NVIDIA:
        # a black native window was observed while execute/sync still worked.
        ui.evaluate("window.__vrctFrameSeen = false; requestAnimationFrame(() => window.__vrctFrameSeen = true); return true;")
        ui.wait("return window.__vrctFrameSeen === true", timeout=5)
