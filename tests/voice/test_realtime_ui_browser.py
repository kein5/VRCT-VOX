"""Production UI/routes with a fake stdio peer; no capture or real ASR here."""

import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from models.transcription.realtime_settings import normalize_settings

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_REALTIME_UI") != "1", reason="opt-in browser integration"
)


def test_selection_caption_replacement_stop_and_stale_responses(tmp_path):
    from playwright.sync_api import sync_playwright, expect

    with ExitStack() as stack:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = stack.enter_context((tmp_path / "vite.log").open("w"))
        vite = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js",
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

        def close_vite():
            vite.terminate()
            try:
                vite.wait(5)
            except subprocess.TimeoutExpired:
                vite.kill()
                vite.wait(3)

        stack.callback(close_vite)
        deadline = time.monotonic() + 15
        while "Local:" not in (tmp_path / "vite.log").read_text():
            assert vite.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)
        browser = stack.enter_context(sync_playwright()).chromium.launch(
            executable_path=os.environ["VRCT_TEST_CHROMIUM"], headless=True
        )
        stack.callback(browser.close)
        page = browser.new_page(viewport={"width": 1200, "height": 1600})
        stack.callback(lambda: (tmp_path / "page.html").write_text(page.content()))
        page.set_default_timeout(5000)
        replies, requests, errors = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        settings = normalize_settings({})
        ids = {
            source: dict(
                cookie="12", serial=str(2**63 + i), name=source, media_class=media
            )
            for i, (source, media) in enumerate(
                (("mic", "Audio/Source"), ("speaker", "Audio/Sink"))
            )
        }
        state = {
            source: dict(
                source=source,
                namespace=None,
                state="idle",
                generation=0,
                requested=False,
                error_code=None,
            )
            for source in ids
        }

        def reply(endpoint, result, status=200):
            replies.append(
                json.dumps(dict(endpoint=endpoint, status=status, result=result))
            )

        def write(line):
            request = json.loads(line)
            endpoint = request["endpoint"]
            data = (
                json.loads(base64.b64decode(request["data"]))
                if request.get("data")
                else None
            )
            requests.append((endpoint, data))
            if endpoint == "/get/data/realtime_asr_settings":
                reply(endpoint, settings)
            elif endpoint == "/set/data/realtime_asr_settings":
                settings.update(data)
                reply(endpoint, settings)
            elif endpoint == "/get/data/realtime_asr_models":
                reply(
                    endpoint,
                    dict(
                        server=settings["server"], configured_url=settings["base_url"], server_generation=None,
                        base_url=settings["base_url"],
                        models=[
                            dict(
                                id="asr", languages=["ja", "en"], accepts_language=False
                            )
                        ],
                        error_code=None,
                    ),
                )
            elif endpoint == "/get/data/realtime_asr_endpoints":
                source = data["source"]
                reply(
                    endpoint,
                    dict(
                        source=source,
                        endpoints=[
                            dict(endpoint=ids[source], label=source + " fixture")
                        ],
                        error_code=None,
                    ),
                )
            elif endpoint == "/get/data/realtime_asr_state":
                reply(endpoint, state)
            elif endpoint == "/run/start_realtime_asr":
                source = data["source"]
                state[source].update(
                    generation=state[source]["generation"] + 1,
                    namespace=source + "-session",
                    state="ready",
                    requested=True,
                )
                reply(endpoint, state)
            elif endpoint == "/run/stop_realtime_asr":
                state[data["source"]].update(
                    generation=state[data["source"]]["generation"] + 1,
                    state="closed",
                    requested=False,
                )
                reply(endpoint, state)

        def read():
            result = list(replies)
            replies.clear()
            return result

        page.expose_function("sidecarWrite", write)
        page.expose_function("sidecarRead", read)
        page.goto(f"http://127.0.0.1:{port}/tests/voice/realtime-ui-entry/")
        start = page.get_by_role("button", name="Start microphone captions", exact=True)
        expect(start).to_be_disabled()
        page.get_by_role("button", name="Refresh ASR models", exact=True).click()
        page.get_by_label("ASR model", exact=True).select_option("asr")
        mic = page.get_by_label("Microphone input", exact=True)
        value = (
            mic.locator("option").filter(has_text="mic fixture").get_attribute("value")
        )
        mic.select_option(value)
        page.get_by_role("button", name="Save caption settings", exact=True).click()
        expect(start).to_be_enabled()
        assert not any(
            endpoint == "/run/start_realtime_asr" for endpoint, data in requests
        )
        start.click()
        expect(start).to_be_disabled()
        assert next(
            data for endpoint, data in requests if endpoint == "/run/start_realtime_asr"
        ) == {"source": "mic"}
        event = dict(
            source="mic",
            generation=1,
            namespace="mic-session",
            item_id="u",
            revision=1,
            state="partial",
            text="one",
            translations=[],
        )
        for revision, text in ((1, "one"), (2, "two")):
            reply(
                "/run/realtime_caption", {**event, "revision": revision, "text": text}
            )
            page.wait_for_function(
                "text => window.entry.logs.length === 1 && window.entry.logs[0].messages.original.message === text",
                arg=text,
            )
        reply(
            "/run/realtime_caption",
            {**event, "revision": 3, "state": "final", "text": "final"},
        )
        reply(
            "/run/realtime_caption",
            {
                **event,
                "revision": 4,
                "state": "translated",
                "text": "final",
                "translations": [{"message": "訳文"}],
            },
        )
        page.wait_for_function(
            "window.entry.logs.length === 1 && window.entry.logs[0].messages.translations[0]?.message === '訳文'"
        )
        reply("/run/realtime_caption", {**event, "item_id": "pending"})
        page.wait_for_function("window.entry.logs.length === 2")
        old = json.loads(json.dumps(state))
        page.get_by_role("button", name="Stop microphone captions", exact=True).click()
        page.wait_for_function("window.entry.logs.length === 1")
        reply("/get/data/realtime_asr_state", old)
        reply("/run/realtime_caption", {**event, "item_id": "late"})
        reply(
            "/run/transcription_send_mic_message",
            {"original": {"message": "legacy"}, "translations": []},
        )
        page.wait_for_function(
            "window.entry.logs.length === 2 && window.entry.logs[1].messages.original.message === 'legacy'"
        )
        expect(start).to_be_enabled()
        # Saving changed input settings invalidates captions immediately even
        # when an old state poll is delivered before the new backend snapshot.
        start.click()
        expect(start).to_be_disabled()
        event = {
            **event,
            "generation": state["mic"]["generation"],
            "item_id": "settings-pending",
        }
        reply("/run/realtime_caption", event)
        page.wait_for_function("window.entry.logs.length === 3")
        page.get_by_label("Microphone language", exact=True).select_option("en")
        page.get_by_role("button", name="Save caption settings", exact=True).click()
        page.wait_for_function("window.entry.logs.length === 2")
        # The fake peer deliberately keeps returning the stale ready snapshot.
        reply("/get/data/realtime_asr_state", state)
        reply("/run/realtime_caption", {**event, "item_id": "settings-late"})
        page.wait_for_timeout(80)
        assert page.evaluate("window.entry.logs.length") == 2
        ids["mic"] = {**ids["mic"], "serial": str(2**63 + 99)}
        page.get_by_role("button", name="Refresh audio devices", exact=True).click()
        expect(mic.locator("option:checked")).to_contain_text("Disconnected")
        expect(start).to_be_disabled()
        reply("/run/start_realtime_asr", {"error_code": "realtime_stale_start"}, 409)
        expect(
            page.get_by_role("alert").filter(has_text="realtime_stale_start")
        ).to_be_visible()
        page.reload()
        expect(
            start
        ).to_be_disabled()  # saved identity does not silently bind to its replacement
        assert len([r for r in requests if r[0] == "/run/start_realtime_asr"]) == 2
        assert not errors, errors
