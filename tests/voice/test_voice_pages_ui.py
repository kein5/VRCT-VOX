"""Real settings navigation, forms and response hooks; model-free stdio peer."""

import base64
import json
import os
from urllib.parse import urlsplit

import pytest
from models.model_downloads.manager import Downloads
from models.tts.settings import VoiceSettings
from test_speech_servers_ui import ui as ui

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['ui']

pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_SPEECH_UI") != "1", reason="opt-in browser integration"
)


@pytest.fixture
def pages(ui, request, tmp_path):
    page, peer, reply = ui
    original_url = page.url
    page.goto("about:blank")
    peer.sent.clear()
    peer.replies.clear()
    main_only = getattr(request, "param", None) == "main"
    if main_only:
        peer.voice.update(mode="original", output_device="headphones")
    peer.reject_voice = False
    peer.hold_voice = False
    peer.sequence = 0
    peer.tts = dict(tts_enabled=False, tts_generation=0, active=False, queued=0)
    peer.hold_tts = False
    peer.hold_direct = False
    peer.drain_direct = False
    peer.reject_tts = None
    peer.model_options = dict(
        model="test-tts",
        seed=dict(minimum=0, maximum=9007199254740991),
        instructions=True,
    )
    peer.hold_options = False
    peer.direct = dict(
        generation=0,
        requested=False,
        pending=False,
        active=False,
        mode="off",
        error=None,
        settings=dict(
            mode="passthrough",
            engine="seed-vc",
            runtime="",
            reference="",
            rvc_runtime="",
            rvc_model="",
            rvc_index="",
            rvc_pitch=0,
            rvc_index_rate=0,
        ),
    )
    peer.catalog = Downloads(tmp_path / "models").catalog()
    peer.download_jobs = {}
    peer.sources = [
        dict(
            label="Test microphone",
            id=dict(
                cookie="test-cookie",
                serial=15,
                name="physical-source",
                media_class="Audio/Source",
            ),
        )
    ]

    def write(line):
        req = json.loads(line)
        ep = req["endpoint"]
        data = json.loads(base64.b64decode(req["data"])) if req.get("data") else None
        peer.sequence += 1
        observation = str(peer.sequence)
        peer.sent.append((ep, data))
        if ep == "/get/data/voice_status":
            reply(ep, dict(peer.tts, observation_id=observation))
        elif ep in ("/run/enable_tts", "/run/disable_tts"):
            if ep == "/run/enable_tts" and peer.reject_tts:
                reply(ep, dict(error_code=peer.reject_tts), 409)
            elif ep == "/run/disable_tts" or not peer.hold_tts:
                peer.tts.update(
                    tts_enabled=ep == "/run/enable_tts",
                    tts_generation=peer.tts["tts_generation"] + 1,
                )
                reply(ep, dict(peer.tts, observation_id=observation))
        elif ep in ("/run/start_direct_voice", "/run/stop_direct_voice"):
            if ep == "/run/stop_direct_voice" or not peer.hold_direct:
                enabled = ep == "/run/start_direct_voice"
                peer.direct.update(
                    requested=enabled,
                    active=enabled,
                    pending=False,
                    stopping=not enabled and peer.drain_direct,
                    mode=data.get("mode", "passthrough") if enabled else "off",
                    generation=peer.direct["generation"] + 1,
                )
                reply(ep, dict(peer.direct, observation_id=observation))
        elif ep == "/get/data/tts_model_options":
            if not peer.hold_options:
                role = data["role"]
                bundled = peer.voice[role + "_server"] == "bundled"
                reply(
                    ep,
                    dict(
                        role=role,
                        request_id=data.get("request_id"),
                        server=peer.voice[role + "_server"],
                        configured_url=peer.voice[role + "_url"],
                        base_url=peer.state[role]["base_url"]
                        if bundled
                        else peer.voice[role + "_url"],
                        server_generation=peer.state[role]["generation"]
                        if bundled
                        else None,
                        options=peer.model_options,
                        error_code=None,
                    ),
                )
        elif ep == "/get/data/voice_route":
            reply(
                ep,
                dict(
                    observation_id=observation,
                    managed=peer.voice["routing"] == "managed",
                    ready=True,
                    requested_muted=False,
                    observed_muted=False,
                ),
            )
        elif ep == "/get/data/direct_voice_state":
            reply(ep, dict(peer.direct, observation_id=observation))
        elif ep == "/get/data/direct_voice_sources":
            reply(ep, dict(sources=peer.sources, error=None))
        elif ep == "/get/data/voice_output_devices":
            reply(
                ep,
                dict(devices=[dict(id="headphones", label="Headphones")], error=None),
            )
        elif ep == "/set/data/voice_settings":
            if peer.reject_voice:
                reply(ep, dict(error_code="VOICE_SETTINGS_INVALID"), 400)
            elif not peer.hold_voice:
                peer.voice = VoiceSettings.from_dict(data).to_dict()
                reply(ep, peer.voice)
        elif ep == "/set/data/direct_voice_settings":
            peer.direct["settings"] = data
            reply(ep, dict(peer.direct, observation_id=observation))
        elif ep == "/get/data/model_download_catalog":
            reply(ep, peer.catalog)
        elif ep == "/get/data/model_download_state":
            reply(ep, dict(observation_id=observation, jobs=peer.download_jobs))
        elif ep == "/run/apply_model_download":
            job = peer.download_jobs[data["id"]]
            peer.direct["settings"].update(
                rvc_model=job["paths"]["model"], rvc_index=job["paths"]["index"]
            )
            job["phase"] = "applied"
            reply(ep, dict(observation_id=observation, jobs=peer.download_jobs))
        else:
            # Existing speech/ASR fixture handles the other production endpoints.
            peer.sent.pop()
            return False
        return True

    page.expose_function("voiceHandled", write)
    page.add_init_script(
        "window.voiceWrite = async line => { if (!await window.voiceHandled(line)) await window.sidecarWrite(line); };"
    )
    base = urlsplit(original_url)
    page.goto(
        f"{base.scheme}://{base.netloc}/tests/voice/voice-pages-entry/"
        + ("?main=1" if main_only else "")
    )
    yield page, peer, reply


def test_separate_pages_search_and_asr_placement(pages):
    from playwright.sync_api import expect

    page, peer, _ = pages
    expect(page.get_by_role("button", name="TTS", exact=True)).to_be_visible()
    expect(page.get_by_label("Chat voice", exact=True)).to_be_visible()
    expect(page.get_by_role("group", name="ASR + VAD", exact=True)).to_have_count(0)
    page.get_by_role("button", name="RVC", exact=True).click()
    expect(page.get_by_label("Permitted RVC model (.pth)", exact=True)).to_be_visible()
    expect(page.get_by_label("Chat voice", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Advanced", exact=True).click()
    expect(page.get_by_label("Permitted RVC model (.pth)", exact=True)).to_have_count(0)
    expect(page.get_by_label("Chat voice", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Transcription", exact=True).click()
    expect(page.get_by_role("group", name="ASR + VAD", exact=True)).to_be_visible()
    expect(page.get_by_role("group", name="Japanese TTS", exact=True)).to_have_count(0)
    page.get_by_label("Search settings", exact=True).fill("RVC")
    page.get_by_label("Search results", exact=True).get_by_role("button").first.click()
    expect(page.get_by_label("Permitted RVC model (.pth)", exact=True)).to_be_visible()
    assert not any(ep.startswith("/run/start_") for ep, _ in peer.sent)


def test_device_route_is_first_and_setup_status_does_not_enable_resume(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    page.get_by_role("button", name="Device", exact=True).click()
    assert (
        page.locator("main [data-setting-id]").first.get_attribute("data-setting-id")
        == "voice_route"
    )
    peer.voice["routing"] = "managed"
    reply(
        "/get/data/voice_route",
        dict(
            observation_id="100000",
            managed=True,
            preparing=True,
            ready=False,
            pending=True,
            requested_muted=True,
            observed_muted=None,
        ),
    )
    expect(
        page.get_by_text("Preparing the virtual microphone…", exact=True)
    ).to_be_visible()
    expect(page.get_by_role("button", name="Resume voice", exact=True)).to_be_disabled()


def test_rvc_can_prepare_route_without_losing_model_or_output_settings(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    page.get_by_role("button", name="RVC", exact=True).click()
    page.get_by_label("Input to forward", exact=True).select_option(
        label="Test microphone"
    )
    model = page.get_by_label("Permitted RVC model (.pth)", exact=True)
    model.fill("/permitted/model.pth")
    previous = dict(peer.voice)
    page.get_by_role(
        "button", name="Prepare and use virtual microphone", exact=True
    ).click()
    expect(
        page.get_by_role(
            "button", name="Prepare and use virtual microphone", exact=True
        )
    ).to_have_count(0)
    assert peer.voice == dict(previous, routing="managed")
    expect(model).to_have_value("/permitted/model.pth")
    expect(page.get_by_label("Input to forward", exact=True)).not_to_have_value("")
    assert not any(ep == "/run/start_direct_voice" for ep, _ in peer.sent)
    reply(
        "/get/data/voice_route",
        dict(
            observation_id="100001",
            managed=True,
            preparing=False,
            ready=False,
            pending=True,
            requested_muted=True,
            observed_muted=None,
            error="managed_setup_tools_missing",
        ),
    )
    expect(page.get_by_role("alert").filter(has_text="pw-loopback")).to_be_visible()
    expect(page.get_by_role("button", name="Resume voice", exact=True)).to_be_disabled()


def test_rvc_download_applies_without_saving_other_edits_first(pages):
    from playwright.sync_api import expect

    # Regression: an unsaved runtime folder used to disable Apply until saved.
    page, peer, reply = pages
    page.get_by_role("button", name="RVC", exact=True).click()
    runtime = page.get_by_label("RVC runtime folder", exact=True)
    runtime.fill("/unsaved/runtime")
    paths = dict(model="/verified/saisho.pth", index="/verified/saisho.index")
    peer.download_jobs["rvc-saisho"] = dict(
        job_id="job1", phase="ready", received_bytes=1, total_bytes=1,
        paths=paths, error_code=None,
    )
    reply(
        "/get/data/model_download_state",
        dict(observation_id="100000", jobs=peer.download_jobs),
    )
    apply = page.get_by_role("button", name="Apply model path", exact=True)
    expect(apply).to_be_enabled()
    apply.click()
    expect(page.get_by_label("Permitted RVC model (.pth)", exact=True)).to_have_value(
        paths["model"]
    )
    expect(
        page.get_by_label("RVC retrieval index (.index, optional)", exact=True)
    ).to_have_value(paths["index"])
    expect(runtime).to_have_value("/unsaved/runtime")
    expect(page.get_by_text("Unsaved changes", exact=True)).to_be_visible()
    assert next(data for ep, data in peer.sent if ep == "/run/apply_model_download")[
        "expected"
    ] == {"model": "", "index": ""}
    assert peer.direct["settings"]["rvc_runtime"] == ""
    assert not any(ep == "/set/data/direct_voice_settings" for ep, _ in peer.sent)
    assert not any(ep == "/run/start_direct_voice" for ep, _ in peer.sent)


def test_unsaved_changes_require_ack_and_navigation_confirmation(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    mode = page.get_by_label("Chat voice", exact=True)
    mode.select_option("original")
    page.get_by_label("Output device", exact=True).select_option("headphones")
    save = page.get_by_role("button", name="Save voice settings", exact=True)
    peer.reject_voice = True
    save.click()
    expect(
        page.get_by_role("alert").filter(has_text="VOICE_SETTINGS_INVALID")
    ).to_be_visible()
    expect(mode).to_have_value("original")
    page.get_by_role("button", name="RVC", exact=True).click()
    page.get_by_role("button", name="Keep editing", exact=True).click()
    expect(mode).to_be_visible()
    peer.reject_voice = False
    peer.hold_voice = True
    save.click()
    expect(page.get_by_role("button", name="Saving…", exact=True)).to_be_disabled()
    peer.voice = VoiceSettings.from_dict(
        dict(peer.voice, mode="original", output_device="headphones")
    ).to_dict()
    reply("/set/data/voice_settings", peer.voice)
    expect(save).to_be_disabled()
    page.get_by_role("button", name="RVC", exact=True).click()
    expect(page.get_by_label("Permitted RVC model (.pth)", exact=True)).to_be_visible()


def test_input_identity_survives_pages_and_stale_state(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    page.get_by_role("button", name="RVC", exact=True).click()
    source = page.get_by_label("Input to forward", exact=True)
    source.select_option(label="Test microphone")
    identity = source.input_value()
    page.get_by_role("button", name="TTS", exact=True).click()
    page.get_by_role("button", name="RVC", exact=True).click()
    expect(source).to_have_value(identity)
    assert json.loads(identity) == [
        "test-cookie",
        15,
        "physical-source",
        "Audio/Source",
    ]
    peer.direct.update(requested=True, pending=True, mode="converted")
    peer.direct["settings"].update(mode="converted", engine="rvc")
    reply("/get/data/direct_voice_state", dict(peer.direct, observation_id="100000"))
    expect(source).to_be_disabled()
    received = reply(
        "/get/data/direct_voice_state",
        dict(peer.direct, requested=False, pending=False, observation_id="1"),
    )
    page.wait_for_function("id => window.received.includes(id)", arg=received)
    expect(source).to_be_disabled()
    page.get_by_role("button", name="Device", exact=True).click()
    expect(
        page.get_by_role("combobox", name="Audio route", exact=True)
    ).to_be_disabled()


def test_discard_before_closing_restores_mounted_form(pages):
    from playwright.sync_api import expect

    page, peer, _ = pages
    mode = page.get_by_label("Chat voice", exact=True)
    mode.select_option("original")
    # ConfigPage stays mounted when hidden. Exercise its navigation guard without unmounting.
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('vrct:settings-leave', {
        cancelable: true, detail: { proceed: () => { window.didLeave = true; } }
    }))""")
    page.get_by_role("button", name="Discard and leave", exact=True).click()
    page.wait_for_function("window.didLeave === true")
    expect(mode).to_have_value(peer.voice["mode"])
    expect(
        page.get_by_role("button", name="Save voice settings", exact=True)
    ).to_be_disabled()
    page.get_by_role("button", name="RVC", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
