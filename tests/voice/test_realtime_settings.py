import copy
import importlib

import pytest


def module():
    return importlib.import_module("models.transcription.realtime_settings")


def test_default_settings_have_no_recording_intent_and_roundtrip():
    m = module()
    value = m.normalize_settings({})
    assert value == {
        "version": 1,
        "base_url": "http://127.0.0.1:8080",
        "model": "",
        "mic": {"language": "ja", "endpoint": None},
        "speaker": {"language": "ja", "endpoint": None},
    }
    assert m.normalize_settings(value) == value
    assert m.normalize_settings(value) is not value
    with pytest.raises(ValueError):
        m.session_options(value, "mic")


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("version", True),
        ("enabled", True),
        ("base_url", "https://example.com"),
        ("base_url", "http://127.0.0.1:8080/path"),
        ("model", "x" * 201),
        ("model", "\nsecret"),
        ("mic", {"language": "ja", "endpoint": None, "active": True}),
        ("speaker", {"language": True}),
        ("mic", {"language": "auto"}),
    ],
)
def test_bad_settings_fail_without_silent_fallback(field, value):
    with pytest.raises(ValueError):
        module().normalize_settings({field: value})


@pytest.mark.parametrize(
    "change",
    [
        {"cookie": 1},
        {"serial": "01"},
        {"serial": str(2**64)},
        {"name": "vrct.managed.mic"},
        {"name": "vrct.asr.capture.a"},
        {"name": "bad\0name"},
        {"media_class": "Audio/Sink"},
        {"extra": "value"},
    ],
)
def test_endpoint_identity_remains_precise_and_source_specific(change):
    endpoint = dict(
        cookie="4294967295",
        serial="18446744073709551615",
        name="selected",
        media_class="Audio/Source",
    )
    endpoint.update(change)
    with pytest.raises(ValueError):
        module().normalize_settings({"mic": {"language": "ja", "endpoint": endpoint}})


def test_model_and_each_endpoint_are_explicit_and_not_mutated():
    m = module()
    endpoint = dict(
        cookie="1",
        serial="18446744073709551615",
        name="selected",
        media_class="Audio/Source",
    )
    given = {"model": "asr", "mic": {"language": "ja", "endpoint": endpoint}}
    before = copy.deepcopy(given)
    value = m.normalize_settings(given)
    options, selected = m.session_options(value, "mic")
    assert (options.base_url, options.model, options.language) == (
        "http://127.0.0.1:8080",
        "asr",
        "ja",
    )
    assert selected.serial == 2**64 - 1 and selected.media_class == "Audio/Source"
    assert given == before
    with pytest.raises(ValueError):
        m.session_options(value, "speaker")
    with pytest.raises(ValueError):
        m.session_options(value, "other")


def test_localhost_input_is_canonicalized_without_dns_lookup():
    assert (
        module().normalize_settings({"base_url": "http://localhost:8080"})["base_url"]
        == "http://127.0.0.1:8080"
    )
