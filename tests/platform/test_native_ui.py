"""Opt-in actual Tauri/WebKitGTK -> shell sidecar -> full Model startup."""
import json
import os
import sys
import time

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
        "AUTO_DOWNLOAD_MODELS": False, "ENABLE_TELEMETRY": False, "TELEMETRY_NOTICE": 1,
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
        assert ui.evaluate("return document.title") == "VRCT-VOX"
        assert "VRCT-VOX" in ui.evaluate("return document.body.innerText")
        assert "An error occurred" not in ui.evaluate("return document.body.innerText")
        assert "download automatically, normally" not in ui.evaluate("return document.body.innerText")
        # DPMS Off reproduced the old black window while the DOM still worked.
        ui.assert_rendered()
        ui.close_app()


def x11_window(title):
    """The X11 id and the xwininfo report of the window with this exact title, or None."""
    import re
    import subprocess

    tree = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True, timeout=5).stdout
    match = re.search(r'^\s*(0x[0-9a-f]+) "' + re.escape(title) + '"', tree, re.MULTILINE)
    if match is None:
        return None
    report = subprocess.run(["xwininfo", "-id", match.group(1)], capture_output=True, text=True, timeout=5).stdout
    return match.group(1), report


def test_desktop_captions_are_an_unmanaged_window_above_the_others(tmp_path):
    """Linux on X11/XWayland: the caption window is override-redirect, so a window manager
    neither focuses it nor puts a focused full-screen game above it, and it shows the line
    just sent. Xvfb has no window manager; KWin's stacking is checked by hand."""
    state = initial_state(tmp_path)
    with NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state)}) as ui:
        ui.wait("return document.querySelector('textarea') !== null")
        ui.open_voice_page("VR", '[data-setting-id="desktop_overlay"] input[type=checkbox]')
        assert ui.evaluate("return document.querySelector('[data-setting-id=\"desktop_overlay\"] input').checked") is False
        ui.evaluate("document.querySelector('[data-setting-id=\"desktop_overlay\"] input').click(); return true;")
        ui.wait("return document.querySelector('[data-setting-id=\"desktop_overlay\"] input').checked === true")
        deadline = time.monotonic() + 15
        while (found := x11_window("VRCT-VOX Captions")) is None or "IsViewable" not in found[1]:
            assert time.monotonic() < deadline, "the caption window did not appear"
            time.sleep(.2)
        xid, report = found
        (tmp_path / "caption-window.txt").write_text(report)
        assert "Override Redirect State: yes" in report, report
        ui.close_settings()
        field = ui.command("POST", "/element", {"using": "css selector", "value": "textarea[class*=message_box_input_area]"})
        ui.element_command(field, "clear")
        ui.element_command(field, "value", {"text": "caption overlay check"})
        ui.click('[class*="message_send_button"]')
        ui.wait("return document.querySelector('textarea[class*=message_box_input_area]').value === ''")
        # The overlay page reads its lines from the native side; its own document has the text.
        windows = ui.command("GET", "/window/handles")
        main = ui.command("GET", "/window")
        overlay = next(handle for handle in windows if handle != main)
        ui.command("POST", "/window", {"handle": overlay})
        ui.wait("return document.body.innerText.includes('caption overlay check')")
        ui.command("POST", "/window", {"handle": main})
        ui.close_app()


def test_native_settings_navigation_observes_open_and_close(tmp_path):
    from test_native_realtime import open_captions
    from test_native_spoken_translation import open_voice
    from tools.voice_acceptance import private_graph
    from native_webdriver import ROOT

    state = initial_state(tmp_path)
    with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'):
        with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state)}) as ui:
            ui.wait("return document.querySelector('textarea') !== null")
            for _ in range(20):
                open_voice(ui)
                ui.close_settings()
                ui.wait("return document.querySelector('[class*=show_main]') !== null", timeout=3)
                open_captions(ui)
                ui.close_settings()
                ui.wait("return document.querySelector('[class*=show_main]') !== null", timeout=3)
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
            ui.open_route_settings()
            ui.select("Audio route", "managed")
            ui.click_text("button", "Save changes")
            wait_for(lambda: json.loads((state / "config.json").read_text()).get("VOICE_SETTINGS", {}).get("routing") == "managed")
            ui.open_voice_settings()
            ui.select("Chat voice", "translated")
            ui.select("Translation slot", "2")
            ui.select("Chat voice", "original")
            ui.select("Seed mode", "fixed")
            ui.fill("Instruction", "設定復元の試験")
            ui.fill("Japanese voice name", "保存テスト")
            ui.click_text("button", "Save changes")
            wait_for(lambda: json.loads((state / "config.json").read_text()).get("VOICE_SETTINGS", {}).get("japanese_voice") == "保存テスト")
            ui.open_route_settings()
            ui.wait("return [...document.querySelectorAll('[role=status], [role=status] p')].some(e => e.textContent === 'Muted (confirmed)')")
            assert gate.inspect()["muted"] is True
            ui.click_text("button", "Resume voice")
            wait_for(lambda: gate.inspect()["muted"] is False)
            ui.wait("return [...document.querySelectorAll('[role=status], [role=status] p')].some(e => e.textContent === 'Voice enabled (confirmed)')")
            ui.assert_rendered()
            ui.close_app()
        assert gate.inspect()["muted"] is True
        with NativeWebDriver(tmp_path / "second", {"VRCT_CONFIG_DIR": str(state)}) as ui:
            ui.wait("return document.querySelector('textarea') !== null")
            ui.open_voice_settings()
            for label, value in [("Chat voice", "original"), ("Translation slot", "2"), ("Japanese voice name", "保存テスト"),
                                 ("Seed value", "0"), ("Instruction", "設定復元の試験")]:
                assert ui.evaluate("return arguments[0].value", ui.control(label)) == value
            ui.open_route_settings()
            ui.wait("return [...document.querySelectorAll('[role=status], [role=status] p')].some(e => e.textContent === 'Muted (confirmed)')")
            assert gate.inspect()["muted"] is True
            ui.assert_rendered()
            ui.close_app()
