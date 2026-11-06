"""Numeric limits shared by persistence, IPC and the OBS page."""

import re


NUMERIC_RANGES = {
    "MAX_MESSAGES": (1, 50),
    "DISPLAY_DURATION": (1, 120),
    "FADEOUT_DURATION": (0, 120),
    "FONT_SIZE": (10, 200),
    "FONT_OUTLINE_THICKNESS": (0, 20),
}


def is_valid_numeric_setting(name, value):
    minimum, maximum = NUMERIC_RANGES[name]
    return type(value) is int and minimum <= value <= maximum


def parse_numeric_setting(name, value):
    # Existing text controls send decimal strings over IPC.
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        value = int(value)
    if not is_valid_numeric_setting(name, value):
        raise ValueError(f"Invalid OBS {name}")
    return value
