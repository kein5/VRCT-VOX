"""Persist choices, never recording intent; endpoint integers stay exact in IPC."""

from dataclasses import dataclass
import re

from .asr_vocabulary import MAX_TERMS, merged_terms, normalize_vocabulary, parse_term

from models.audio_routing.source_bridge import Endpoint
from models.tts.settings import local_url
from .capture_pipewire import _validate


@dataclass(frozen=True)
class SessionOptions:
    base_url: str
    model: str
    language: str
    # Merged vocabulary terms; sent as keywords or a prompt where the model takes one.
    vocabulary: tuple = ()

    def __post_init__(self):
        local_url(self.base_url)
        _model(self.model, empty=False)
        _language(self.language)
        if (not isinstance(self.vocabulary, tuple) or len(self.vocabulary) > MAX_TERMS
                or any(parse_term(term) != term for term in self.vocabulary)):
            raise ValueError("realtime_vocabulary_invalid")


def _model(value, *, empty=True):
    if (
        not isinstance(value, str)
        or len(value) > 200
        or (not empty and not value.strip())
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("realtime_model_invalid")
    return value


AUTO = "auto"
# A fresh speaker setting detects the language: other players speak anything.
# The microphone keeps Japanese, which steers the model toward the user's speech.
DEFAULT_LANGUAGE = dict(mic="ja", speaker=AUTO)


def _language(value):
    # "auto" asks the model to detect the language; whether the selected model
    # can is checked against its /v1/models options when a session starts.
    if not isinstance(value, str) or not (
        value == AUTO or re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", value)
    ):
        raise ValueError("realtime_language_invalid")
    return value


def language_supported(model, language):
    """Whether a RecognitionModel takes language; "auto" needs real detection."""
    if language == AUTO:
        return bool(getattr(model, "detects_language", False))
    return language in model.languages


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
        "server",
        "base_url",
        "model",
        "mic",
        "speaker",
        "vocabulary",
    }:
        raise ValueError("realtime_settings_invalid")
    version = value.get("version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("realtime_settings_version")
    server = value.get("server", "external")
    if server not in ("external", "bundled"):
        raise ValueError("realtime_server_invalid")
    result = dict(
        version=1,
        server=server,
        base_url=local_url(value.get("base_url", "http://127.0.0.1:8080")),
        model=_model(value.get("model", "")),
        vocabulary=normalize_vocabulary(value.get("vocabulary")),
    )
    for source in ("mic", "speaker"):
        row = value.get(source, {})
        if not isinstance(row, dict) or set(row) - {"language", "endpoint", "follow_default"}:
            raise ValueError("realtime_source_settings_invalid")
        selected = row.get("endpoint")
        # Following the system default is a choice, never a fallback: it
        # applies only while no endpoint is picked, is resolved once per start,
        # and that endpoint is then pinned. A picked endpoint always wins.
        follow = row.get("follow_default", True)
        if type(follow) is not bool:
            raise ValueError("realtime_source_settings_invalid")
        result[source] = dict(
            language=_language(row.get("language", DEFAULT_LANGUAGE[source])),
            endpoint=None
            if selected is None
            else endpoint_dict(parse_endpoint(selected, source)),
            follow_default=follow,
        )
    return result


def realtime_endpoint(value, source):
    """The pinned endpoint, or None to resolve the system default at start."""
    settings = normalize_settings(value)
    if source not in ("mic", "speaker"):
        raise ValueError("realtime_endpoint_required")
    row = settings[source]
    if row["endpoint"] is None and not row["follow_default"]:
        raise ValueError("realtime_endpoint_required")
    return None if row["endpoint"] is None else parse_endpoint(row["endpoint"], source)


def session_options(value, source):
    """Options and realtime_endpoint(); a session needs a saved model id."""
    endpoint = realtime_endpoint(value, source)
    settings = normalize_settings(value)
    return (
        SessionOptions(settings["base_url"], settings["model"], settings[source]["language"],
                       merged_terms(settings["vocabulary"])),
        endpoint,
    )
