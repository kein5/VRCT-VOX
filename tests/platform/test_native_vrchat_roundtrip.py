"""Opt-in: a message typed in the app reaches a real VRChat and the app reads it back.

The app sends the message over OSC to one local VRChat client (the speaker). A second client in
the same instance (the camera) sees the speaker's chat bubble, and the app's chat reading reads
that window with the real OCR models. One pass therefore covers the chatbox send, VRChat showing
it, the window capture and the recognition, without touching the PC's audio.

Start the two clients first: python tools/chatbox_lab/launch_clients.py --clients 2
(a hidden local instance; nobody else can join). The lab world moves both avatars every few
seconds, so the bubble is read at changing distances and backgrounds.

The chat bubble detector is not part of the lab's models, so signs and nameplates in view are read
too. The test looks for its own messages among the results and ignores the rest.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

import native_vrchat_lab as lab
from native_webdriver import NativeWebDriver
from test_native_ui import initial_state

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VRCT_TEST_NATIVE_VRCHAT_ROUNDTRIP") != "1",
    reason="opt-in: needs the chatbox lab's two local VRChat clients and the OCR models",
)

MODELS = Path(os.environ.get("VRCT_TEST_OCR_MODELS", Path.home() / ".cache/vrct-vox-chatbox-lab/models"))
# Short and long, both scripts, digits. Each is made unique per run below.
MESSAGES = ["Hello from VRCT-VOX", "こんにちは、テストです", "Linux and Wayland check",
            "今日はいい天気ですね", "これは少し長めの文章で、折り返されるかを確かめます", "last line"]
WAIT = 20


def squeeze(text):
    return "".join(text.split())


def read_rows(ui):
    """Chat reading results on screen. The log keeps only the rows in view, so callers collect while they wait."""
    rows = [row.strip() for row in ui.evaluate("return document.querySelector('#log_container')?.innerText || '';").split("\n") if row.strip()]
    return [rows[i + 1] for i, row in enumerate(rows[:-1]) if row.startswith("Received (Chat reading)")]


def test_typed_message_is_shown_by_vrchat_and_read_back(tmp_path):
    assert lab.ready(), "start the lab clients: python tools/chatbox_lab/launch_clients.py --clients 2"
    assert MODELS.is_dir(), f"OCR models not found: {MODELS}"
    speaker = lab.clients()["speaker"]
    state = initial_state(tmp_path)
    config = json.loads((state / "config.json").read_text())
    config.update(SEND_MESSAGE_TO_VRC=True, OSC_IP_ADDRESS="127.0.0.1", OSC_PORT=speaker["osc_in"])
    (state / "config.json").write_text(json.dumps(config))
    shutil.copytree(MODELS, state / "downloaded_models")
    stamp = time.strftime("%M%S")
    report = {"status": "failed", "real_vrchat": True, "real_ocr": True, "host_audio_changed": False,
              "speaker_osc_port": speaker["osc_in"], "wait_seconds": WAIT, "messages": []}
    try:
        with lab.OnlyCameraNamedVRChat(), NativeWebDriver(tmp_path / "ui", {"VRCT_CONFIG_DIR": str(state)}) as ui:
            ui.wait("return document.querySelector('textarea[class*=message_box_input_area]') !== null")
            ui.set_switch("Chat reading (OCR)")
            for index, base in enumerate(MESSAGES):
                text = f"{base} {stamp}{index}"
                seen = set(read_rows(ui))
                field = ui.command("POST", "/element", {"using": "css selector", "value": "textarea[class*=message_box_input_area]"})
                ui.element_command(field, "clear")
                ui.element_command(field, "value", {"text": text})
                sent = time.monotonic()
                ui.click('[class*="message_send_button"]')
                ui.wait("return document.querySelector('textarea[class*=message_box_input_area]').value === ''")
                heard, read_at = [], None
                while time.monotonic() - sent < WAIT and read_at is None:
                    time.sleep(.3)
                    for row in read_rows(ui):
                        if row not in seen and row not in heard:
                            heard.append(row)
                    if any(squeeze(text) in squeeze(row) for row in heard):
                        read_at = time.monotonic() - sent
                report["messages"].append({"sent": text, "read_after_s": read_at and round(read_at, 1), "results": heard[:8]})
                # VRChat limits how often a chatbox may change; leave the bubble time to be replaced.
                time.sleep(max(0, 4 - (time.monotonic() - sent)))
            ui.set_switch("Chat reading (OCR)", on=False)
            ui.assert_rendered()
            ui.close_app()
        missed = [row["sent"] for row in report["messages"] if row["read_after_s"] is None]
        report["read"] = len(MESSAGES) - len(missed)
        assert not missed, f"not read back within {WAIT}s: {missed}"
        report["status"] = "passed"
    finally:
        (tmp_path / "vrchat-roundtrip-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
