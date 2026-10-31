"""Config → Chat Transcribe in a headless browser with an offline sidecar peer.

Opt-in like the other browser tests: VRCT_TEST_OCR_UI=1 and VRCT_TEST_CHROMIUM=<chromium binary>.
Set VRCT_TEST_OCR_UI_SCREENSHOT=<path.png> to keep a screenshot of the page.
"""

import base64
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from types import SimpleNamespace

import pytest
from models.model_downloads.manager import Downloads

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get("VRCT_TEST_OCR_UI") != "1", reason="opt-in browser test")


@pytest.fixture
def ui(tmp_path):
    from playwright.sync_api import sync_playwright

    with ExitStack() as stack:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = stack.enter_context((tmp_path / "vite.log").open("w"))
        vite = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", ".", "--host", "127.0.0.1",
                                 "--port", str(port), "--strictPort"], cwd=ROOT, stdout=log, stderr=log)

        def stop():
            vite.terminate()
            try:
                vite.wait(5)
            except subprocess.TimeoutExpired:
                vite.kill()
                vite.wait(3)

        stack.callback(stop)
        end = time.monotonic() + 15
        while "Local:" not in (tmp_path / "vite.log").read_text():
            assert vite.poll() is None and time.monotonic() < end
            time.sleep(0.05)
        browser = stack.enter_context(sync_playwright()).chromium.launch(
            executable_path=os.environ["VRCT_TEST_CHROMIUM"], headless=True)
        stack.callback(browser.close)
        page = browser.new_page(viewport={"width": 1000, "height": 2200})
        page.set_default_timeout(5000)
        catalog = Downloads(tmp_path / "models").catalog()
        peer = SimpleNamespace(sent=[], replies=[], errors=[], sequence=0, jobs={}, catalog=catalog,
                               region={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}, chatbox=True,
                               readiness=dict(engine=True, language="auto", language_supported=True,
                                              required_models=["ppocrv6-small"], missing_models=["ppocrv6-small"],
                                              capture="window_not_found", window_title="VRChat"))
        page.on("pageerror", lambda error: peer.errors.append(str(error)))

        def reply(endpoint, result, status=200):
            peer.replies.append(dict(endpoint=endpoint, result=result, status=status))

        def state():
            peer.sequence += 1
            return dict(observation_id=str(peer.sequence), jobs=copy.deepcopy(peer.jobs))

        def write(line):
            req = json.loads(line)
            ep = req["endpoint"]
            data = json.loads(base64.b64decode(req["data"])) if req.get("data") else None
            peer.sent.append((ep, data))
            if ep == "/get/data/model_download_catalog":
                reply(ep, catalog)
            elif ep == "/get/data/model_download_state":
                reply(ep, state())
            elif ep == "/run/start_model_download":
                assert data["consent"] is True
                entry = next(m for m in catalog["models"] if m["id"] == data["id"])
                peer.jobs[data["id"]] = dict(job_id="job1", phase="downloading", received_bytes=12,
                                             total_bytes=entry["total_bytes"], paths={}, error_code=None)
                reply(ep, state())
            elif ep == "/get/data/ocr_readiness":
                reply(ep, copy.deepcopy(peer.readiness))
            elif ep == "/set/data/ocr_capture_region":
                peer.region = data
                reply(ep, data)
            elif ep in ("/set/enable/ocr_chatbox_filter", "/set/disable/ocr_chatbox_filter"):
                peer.chatbox = ep.startswith("/set/enable")
                reply(ep, peer.chatbox)

        def read():
            result, peer.replies = peer.replies, []
            return result

        page.expose_function("sidecarWrite", write)
        page.expose_function("sidecarRead", read)
        for endpoint, value in (("/get/data/ocr_source_language", "auto"),
                                ("/get/data/selectable_ocr_source_languages", ["auto", "Korean"]),
                                ("/get/data/ocr_window_title", "VRChat"),
                                ("/get/data/ocr_capture_region", peer.region),
                                ("/get/data/ocr_chatbox_filter", True),
                                ("/get/data/ocr_poll_interval_ms", 750),
                                ("/get/data/ocr_min_confidence", 0.85),
                                ("/get/data/ocr_bubble_min_text_length", 2)):
            reply(endpoint, value)
        page.goto(f"http://127.0.0.1:{port}/tests/voice/ocr-ui-entry/")
        yield page, peer, reply, state
        screenshot = os.environ.get("VRCT_TEST_OCR_UI_SCREENSHOT")
        if screenshot:
            page.screenshot(path=screenshot, full_page=True)
        assert not peer.errors


def test_readiness_names_what_is_missing_and_download_needs_consent(ui):
    from playwright.sync_api import expect

    page, peer, reply, state = ui
    expect(page.get_by_text("Download the recognition models below", exact=False)).to_be_visible()
    expect(page.get_by_text("PP-OCRv6 small", exact=False)).to_be_visible()
    expect(page.get_by_text("Not downloaded", exact=True)).to_be_visible()
    page.get_by_role("button", name="Review download", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Apache-2.0")
    expect(dialog).to_contain_text("PaddlePaddle/PP-OCRv6_small_det_onnx")
    expect(dialog).to_contain_text("PaddlePaddle/PP-OCRv6_small_rec_onnx")
    expect(dialog).to_contain_text("det.onnx")
    start = dialog.get_by_role("button", name="Agree and download", exact=True)
    expect(start).to_be_disabled()
    assert not any(ep == "/run/start_model_download" for ep, _ in peer.sent)
    dialog.get_by_role("checkbox").check()
    start.click()
    expect(page.get_by_role("progressbar")).to_be_visible()
    assert [d for ep, d in peer.sent if ep == "/run/start_model_download"][0]["id"] == "ppocrv6-small"

    # Verified download: readiness is asked again and the next blocker shows.
    peer.jobs["ppocrv6-small"].update(phase="ready")
    peer.readiness.update(missing_models=[])
    asked = sum(ep == "/get/data/ocr_readiness" for ep, _ in peer.sent)
    reply("/get/data/model_download_state", state())
    expect(page.get_by_text("The 'VRChat' window was not found", exact=False)).to_be_visible()
    assert sum(ep == "/get/data/ocr_readiness" for ep, _ in peer.sent) > asked
    expect(page.get_by_text("Downloaded", exact=True)).to_be_visible()


def test_region_reset_and_chatbox_filter_reach_the_backend(ui):
    from playwright.sync_api import expect

    page, peer, reply, _ = ui
    reply("/get/data/ocr_capture_region", {"x": 0.25, "y": 0.1, "width": 0.5, "height": 0.4})
    reset = page.get_by_role("button", name="Use the whole window", exact=True)
    expect(reset).to_be_enabled()
    area = page.get_by_role("img", name="Reading area within the VRChat window")
    expect(area).to_be_visible()
    reset.click()
    expect(reset).to_be_disabled()
    assert peer.region == {"x": 0, "y": 0, "width": 1, "height": 1}
    page.locator('[data-setting-label="Only read chatbox-style text"] label').click()
    for _ in range(60):  # page.wait_for_timeout keeps Playwright's dispatcher (and the sidecar peer) running
        if peer.chatbox is False:
            break
        page.wait_for_timeout(50)
    assert peer.chatbox is False


def test_readiness_is_not_polled_in_a_loop(ui):
    page, peer, _, _ = ui
    page.get_by_text("PP-OCRv6 small", exact=False).wait_for()
    page.wait_for_timeout(1000)
    asked = sum(ep == "/get/data/ocr_readiness" for ep, _ in peer.sent)
    assert 1 <= asked <= 3, asked
