"""A PC with two GPUs has to be able to say which one speech.cpp uses."""

import importlib
import subprocess
from types import SimpleNamespace

import pytest

OUTPUT = """Vulkan0    igpu  Intel(R) Iris(R) Xe Graphics, 17.1 GB, 16.3 GB free
Vulkan1    gpu   NVIDIA GeForce RTX 3060 Ti, 8.6 GB, 7.8 GB free
CPU        cpu   12th Gen Intel(R) Core(TM) i7-1255U, 34.2 GB, 19.3 GB free
"""


def settings():
    return importlib.import_module("models.speech_server.settings")


def runtime():
    return importlib.import_module("models.speech_server.runtime")


def profiles(device):
    return {"profiles": {"japanese": {"device": device}}}


def test_only_the_gpus_are_listed():
    assert runtime().parse_devices(OUTPUT) == [
        dict(name="Vulkan0", kind="igpu", label="Intel(R) Iris(R) Xe Graphics"),
        dict(name="Vulkan1", kind="gpu", label="NVIDIA GeForce RTX 3060 Ti"),
    ]


@pytest.mark.parametrize("text", ["", "no devices\n", "Vulkan0 igpu\n", "Vulkan999 gpu X, 1 GB, 1 GB free\n"])
def test_unexpected_output_lists_nothing(text):
    assert runtime().parse_devices(text) == []


def test_a_named_gpu_is_kept():
    value = settings().normalize_settings(profiles("Vulkan1"))
    assert value["profiles"]["japanese"]["device"] == "Vulkan1"


@pytest.mark.parametrize("device", ["auto", "cpu", "gpu"])
def test_the_general_choices_stay_valid(device):
    value = settings().normalize_settings(profiles(device))
    assert value["profiles"]["japanese"]["device"] == device


@pytest.mark.parametrize(
    "device", ["Vulkan", "Vulkan123", "vulkan1", "CUDA0", "--device", "Vulkan1 --port", "Vulkan1\n", ""]
)
def test_anything_else_is_refused(device):
    with pytest.raises(ValueError, match="speech_server_settings_invalid"):
        settings().normalize_settings(profiles(device))


def test_listing_asks_the_verified_binary(monkeypatch):
    module = runtime()
    calls = []
    monkeypatch.setattr(module, "bundled_binary", lambda: "C:/x/speech.exe")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=OUTPUT.encode(), stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert [row["name"] for row in module.list_gpus()] == ["Vulkan0", "Vulkan1"]
    [(args, kwargs)] = calls
    assert args == ["C:/x/speech.exe", "devices"]
    assert kwargs["timeout"] <= 15 and kwargs["stdin"] == subprocess.DEVNULL


def test_the_list_may_arrive_on_stderr(monkeypatch):
    module = runtime()
    monkeypatch.setattr(module, "bundled_binary", lambda: "speech")
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda args, **kw: SimpleNamespace(returncode=0, stdout=b"", stderr=OUTPUT.encode()),
    )
    assert len(module.list_gpus()) == 2


@pytest.mark.parametrize(
    "failure",
    [OSError("gone"), subprocess.TimeoutExpired("speech", 15), RuntimeError("speech_bundle_missing_or_invalid")],
)
def test_a_listing_that_fails_lists_nothing(monkeypatch, failure):
    module = runtime()
    monkeypatch.setattr(module, "bundled_binary", lambda: "speech")

    def run(args, **kwargs):
        raise failure

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.list_gpus() == []


def test_a_listing_that_exits_with_an_error_lists_nothing(monkeypatch):
    module = runtime()
    monkeypatch.setattr(module, "bundled_binary", lambda: "speech")
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda args, **kw: SimpleNamespace(returncode=1, stdout=OUTPUT.encode(), stderr=b""),
    )
    assert module.list_gpus() == []
