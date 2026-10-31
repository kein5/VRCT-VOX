import os
import pytest
from test_voice_pages_ui import pages as pages, ui as ui

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['pages']

pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_SPEECH_UI") != "1", reason="opt-in browser integration"
)


def japanese(page):
    return page.get_by_role(
        "group", name="Japanese TTS · Text to voice (speech.cpp)", exact=True
    )


def test_zero_instruction_save_reload_and_random_omission(pages):
    from playwright.sync_api import expect

    page, peer, _ = pages
    group = japanese(page)
    group.get_by_label("Seed mode", exact=True).select_option("fixed")
    seed = group.get_by_label("Seed value", exact=True)
    expect(seed).to_have_value("0")
    instruction = group.get_by_label("Instruction", exact=True)
    instruction.fill("やさしく\nゆっくり。")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(
        page.get_by_role("button", name="Save changes", exact=True)
    ).to_be_disabled()
    assert peer.voice["japanese_seed"] == "0"
    assert peer.voice["japanese_instructions"] == "やさしく\nゆっくり。"
    assert peer.voice["multilingual_seed"] == ""
    page.reload()
    expect(seed).to_have_value("0")
    expect(instruction).to_have_value("やさしく\nゆっくり。")
    group.get_by_label("Seed mode", exact=True).select_option("random")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(
        page.get_by_role("button", name="Save changes", exact=True)
    ).to_be_disabled()
    assert peer.voice["japanese_seed"] == ""
    assert not any(ep.startswith("/run/start_") for ep, _ in peer.sent)


def test_seed_bounds_and_unknown_or_unsupported_capabilities_keep_edits(pages):
    from playwright.sync_api import expect

    page, peer, reply = pages
    group = japanese(page)
    group.get_by_label("Seed mode", exact=True).select_option("fixed")
    seed = group.get_by_label("Seed value", exact=True)
    save = page.get_by_role("button", name="Save changes", exact=True)
    for invalid in ("-1", "1.5", "1e3", "9007199254740992", "100000000000000000"):
        seed.fill(invalid)
        expect(save).to_be_disabled()
        expect(seed).to_have_value(invalid)
    seed.fill("9007199254740991")
    expect(save).to_be_enabled()
    group.get_by_label("Instruction", exact=True).fill("keep this")
    peer.model_options = dict(model="small-tts", seed=None, instructions=False)
    group.get_by_role("button", name="Check model options", exact=True).click()
    expect(
        group.get_by_role("status").filter(has_text="Instruction: Not supported")
    ).to_be_visible()
    expect(group.get_by_label("Instruction", exact=True)).to_have_value("keep this")
    peer.hold_options = True
    group.get_by_role("button", name="Check model options", exact=True).click()
    expect(group.get_by_role("status").filter(has_text="Not confirmed")).to_be_visible()
    requests = [
        data
        for ep, data in peer.sent
        if ep == "/get/data/tts_model_options" and data["role"] == "japanese"
    ]
    old = requests[-2]
    received = reply(
        "/get/data/tts_model_options",
        dict(
            role="japanese",
            request_id=old["request_id"],
            server="external",
            configured_url=peer.voice["japanese_url"],
            server_generation=None,
            options=dict(
                model="old", seed=dict(minimum=0, maximum=10), instructions=True
            ),
        ),
    )
    page.wait_for_function("id => window.received.includes(id)", arg=received)
    expect(group.get_by_role("status").filter(has_text="Not confirmed")).to_be_visible()
    expect(group.get_by_label("Instruction", exact=True)).to_have_value("keep this")
