"""Where the user's own voice and typed chat go with the current settings.

The flow panel and its overlays draw this. The controller gathers the state;
describe() only turns it into two lanes. Every output says whether it is used
now, and when it is not, why, as a fixed code the UI puts into words. Nothing
here is logged or leaves the PC.
"""


def _output(name, on, reason=None, **detail):
    return {"id": name, "on": bool(on), "reason": None if on else reason, **detail}


def _chatbox(state):
    if not state["send_to_vrc"]:
        return _output("chatbox", False, "vrchat_off")
    if not state["translation"]:
        content = "original"
    elif state["only_translated"]:
        content = "translation"
    else:
        content = "both"
    return _output("chatbox", True, content=content)


def _speech_block(state):
    """Why speech cannot play at all right now, whatever the input."""
    if state["muted"]:
        return "muted"
    if not state["tts_enabled"]:
        return "tts_off"
    return None


def _speech_path(state):
    # Through the conversion only while it runs (ADR-007); otherwise the TTS output device.
    direct = state["direct"]
    converted = (state["voice"].get("conversion") == "on" and direct["mode"] == "converted"
                 and direct["active"])
    return "converted" if converted else "device"


def _voice(state):
    # While the microphone is off the lane says so once, and its outputs still show
    # where the voice would go when it is turned on.
    voice = state["voice"]
    if voice.get("mic_mode") != "translated":
        speech_reason = "mic_speech_off"
    elif not state["translation"]:
        speech_reason = "translation_off"
    elif not state["realtime"]:
        speech_reason = "not_realtime"
    else:
        speech_reason = _speech_block(state)
    speaking = speech_reason is None
    direct = state["direct"]
    if state["muted"]:
        live = "muted"
    elif direct["mode"] == "off" or not direct["active"]:
        live = "vrchat_mic"  # VRCT-VOX does not carry the voice; VRChat reads the microphone itself.
    else:
        live = direct["mode"]  # "converted" or "passthrough"
    during_speech = None
    if speaking and live in ("converted", "passthrough"):
        during_speech = voice.get("direct_policy", "suppress")
    outputs = [
        _chatbox(state),
        _output("speech", speaking, speech_reason, path=_speech_path(state) if speaking else None,
                language=state["speech_language"] if speaking else None),
        _output("live_voice", live != "muted", "muted", carried=live, engine=direct.get("engine"),
                during_speech=during_speech),
        _output("desktop_caption", state["desktop"], "setting_off"),
        _output("vr_log", state["large_log"], "setting_off"),
        _output("clipboard", state["clipboard"], "setting_off"),
        _output("websocket", state["websocket"], "setting_off"),
    ]
    return {
        "on": state["mic_on"],
        "recognition": {"realtime": state["realtime"], "engine": None if state["realtime"] else state["engine"]},
        "translation": _translation(state),
        "outputs": outputs,
    }


def _chat(state):
    voice = state["voice"]
    mode = voice.get("mode", "off")
    if mode == "off":
        speech_reason = "chat_speech_off"
    elif mode == "translated" and not state["translation"]:
        speech_reason = "translation_off"
    else:
        speech_reason = _speech_block(state)
    speaking = speech_reason is None
    outputs = [
        _chatbox(state),
        _output("speech", speaking, speech_reason, path=_speech_path(state) if speaking else None,
                content=mode if speaking else None,
                language=(state["speech_language"] if mode == "translated" else state["source_language"])
                if speaking else None),
        _output("desktop_caption", state["desktop"], "setting_off"),
        _output("vr_log", state["large_log"], "setting_off"),
        _output("websocket", state["websocket"], "setting_off"),
    ]
    return {"on": True, "translation": _translation(state), "outputs": outputs}


def _translation(state):
    return {"on": state["translation"], "source": state["source_language"],
            "targets": list(state["targets"]) if state["translation"] else []}


def describe(state):
    return {"voice": _voice(state), "chat": _chat(state), "conversion_round_trip_ms": state["round_trip_ms"]}
