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


def initial_state(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.json").write_text(json.dumps({
        "AUTO_DOWNLOAD_MODELS": False, "ENABLE_TELEMETRY": False,
        "AUTO_MIC_SELECT": False, "AUTO_SPEAKER_SELECT": False,
        "SEND_MESSAGE_TO_VRC": False, "VRC_MIC_MUTE_SYNC": False,
        "OSC_IP_ADDRESS": "127.0.0.2", "WEBSOCKET_SERVER": False,
        "UI_LANGUAGE": "en",
    }))
    return state


def test_model_free_native_app_renders_text_input_without_fatal_warning(tmp_path):
    state = initial_state(tmp_path)
    with NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state)}) as ui:
        ui.wait("return document.querySelector('textarea') !== null")
        assert "An error occurred" not in ui.evaluate("return document.body.innerText")
        assert "download automatically, normally" not in ui.evaluate("return document.body.innerText")
        # DPMS Off reproduced the old black window while the DOM still worked.
        ui.assert_rendered()
        ui.close_app()


def test_native_voice_settings_survive_restart_with_managed_route_muted(tmp_path):
    from tools.voice_acceptance import private_graph, wait_for
    from models.audio_routing.pipewire_gate import PipeWireGate
    from native_webdriver import ROOT

    state = initial_state(tmp_path)
    with private_graph(config_fragment=ROOT / "config/pipewire/90-vrct-managed.conf"):
        gate = PipeWireGate()
        with NativeWebDriver(tmp_path / "first", {"VRCT_CONFIG_DIR": str(state)}) as ui:
            ui.wait("return document.querySelector('textarea') !== null")
            ui.open_voice_settings()
            ui.select("Audio route", "managed")
            ui.select("Read aloud", "original")
            ui.select("Translation slot", "2")
            ui.fill("Japanese voice name", "保存テスト")
            ui.click_text("button", "Save voice settings")
            wait_for(lambda: json.loads((state / "config.json").read_text()).get("VOICE_SETTINGS", {}).get("japanese_voice") == "保存テスト")
            ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Muted (confirmed)')")
            assert gate.inspect()["muted"] is True
            ui.click_text("button", "Resume voice")
            wait_for(lambda: gate.inspect()["muted"] is False)
            ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Voice enabled (confirmed)')")
            ui.assert_rendered()
            ui.close_app()
        assert gate.inspect()["muted"] is True
        with NativeWebDriver(tmp_path / "second", {"VRCT_CONFIG_DIR": str(state)}) as ui:
            ui.wait("return document.querySelector('textarea') !== null")
            ui.open_voice_settings()
            for label, value in [("Read aloud", "original"), ("Audio route", "managed"),
                                 ("Translation slot", "2"), ("Japanese voice name", "保存テスト")]:
                assert ui.evaluate("return arguments[0].value", ui.control(label)) == value
            ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Muted (confirmed)')")
            assert gate.inspect()["muted"] is True
            ui.assert_rendered()
            ui.close_app()
