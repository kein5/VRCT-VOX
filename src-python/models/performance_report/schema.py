"""The list of what a performance report may hold. The receiver keeps the same list."""
import math
import re

SCHEMA = 1
# What ran during the session: how long it was on, and where.
FEATURES = ("tts", "captions_mic", "captions_speaker", "diarization", "legacy_asr_mic", "legacy_asr_speaker",
            "translation", "rvc", "seed_vc", "ocr", "vr_overlay", "desktop_overlay")
# Delays in milliseconds, each as a count with its median, 95th percentile and maximum.
TIMINGS = ("caption_mic_final_ms", "caption_speaker_final_ms", "tts_first_audio_ms", "translation_ms",
           "voice_roundtrip_ms", "voice_block_delay_ms")
COUNTERS = ("voice_blocks", "voice_late_blocks", "voice_stops_overrun", "captions_final", "captions_dropped",
            "tts_requests")
MAX_BODY_BYTES = 16 * 1024
DAY_SECONDS = 86400

_PRINTABLE = re.compile(r"[\x20-\x7e]+")


def _text(limit, pattern=_PRINTABLE):
    return lambda value: isinstance(value, str) and 1 <= len(value) <= limit and pattern.fullmatch(value) is not None


def _integer(low, high):
    return lambda value: type(value) is int and low <= value <= high


def _number(low, high):
    return lambda value: (type(value) in (int, float) and math.isfinite(value) and low <= value <= high)


def _one_of(*choices):
    return lambda value: isinstance(value, str) and value in choices


def _object(required, optional=None):
    optional = optional or {}

    def check(value):
        return (isinstance(value, dict) and all(key in required or key in optional for key in value)
                and all(key in value and test(value[key]) for key, test in required.items())
                and all(test(value[key]) for key, test in optional.items() if key in value))
    return check


def _list(limit, item):
    return lambda value: isinstance(value, list) and len(value) <= limit and all(item(row) for row in value)


def _record(names, item):
    return lambda value: isinstance(value, dict) and all(name in names and item(row) for name, row in value.items())


def _errors(value):
    return (isinstance(value, dict) and len(value) <= 50
            and all(isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", code) and _integer(1, 1_000_000)(count)
                    for code, count in value.items()))


_SHAPE = {
    "schema": lambda value: type(value) is int and value == SCHEMA,
    "app_version": _text(40, re.compile(r"[0-9A-Za-z.+-]+")),
    "os": _one_of("windows", "linux"),
    "os_version": _text(60),
    "session_id": lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None,
    "sequence": _integer(0, 10000),
    "uptime_s": _integer(0, 30 * DAY_SECONDS),
    "vrchat": lambda value: type(value) is bool,
    "cpu": _object({"model": _text(100), "logical": _integer(1, 1024), "memory_gb": _number(0, 8192)}),
    "gpus": _list(8, _object({"name": _text(100), "kind": _one_of("gpu", "igpu", "other"), "memory_gb": _number(0, 1024)})),
    "features": _record(FEATURES, _object(
        {"used_s": _integer(0, 30 * DAY_SECONDS)},
        # "auto", "cpu", "gpu", "cuda" or a device by the engine's name, such as "Vulkan1".
        # A catalog id such as "qwen3-asr-06b-q8", or "custom" for a file of the user's own.
        {"device": _text(20, re.compile(r"[0-9A-Za-z]+")), "model": _text(60, re.compile(r"[0-9a-z][0-9a-z._-]*"))})),
    "timings": _record(TIMINGS, _object({
        "n": _integer(1, 10_000_000), "p50": _number(0, 3_600_000), "p95": _number(0, 3_600_000), "max": _number(0, 3_600_000)})),
    "counters": _record(COUNTERS, _integer(0, 1_000_000_000)),
    # How often each failure with a fixed code happened, such as "vc_capture_overrun".
    "errors": _errors,
}


def fault_of(report):
    """The first field at fault, or None for a report that may be sent.

    A report that carries anything outside the list is refused whole, here before it is
    sent and again by the receiver.
    """
    if not isinstance(report, dict):
        return "report"
    if any(key not in _SHAPE for key in report):
        return "unknown_field"
    for key, check in _SHAPE.items():
        if key not in report or not check(report[key]):
            return key
    return None


def ascii_text(value, limit):
    """A hardware or version string as the report may carry it, or "" when nothing is left.

    Such strings come from drivers and the OS. Whatever is not printable ASCII is dropped,
    so a name in another script never travels.
    """
    if not isinstance(value, str):
        return ""
    kept = "".join(char if " " <= char <= "~" else " " if char.isspace() else "" for char in value)
    return " ".join(kept.split())[:limit].strip()
