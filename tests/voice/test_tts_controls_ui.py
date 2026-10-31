"""Main toggles use production hooks and stdio; never load models or capture audio."""

import copy
import os
import pytest
from test_voice_pages_ui import pages as pages, ui as ui

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['pages']

pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_SPEECH_UI") != "1", reason="opt-in browser integration"
)


def configure(page, peer, reply):
    from playwright.sync_api import expect

    peer.voice.update(mode="original", output_device="headphones", routing="managed")
    reply("/get/data/voice_settings", peer.voice)
    peer.direct["settings"].update(
        mode="converted",
        engine="rvc",
        rvc_runtime="/allowed/rvc",
        rvc_model="/allowed/voice.pth",
    )
    peer.sequence += 1
    reply(
        "/get/data/direct_voice_state",
        dict(peer.direct, observation_id=str(peer.sequence)),
    )
    page.get_by_role("button", name="RVC", exact=True).click()
    page.get_by_label("Input to forward", exact=True).select_option(
        label="Test microphone"
    )
    expect(page.get_by_role("switch", name="RVC", exact=True)).to_have_attribute(
        "aria-checked", "false"
    )


@pytest.mark.parametrize("pages", ["main"], indirect=True)
def test_first_main_render_can_toggle_without_visiting_settings(pages):
    from playwright.sync_api import expect

    page, peer, _ = pages
    tts = page.get_by_role("switch", name="TTS", exact=True)
    expect(tts).to_have_attribute("aria-checked", "false")
    expect(tts).to_have_attribute("aria-disabled", "false")
    tts.focus()
    tts.press("Space")
    expect(tts).to_have_attribute("aria-checked", "true")
    tts.press("Space")
    expect(tts).to_have_attribute("aria-checked", "false")
    calls = [(ep, data) for ep, data in peer.sent if ep.startswith("/run/")]
    assert [ep for ep, _ in calls] == ["/run/enable_tts", "/run/disable_tts"]
    assert calls[0][1] == {"generation": 0}
    assert not any(ep == "/get/data/voice_output_devices" for ep, _ in peer.sent)
    assert page.get_by_role("switch").all_text_contents()[-2:] == ["TTS", "RVC"]


def test_independent_toggle_combinations_and_pending_cancel(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    configure(page, peer, reply)
    tts = page.get_by_role("switch", name="TTS", exact=True)
    rvc = page.get_by_role("switch", name="RVC", exact=True)
    tts.click()
    expect(tts).to_have_attribute("aria-checked", "true")
    rvc.click()
    expect(rvc).to_have_attribute("aria-checked", "true")
    tts.click()
    expect(tts).to_have_attribute("aria-checked", "false")
    expect(rvc).to_have_attribute("aria-checked", "true")
    rvc.click()
    expect(rvc).to_have_attribute("aria-checked", "false")
    peer.hold_direct = True
    rvc.click()
    expect(rvc).to_have_attribute("aria-busy", "true")
    stale = copy.deepcopy(peer.direct)
    rvc.click()
    expect(rvc).to_have_attribute("aria-busy", "false")
    late = reply(
        "/run/start_direct_voice",
        dict(stale, active=True, requested=True, mode="converted", observation_id="1"),
    )
    page.wait_for_function("id => window.received.includes(id)", arg=late)
    expect(rvc).to_have_attribute("aria-checked", "false")
    starts = [data for ep, data in peer.sent if ep == "/run/start_direct_voice"]
    assert starts[0] == dict(
        source=peer.sources[0]["id"],
        mode="converted",
        options=dict(
            engine="rvc",
            runtime="/allowed/rvc",
            model="/allowed/voice.pth",
            index="",
            pitch=0,
            index_rate=0,
        ),
    )
    assert not any(
        ep in ("/run/mute_voice", "/run/resume_voice", "/run/stop_realtime_asr")
        for ep, _ in peer.sent
    )


def test_tts_failure_and_delayed_enable_do_not_restore_switch(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    tts = page.get_by_role("switch", name="TTS", exact=True)
    peer.reject_tts = "speech_server_or_settings_not_ready"
    tts.click()
    expect(
        page.get_by_role("alert").filter(has_text="speech_server_or_settings_not_ready")
    ).to_be_visible()
    expect(tts).to_have_attribute("aria-checked", "false")
    peer.reject_tts = None
    peer.hold_tts = True
    tts.click()
    expect(tts).to_have_attribute("aria-busy", "true")
    tts.click()
    expect(tts).to_have_attribute("aria-busy", "false")
    late = reply(
        "/run/enable_tts", dict(tts_enabled=True, tts_generation=0, observation_id="1")
    )
    page.wait_for_function("id => window.received.includes(id)", arg=late)
    expect(tts).to_have_attribute("aria-checked", "false")


def test_rvc_does_not_hijack_original_input(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    peer.direct.update(requested=True, active=True, mode="passthrough")
    reply("/get/data/direct_voice_state", dict(peer.direct, observation_id="10000"))
    rvc = page.get_by_role("switch", name="RVC", exact=True)
    expect(rvc).to_have_attribute("aria-checked", "false")
    rvc.click()
    expect(
        page.get_by_role("alert").filter(has_text="Another direct input engine")
    ).to_be_visible()
    assert not any(
        ep in ("/run/start_direct_voice", "/run/stop_direct_voice")
        for ep, _ in peer.sent
    )


def test_rvc_numbers_preserve_seed_paths_and_lock_during_start(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    peer.direct["settings"].update(
        runtime="/seed/runtime", reference="/seed/permitted.wav"
    )
    peer.sequence += 1
    reply(
        "/get/data/direct_voice_state",
        dict(peer.direct, observation_id=str(peer.sequence)),
    )
    page.get_by_role("button", name="RVC", exact=True).click()
    save = page.get_by_role("button", name="Save changes", exact=True)
    pitch = page.get_by_label("Pitch shift (semitones)", exact=True)
    for invalid in ("25", "-25", "0.5"):
        pitch.fill(invalid)
        expect(save).to_be_disabled()
    for valid in ("-24", "24"):
        pitch.fill(valid)
        expect(save).to_be_enabled()
    page.get_by_label("RVC runtime folder", exact=True).fill("/rvc/runtime")
    page.get_by_label("Permitted RVC model (.pth)", exact=True).fill(
        "/rvc/permitted.pth"
    )
    page.get_by_label("Retrieval blend (0–1)", exact=True).fill("1")
    page.get_by_label("RVC retrieval index (.index, optional)", exact=True).fill(
        "/rvc/permitted.index"
    )
    save.click()
    expect(save).to_be_disabled()
    assert peer.direct["settings"]["runtime"] == "/seed/runtime"
    assert peer.direct["settings"]["reference"] == "/seed/permitted.wav"
    assert peer.direct["settings"]["rvc_pitch"] == 24
    assert peer.direct["settings"]["rvc_index_rate"] == 1
    peer.voice["routing"] = "managed"
    reply("/get/data/voice_settings", peer.voice)
    source = page.get_by_label("Input to forward", exact=True)
    source.select_option(label="Test microphone")
    peer.hold_direct = True
    page.get_by_role("switch", name="RVC", exact=True).click()
    expect(source).to_be_disabled()
    expect(pitch).to_be_disabled()


@pytest.mark.parametrize("mode", ["passthrough", "converted"])
def test_rvc_does_not_cancel_other_engine_start_request(pages, mode):
    from playwright.sync_api import expect

    page, peer, reply = pages
    peer.voice["routing"] = "managed"
    peer.direct["settings"].update(
        mode=mode, runtime="/seed/runtime", reference="/seed/permitted.wav"
    )
    reply("/get/data/voice_settings", peer.voice)
    peer.sequence += 1
    reply(
        "/get/data/direct_voice_state",
        dict(peer.direct, observation_id=str(peer.sequence)),
    )
    page.get_by_role("button", name="Advanced", exact=True).click()
    page.get_by_label("Input to forward", exact=True).select_option(
        label="Test microphone"
    )
    peer.hold_direct = True
    page.get_by_role("button", name="Start input forwarding", exact=True).click()
    rvc = page.get_by_role("switch", name="RVC", exact=True)
    rvc.click()
    expect(
        page.get_by_role("alert").filter(has_text="Another direct input engine")
    ).to_be_visible()
    assert not any(ep == "/run/stop_direct_voice" for ep, _ in peer.sent)
    expect(rvc).to_have_attribute("aria-busy", "false")


def test_rvc_page_can_cancel_start_before_response(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    configure(page, peer, reply)
    peer.hold_direct = True
    page.get_by_role("switch", name="RVC", exact=True).click()
    expect(
        page.get_by_role("button", name="Start input forwarding", exact=True)
    ).to_be_disabled()
    stop = page.get_by_role("button", name="Stop input forwarding", exact=True)
    expect(stop).to_be_enabled()
    stop.click()
    expect(page.get_by_role("switch", name="RVC", exact=True)).to_have_attribute(
        "aria-busy", "false"
    )
    assert len([ep for ep, _ in peer.sent if ep == "/run/stop_direct_voice"]) == 1


def test_rvc_stop_timeout_keeps_owner_and_pending_until_drained(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    configure(page, peer, reply)
    rvc = page.get_by_role("switch", name="RVC", exact=True)
    rvc.click()
    expect(rvc).to_have_attribute("aria-checked", "true")
    peer.drain_direct = True
    rvc.click()
    expect(rvc).to_have_attribute("aria-busy", "true")
    page.wait_for_timeout(5200)  # Cross the production acknowledgement timeout.
    expect(rvc).to_have_attribute("aria-busy", "true")
    expect(
        page.get_by_role("alert").filter(has_text="voice_request_unconfirmed").first
    ).to_be_visible()
    expect(page.get_by_label("Input to forward", exact=True)).to_be_disabled()
    peer.direct["stopping"] = False
    peer.sequence += 1
    reply(
        "/get/data/direct_voice_state",
        dict(peer.direct, observation_id=str(peer.sequence)),
    )
    expect(rvc).to_have_attribute("aria-busy", "false")


@pytest.mark.parametrize("pages", ["main"], indirect=True)
def test_rvc_worker_failure_is_notified_on_main(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    peer.direct["settings"].update(mode="converted", engine="rvc")
    peer.direct.update(mode="converted", requested=True, pending=True, generation=1)
    peer.sequence += 1
    reply(
        "/get/data/direct_voice_state",
        dict(peer.direct, observation_id=str(peer.sequence)),
    )
    expect(page.get_by_role("switch", name="RVC", exact=True)).to_have_attribute(
        "aria-busy", "true"
    )
    peer.direct.update(
        mode="off", requested=False, pending=False, error="rvc_worker_failed"
    )
    peer.sequence += 1
    reply(
        "/get/data/direct_voice_state",
        dict(peer.direct, observation_id=str(peer.sequence)),
    )
    expect(
        page.get_by_role("alert").filter(has_text="rvc_worker_failed")
    ).to_be_visible()


def test_rvc_top_requires_saved_form_and_explains_invalid_numbers(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    configure(page, peer, reply)
    pitch = page.get_by_label("Pitch shift (semitones)", exact=True)
    pitch.fill("1")
    page.get_by_role("switch", name="RVC", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Save or discard")).to_be_visible()
    assert not any(ep == "/run/start_direct_voice" for ep, _ in peer.sent)
    pitch.fill("0.5")
    expect(pitch).to_have_attribute("aria-invalid", "true")
    expect(
        page.get_by_role("alert").filter(has_text="integer from -24 to 24")
    ).to_be_visible()
    pitch.fill("0")
    blend = page.get_by_label("Retrieval blend (0–1)", exact=True)
    for invalid in ("-0.1", "1.1", ""):
        blend.fill(invalid)
        expect(blend).to_have_attribute("aria-invalid", "true")
        expect(
            page.get_by_role("button", name="Save changes", exact=True)
        ).to_be_disabled()
    blend.fill("1")
    expect(
        page.get_by_role("alert").filter(has_text="index is required")
    ).to_be_visible()
    expect(
        page.get_by_role("button", name="Start input forwarding", exact=True)
    ).to_be_disabled()


def test_tts_failure_names_the_next_step(pages):
    from playwright.sync_api import expect

    page, peer, _ = pages
    tts = page.get_by_role("switch", name="TTS", exact=True)
    peer.reject_tts = "voice_route_muted"
    tts.click()
    alert = page.get_by_role("alert").filter(has_text="voice_route_muted")
    expect(alert).to_contain_text('press "Resume voice"')
    expect(alert).not_to_contain_text("Check TTS settings.")
    expect(tts).to_have_attribute("aria-checked", "false")


@pytest.mark.parametrize("pages", ["main"], indirect=True)
def test_server_start_shows_starting_and_outlasts_the_confirmation_timer(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    tts = page.get_by_role("switch", name="TTS", exact=True)
    peer.hold_tts = True
    peer.tts["tts_server_starting"] = True  # Status polls report the model load.
    tts.click()
    expect(tts).to_have_attribute("aria-busy", "true")
    expect(tts).to_contain_text("Starting server…")
    page.wait_for_timeout(6500)  # Past the ordinary 5 s confirmation timer.
    expect(page.get_by_role("alert").filter(has_text="voice_request_unconfirmed")).to_have_count(0)
    expect(tts).to_have_attribute("aria-busy", "true")
    peer.tts.update(tts_enabled=True, tts_generation=1, tts_server_starting=False)
    peer.sequence += 1
    ready = reply("/run/enable_tts", dict(peer.tts, observation_id=str(peer.sequence)))
    page.wait_for_function("id => window.received.includes(id)", arg=ready)
    expect(tts).to_have_attribute("aria-checked", "true")
    expect(tts).not_to_contain_text("Starting server…")


@pytest.mark.parametrize("pages", ["main"], indirect=True)
def test_off_during_server_start_cancels_without_an_error(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    tts = page.get_by_role("switch", name="TTS", exact=True)
    peer.hold_tts = True
    peer.tts["tts_server_starting"] = True
    tts.click()
    expect(tts).to_contain_text("Starting server…")
    peer.tts["tts_server_starting"] = False
    tts.click()
    expect(tts).to_have_attribute("aria-busy", "false")
    cancelled = reply("/run/enable_tts", dict(error_code="tts_enable_cancelled"), 409)
    page.wait_for_function("id => window.received.includes(id)", arg=cancelled)
    expect(page.get_by_role("alert").filter(has_text="tts_enable_cancelled")).to_have_count(0)
    expect(tts).to_have_attribute("aria-checked", "false")
    assert [ep for ep, _ in peer.sent if ep.startswith("/run/")] == ["/run/enable_tts", "/run/disable_tts"]
