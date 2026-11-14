"""The flow panel's route map: where the user's voice and chat go with the current settings."""
import pytest

from models.io_flow import describe
from models.io_trace import IoTraces


def state(**changes):
    base = dict(
        mic_on=True, realtime=True, engine="Whisper", translation=True,
        source_language="Japanese", targets=["English"], speech_language="English",
        send_to_vrc=True, only_translated=False, desktop=True, large_log=False,
        clipboard=False, websocket=False,
        voice=dict(mode="off", mic_mode="translated", direct_policy="suppress", conversion="off"),
        tts_enabled=True, muted=False,
        direct=dict(mode="converted", active=True, engine="rvc"), round_trip_ms=31,
    )
    voice = changes.pop("voice", {})
    direct = changes.pop("direct", {})
    base.update(changes)
    base["voice"] = {**base["voice"], **voice}
    base["direct"] = {**base["direct"], **direct}
    return base


def outputs(lane):
    return {row["id"]: row for row in lane["outputs"]}


def test_spoken_translation_with_the_converted_voice():
    flow = describe(state(voice=dict(conversion="on")))
    voice = outputs(flow["voice"])
    assert voice["chatbox"] == {"id": "chatbox", "on": True, "reason": None, "content": "both"}
    assert voice["speech"]["on"] and voice["speech"]["path"] == "converted"
    assert voice["speech"]["language"] == "English"
    assert voice["live_voice"]["carried"] == "converted" and voice["live_voice"]["engine"] == "rvc"
    assert voice["live_voice"]["during_speech"] == "suppress"
    assert voice["vr_log"] == {"id": "vr_log", "on": False, "reason": "setting_off"}
    assert flow["conversion_round_trip_ms"] == 31


@pytest.mark.parametrize("changes, reason", [
    (dict(mic_on=False), "mic_off"),
    (dict(voice=dict(mic_mode="off")), "mic_speech_off"),
    (dict(translation=False), "translation_off"),
    (dict(realtime=False), "not_realtime"),
    (dict(tts_enabled=False), "tts_off"),
    (dict(muted=True), "muted"),
])
def test_why_the_voice_is_not_spoken(changes, reason):
    speech = outputs(describe(state(**changes))["voice"])["speech"]
    assert (speech["on"], speech["reason"], speech["path"]) == (False, reason, None)


def test_speech_goes_to_the_device_when_the_conversion_does_not_run():
    flow = describe(state(voice=dict(conversion="on"), direct=dict(mode="off", active=False)))
    voice = outputs(flow["voice"])
    assert voice["speech"]["path"] == "device"
    # VRChat reads the microphone itself; VRCT-VOX does not carry the voice.
    assert voice["live_voice"]["carried"] == "vrchat_mic" and voice["live_voice"]["during_speech"] is None


def test_chatbox_content_follows_translation_and_send_only_translated():
    assert outputs(describe(state(only_translated=True))["chat"])["chatbox"]["content"] == "translation"
    assert outputs(describe(state(translation=False))["chat"])["chatbox"]["content"] == "original"
    off = outputs(describe(state(send_to_vrc=False))["voice"])["chatbox"]
    assert (off["on"], off["reason"]) == (False, "vrchat_off")


def test_muted_voice_is_shown_as_stopped():
    live = outputs(describe(state(muted=True))["voice"])["live_voice"]
    assert (live["on"], live["reason"], live["carried"]) == (False, "muted", "muted")


@pytest.mark.parametrize("mode, translation, on, language, reason", [
    ("off", True, False, None, "chat_speech_off"),
    ("original", True, True, "Japanese", None),
    ("translated", True, True, "English", None),
    ("translated", False, False, None, "translation_off"),
])
def test_chat_speech(mode, translation, on, language, reason):
    speech = outputs(describe(state(translation=translation, voice=dict(mode=mode)))["chat"])["speech"]
    assert (speech["on"], speech["language"], speech["reason"]) == (on, language, reason)


def test_speech_that_starts_before_publication_is_in_the_publication():
    sent = []
    traces = IoTraces(sent.append)
    trace = traces.begin("a", "chat", "hello", "send", origin_ns=1_000_000_000)
    assert traces.speech_started("a", 1_250_000_000, converted=False)
    assert sent == []  # The message's own publication carries it.
    trace.speech_queued(True)  # A late "queued" never hides that speech already plays.
    traces.publish(trace)
    assert sent[0]["outputs"]["speech"] == {"state": "playing", "at_ms": 250, "converted": False}
    assert not traces.speech_started("unknown", 1, converted=False)


def test_old_traces_are_dropped_and_text_is_bounded():
    traces = IoTraces(lambda payload: None)
    for index in range(40):
        traces.begin(index, "voice", "x" * 500, "final")
    assert not traces.speech_started("0", 1, converted=False)
    assert traces.speech_started("39", 1, converted=False)
    assert len(traces.begin("b", "chat", "y" * 500, "send").to_dict()["text"]) == 200
