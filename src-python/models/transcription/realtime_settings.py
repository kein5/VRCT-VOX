"""Persist choices, never recording intent; endpoint integers stay exact in IPC."""

from dataclasses import dataclass
import re

from models.audio_routing.source_bridge import Endpoint
from models.tts.settings import local_url
from .capture_pipewire import _validate


@dataclass(frozen=True)
class SessionOptions:
    base_url: str
    model: str
    language: str

    def __post_init__(self):
        local_url(self.base_url)
        _model(self.model, empty=False)
        _language(self.language)


def _model(value, *, empty=True):
    if (
        not isinstance(value, str)
        or len(value) > 200
        or (not empty and not value.strip())
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("realtime_model_invalid")
    return value


def _language(value):
    # Explicit requested language; the protocol doesn't return detected language.
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", value)
        or value == "auto"
    ):
        raise ValueError("realtime_language_invalid")
    return value


def parse_endpoint(value, source):
    if not isinstance(value, dict) or set(value) != {
        "cookie",
        "serial",
        "name",
        "media_class",
    }:
        raise ValueError("realtime_endpoint_invalid")
    numbers = []
    for key, bits in (("cookie", 32), ("serial", 64)):
        text = value[key]
        if (
            not isinstance(text, str)
            or not 1 <= len(text) <= 20
            or not text.isascii()
            or not text.isdecimal()
            or (len(text) > 1 and text.startswith("0"))
            or int(text) >= 2**bits
        ):
            raise ValueError("realtime_endpoint_invalid")
        numbers.append(int(text))
    endpoint = Endpoint(*numbers, value["name"], value["media_class"])
    _validate(endpoint, source)
    return endpoint


def endpoint_dict(endpoint):
    return dict(
        cookie=str(endpoint.cookie),
        serial=str(endpoint.serial),
        name=endpoint.name,
        media_class=endpoint.media_class,
    )


def normalize_settings(value):
    if not isinstance(value, dict) or set(value) - {
        "version",
        "base_url",
        "model",
        "mic",
        "speaker",
    }:
        raise ValueError("realtime_settings_invalid")
    version = value.get("version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("realtime_settings_version")
    result = dict(
        version=1,
        base_url=local_url(value.get("base_url", "http://127.0.0.1:8080")),
        model=_model(value.get("model", "")),
    )
    for source in ("mic", "speaker"):
        row = value.get(source, {})
        if not isinstance(row, dict) or set(row) - {"language", "endpoint"}:
            raise ValueError("realtime_source_settings_invalid")
        selected = row.get("endpoint")
        result[source] = dict(
            language=_language(row.get("language", "ja")),
            endpoint=None
            if selected is None
            else endpoint_dict(parse_endpoint(selected, source)),
        )
    return result


def session_options(value, source):
    settings = normalize_settings(value)
    if source not in ("mic", "speaker") or settings[source]["endpoint"] is None:
        raise ValueError("realtime_endpoint_required")
    return (
        SessionOptions(
            settings["base_url"], settings["model"], settings[source]["language"]
        ),
        parse_endpoint(settings[source]["endpoint"], source),
    )
