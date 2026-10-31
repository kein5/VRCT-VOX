"""Production components/hooks/IPC with an offline sidecar peer and headless browser."""

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
from models.speech_server.settings import normalize_settings
from models.model_downloads.manager import Downloads

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_MODEL_DOWNLOAD_UI") != "1", reason="opt-in browser test"
)


@pytest.fixture
def ui(tmp_path):
    from playwright.sync_api import sync_playwright

    with ExitStack() as stack:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = stack.enter_context((tmp_path / "vite.log").open("w"))
        vite = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js", ".",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=ROOT,
            stdout=log,
            stderr=log,
        )

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
            executable_path=os.environ["VRCT_TEST_CHROMIUM"], headless=True
        )
        stack.callback(browser.close)
        page = browser.new_page(viewport={"width": 1200, "height": 1600})
        page.set_default_timeout(5000)
        peer = SimpleNamespace(
            sent=[],
            replies=[],
            errors=[],
            sequence=0,
            jobs={},
            settings=normalize_settings({}),
            state={
                name: dict(state="stopped", generation=0, error_code=None)
                for name in ("japanese", "multilingual", "asr")
            },
        )
        catalog = Downloads(tmp_path / "models").catalog()
        peer.catalog = catalog
        peer.hardware = dict(
            phase="ready",
            measured_at_ms=int(time.time() * 1000),
            error_code=None,
            devices=[
                dict(
                    name="Vulkan0",
                    description="NVIDIA GeForce RTX 4080 SUPER",
                    kind="gpu",
                    memory_total=16 * 1024**3,
                    memory_free=10 * 1024**3,
                )
            ],
        )
        page.on("pageerror", lambda error: peer.errors.append(str(error)))

        def reply(endpoint, result, status=200):
            peer.replies.append(dict(endpoint=endpoint, result=result, status=status))

        def state():
            peer.sequence += 1
            return dict(
                observation_id=str(peer.sequence), jobs=copy.deepcopy(peer.jobs)
            )

        def write(line):
            req = json.loads(line)
            ep = req["endpoint"]
            data = (
                json.loads(base64.b64decode(req["data"])) if req.get("data") else None
            )
            peer.sent.append((ep, data))
            if getattr(peer, "extra", None) and peer.extra(ep, data):
                return
            if ep == "/get/data/model_download_catalog":
                reply(ep, catalog)
            elif ep in (
                "/get/data/model_download_hardware",
                "/run/refresh_model_download_hardware",
            ):
                peer.sequence += 1
                reply(ep, dict(peer.hardware, observation_id=str(peer.sequence)))
            elif ep == "/get/data/model_download_state":
                reply(ep, state())
            elif ep == "/run/start_model_download":
                assert data["consent"] is True
                entry = next(m for m in catalog["models"] if m["id"] == data["id"])
                peer.jobs[data["id"]] = dict(
                    job_id="job1",
                    phase="downloading",
                    received_bytes=12,
                    total_bytes=entry["total_bytes"],
                    paths={},
                    error_code=None,
                )
                reply(ep, state())
            elif ep == "/run/cancel_model_download":
                peer.jobs[data["id"]]["phase"] = "cancelled"
                reply(ep, state())
            elif ep == "/run/apply_model_download":
                job = peer.jobs[data["id"]]
                peer.settings["profiles"]["japanese"]["model"] = job["paths"]["model"]
                job["phase"] = "applied"
                reply(ep, state())
            elif ep == "/get/data/speech_server_settings":
                reply(ep, peer.settings)
            elif ep == "/get/data/speech_server_state":
                reply(ep, peer.state)
            elif ep == "/set/data/speech_server_settings":
                peer.settings = data
                reply(ep, peer.settings)

        def read():
            result, peer.replies = peer.replies, []
            return result

        page.expose_function("sidecarWrite", write)
        page.expose_function("sidecarRead", read)
        page.goto(f"http://127.0.0.1:{port}/tests/voice/model-download-ui-entry/")
        yield page, peer, reply, state
        assert not peer.errors


def test_warning_consent_progress_cancel_and_no_activation(ui):
    from playwright.sync_api import expect

    page, peer, _, _ = ui
    page.get_by_role("button", name="Review download", exact=True).first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Aratako / sakasegawa")
    expect(dialog).to_contain_text("1,920,321,792")
    expect(dialog).to_contain_text("MIT + Apache-2.0")
    start = dialog.get_by_role("button", name="Agree and download", exact=True)
    expect(start).to_be_disabled()
    assert not any("start_model_download" in ep for ep, _ in peer.sent)
    dialog.get_by_role("checkbox").check()
    start.click()
    expect(page.get_by_role("progressbar")).to_be_visible()
    page.get_by_role("button", name="Cancel download", exact=True).click()
    expect(page.get_by_text("Download cancelled.", exact=True)).to_be_visible()
    assert not any(
        ep in ("/run/start_speech_server", "/run/start_direct_voice", "/run/enable_tts")
        for ep, _ in peer.sent
    )


def test_apply_requires_verified_completion_and_clean_draft(ui):
    from playwright.sync_api import expect

    page, peer, reply, state = ui
    page.get_by_role("button", name="Review download", exact=True).first.click()
    page.get_by_role("dialog").get_by_role("checkbox").check()
    page.get_by_role("button", name="Agree and download", exact=True).click()
    page.get_by_role("progressbar").wait_for()
    peer.jobs["irodori-v41-f16"].update(
        phase="ready", paths={"model": "/verified/model.gguf"}
    )
    reply("/get/data/model_download_state", state())
    apply = page.get_by_role("button", name="Apply model path", exact=True)
    expect(apply).to_be_enabled()
    field = page.get_by_label("Model GGUF path", exact=True)
    field.fill("/unsaved.gguf")
    expect(apply).to_be_disabled()
    expect(
        page.get_by_text("A path that this download replaces has unsaved edits.", exact=False)
    ).to_be_visible()
    page.get_by_role("button", name="Discard changes", exact=True).click()
    expect(apply).to_be_enabled()
    apply.click()
    expect(field).to_have_value("/verified/model.gguf")
    assert next(data for ep, data in peer.sent if ep == "/run/apply_model_download")[
        "expected"
    ] == {"model": ""}
    assert not any(ep == "/run/start_speech_server" for ep, _ in peer.sent)


def _download_ready(page, peer, reply, state):
    page.get_by_role("button", name="Review download", exact=True).first.click()
    page.get_by_role("dialog").get_by_role("checkbox").check()
    page.get_by_role("button", name="Agree and download", exact=True).click()
    page.get_by_role("progressbar").wait_for()
    peer.jobs["irodori-v41-f16"].update(
        phase="ready", paths={"model": "/verified/model.gguf"}
    )
    reply("/get/data/model_download_state", state())


def test_apply_right_after_download_keeps_other_unsaved_edits(ui):
    from playwright.sync_api import expect

    # Regression: a voice file or device chosen before downloading used to
    # disable Apply until the whole form was saved.
    page, peer, reply, state = ui
    voice = page.get_by_label("Voice GGUF path (optional)", exact=True)
    voice.fill("/unsaved-voice.gguf")
    page.get_by_label("Inference device", exact=True).select_option("gpu")
    _download_ready(page, peer, reply, state)
    apply = page.get_by_role("button", name="Apply model path", exact=True)
    expect(apply).to_be_enabled()
    apply.click()
    expect(page.get_by_label("Model GGUF path", exact=True)).to_have_value(
        "/verified/model.gguf"
    )
    expect(voice).to_have_value("/unsaved-voice.gguf")
    expect(page.get_by_label("Inference device", exact=True)).to_have_value("gpu")
    expect(page.get_by_text("Unsaved changes", exact=True)).to_be_visible()
    # Apply persisted only the model path; the other edits are still a draft.
    saved = peer.settings["profiles"]["japanese"]
    assert (saved["model"], saved["voice_file"], saved["device"]) == (
        "/verified/model.gguf", "", "auto"
    )
    assert not any(ep == "/set/data/speech_server_settings" for ep, _ in peer.sent)
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_text("Unsaved changes", exact=True)).to_have_count(0)
    saved = peer.settings["profiles"]["japanese"]
    assert (saved["model"], saved["voice_file"], saved["device"]) == (
        "/verified/model.gguf", "/unsaved-voice.gguf", "gpu"
    )
    assert not any(ep == "/run/start_speech_server" for ep, _ in peer.sent)


def test_apply_stays_blocked_while_the_target_server_runs(ui):
    from playwright.sync_api import expect

    page, peer, reply, state = ui
    _download_ready(page, peer, reply, state)
    peer.state["japanese"] = dict(state="preparing", generation=1, error_code=None)
    reply("/get/data/speech_server_state", peer.state)
    expect(
        page.get_by_role("button", name="Apply model path", exact=True)
    ).to_be_disabled()
    expect(
        page.get_by_text("Stop the target server or input before applying.", exact=False)
    ).to_be_visible()


def test_failure_stale_reply_and_rvc_requirements(ui):
    from playwright.sync_api import expect

    page, peer, reply, state = ui
    expect(page.get_by_text("HuBERT", exact=False).first).to_be_visible()
    expect(page.get_by_text("RMVPE", exact=False).first).to_be_visible()
    page.get_by_role("button", name="Review download", exact=True).first.click()
    page.get_by_role("dialog").get_by_role("checkbox").check()
    page.get_by_role("button", name="Agree and download", exact=True).click()
    page.get_by_role("progressbar").wait_for()
    stale = state()
    peer.jobs["irodori-v41-f16"].update(phase="failed", error_code="hash_mismatch")
    reply("/get/data/model_download_state", state())
    expect(
        page.get_by_text(
            "File verification failed. Settings were not changed.", exact=True
        )
    ).to_be_visible()
    reply("/get/data/model_download_state", stale)
    expect(
        page.get_by_role("button", name="Apply model path", exact=True)
    ).to_have_count(0)


def test_model_links_use_tauri_opener_and_report_failure(ui):
    from playwright.sync_api import expect

    page, _, _, _ = ui
    page.get_by_role("button", name="Review download", exact=True).first.click()
    page.evaluate("""() => {
        window.isTauri = true; window.openedModels = [];
        window.__TAURI_INTERNALS__ = { invoke: async (command, args) => {
            window.openedModels.push({ command, args }); throw new Error('opener denied');
        }};
    }""")
    page.get_by_role("dialog").get_by_role(
        "link", name="Model card and usage terms"
    ).click()
    expect(
        page.get_by_text(
            "Could not open the link in your browser. Copy the displayed URL to open it manually.",
            exact=True,
        )
    ).to_be_visible()
    calls = page.evaluate("window.openedModels")
    assert len(calls) == 1 and calls[0]["command"] == "plugin:opener|open_url"
    assert calls[0]["args"]["url"].startswith("https://huggingface.co/sakasegawa/")


def test_external_saved_path_refresh_preserves_unsaved_edits(ui):
    from playwright.sync_api import expect

    page, peer, reply, _ = ui
    field = page.get_by_label("Model GGUF path", exact=True)
    field.fill("/unsaved.gguf")
    peer.settings["profiles"]["japanese"]["model"] = "/externally-saved.gguf"
    reply("/get/data/speech_server_settings", peer.settings)
    expect(field).to_have_value("/unsaved.gguf")
    page.get_by_role("button", name="Discard changes", exact=True).click()
    expect(field).to_have_value("/externally-saved.gguf")


def test_consent_is_bound_to_the_catalog_shown_in_the_dialog(ui, tmp_path):
    from playwright.sync_api import expect

    page, peer, reply, _ = ui
    page.get_by_role("button", name="Review download", exact=True).first.click()
    catalog = peer.catalog
    approved_version = catalog["catalog_version"]
    catalog["catalog_version"] = "new-unreviewed-catalog"
    catalog["models"][0]["name"] = "Unreviewed replacement model"
    reply("/get/data/model_download_catalog", catalog)
    expect(page.get_by_text("Unreviewed replacement model", exact=True)).to_have_count(
        1
    )
    page.get_by_role("dialog").get_by_role("checkbox").check()
    page.get_by_role("button", name="Agree and download", exact=True).click()
    page.get_by_role("progressbar").wait_for()
    sent = next(data for ep, data in peer.sent if ep == "/run/start_model_download")
    assert sent["catalog_version"] == approved_version


def test_idle_render_does_not_repeat_catalog_requests(ui):
    from playwright.sync_api import expect

    page, peer, _, _ = ui
    expect(
        page.get_by_role("button", name="Review download", exact=True)
    ).to_have_count(2)
    # Both mounted components ask once. State replies must not cause a fetch loop.
    page.wait_for_timeout(250)
    initial = sum(ep == "/get/data/model_download_catalog" for ep, _ in peer.sent)
    page.wait_for_timeout(250)
    assert (
        sum(ep == "/get/data/model_download_catalog" for ep, _ in peer.sent) == initial
    )


def test_gpu_guidance_selects_compact_model_and_keeps_active_job_visible(ui):
    from playwright.sync_api import expect

    page, peer, reply, _ = ui
    variant = page.get_by_label("Model variant", exact=True)
    expect(variant).to_have_value("irodori-v41-f16")
    peer.hardware["devices"][0]["memory_free"] = 4500000000
    page.get_by_role("button", name="Refresh GPU and memory", exact=True).first.click()
    expect(variant).to_have_value("irodori-v41-q8")
    expect(
        page.get_by_text("Recommended for available memory", exact=True)
    ).to_be_visible()
    variant.select_option("irodori-v41-q8")
    page.get_by_role("button", name="Review download", exact=True).first.click()
    page.get_by_role("dialog").get_by_role("checkbox").check()
    page.get_by_role("button", name="Agree and download", exact=True).click()
    page.get_by_role("progressbar").wait_for()
    assert (
        next(data for ep, data in peer.sent if ep == "/run/start_model_download")["id"]
        == "irodori-v41-q8"
    )
    variant.select_option("irodori-v41-f16")
    expect(page.get_by_role("progressbar")).to_be_visible()
    page.get_by_role("button", name="Cancel download", exact=True).click()
    assert peer.jobs["irodori-v41-q8"]["phase"] == "cancelled"
    assert not any(ep == "/run/start_speech_server" for ep, _ in peer.sent)


def test_failed_hardware_probe_does_not_invent_capacity_or_disable_manual_choice(ui):
    from playwright.sync_api import expect

    page, peer, reply, _ = ui
    variant = page.get_by_label("Model variant", exact=True)
    expect(variant).to_have_value("irodori-v41-f16")
    peer.hardware.update(phase="failed", devices=[], error_code="hardware_timeout")
    page.get_by_role("button", name="Refresh GPU and memory", exact=True).first.click()
    expect(
        page.get_by_text(
            "GPU information is unavailable. Choose a model manually or refresh.",
            exact=True,
        )
    ).to_be_visible()
    variant.select_option("irodori-v41-q8")
    page.get_by_role("button", name="Review download", exact=True).first.click()
    expect(page.get_by_role("dialog")).to_contain_text("Q8_0")
    assert not any(ep == "/run/start_model_download" for ep, _ in peer.sent)


def test_asr_profile_offers_haas_without_hardware_advice(ui):
    from playwright.sync_api import expect

    page, peer, _, _ = ui
    page.goto(page.url + "?view=asr")
    expect(page.get_by_text("Haas-ja v1.0 · Q8_0", exact=True)).to_be_visible()
    expect(page.get_by_text("Irodori-TTS v4.1 Small MF · F16", exact=True)).to_have_count(0)
    expect(page.get_by_label("Memory headroom", exact=True)).to_have_count(0)
    expect(page.get_by_text("also needs a VAD model", exact=False)).to_be_visible()
    page.get_by_role("button", name="Review download", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Third Intelligence / sakasegawa")
    expect(dialog).to_contain_text("656,381,472")
    expect(dialog).to_contain_text("speech.cpp 0.9.4 or later")
    dialog.get_by_role("checkbox").check()
    dialog.get_by_role("button", name="Agree and download", exact=True).click()
    expect(page.get_by_role("progressbar")).to_be_visible()
    assert next(data for ep, data in peer.sent if ep == "/run/start_model_download")["id"] == "haas-ja-q8"
