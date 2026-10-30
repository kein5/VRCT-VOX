"""Real localhost UDP tests; never connect to a running VRChat instance."""
import socket
import time

import pytest
from pythonosc.osc_bundle_builder import IMMEDIATELY, OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder


def message(address, *params):
    builder = OscMessageBuilder(address=address)
    for value in params:
        builder.add_arg(value)
    return builder.build()


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail("relay did not finish within deadline")


@pytest.mark.parametrize("bundle", [False, True])
def test_one_byte_preserving_datagram_and_teardown(bundle):
    from native_chatbox import OscForwarder
    packet = message("/chatbox/input", "VRCTCHECKA", True, False)
    if bundle:
        builder = OscBundleBuilder(IMMEDIATELY)
        builder.add_content(message("/chatbox/typing", False))
        builder.add_content(packet)
        packet = builder.build()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sink.bind(("127.0.0.1", 0))
        sink.settimeout(.2)
        with OscForwarder(sink.getsockname()) as relay:
            port = relay.port
            sender.sendto(packet.dgram, ("127.0.0.2", port))
            assert sink.recvfrom(65536)[0] == packet.dgram
            with pytest.raises(TimeoutError):
                sink.recvfrom(65536)
            assert len(relay.messages) == (2 if bundle else 1)
            assert relay.messages[-1] == {"address": "/chatbox/input", "params": ["VRCTCHECKA", True, False]}
            assert relay.errors == []
        assert not relay.thread.is_alive()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.2", port))


@pytest.mark.parametrize("kind", ["voice", "bundle_with_voice", "invalid"])
def test_rejects_whole_disallowed_or_invalid_packet(kind):
    from native_chatbox import OscForwarder
    packet = message("/input/Voice", 1)
    if kind == "bundle_with_voice":
        builder = OscBundleBuilder(IMMEDIATELY)
        builder.add_content(message("/chatbox/input", "must not forward", True))
        builder.add_content(packet)
        packet = builder.build()
    data = b"not OSC" if kind == "invalid" else packet.dgram
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sink.bind(("127.0.0.1", 0))
        sink.settimeout(.2)
        with OscForwarder(sink.getsockname()) as relay:
            sender.sendto(data, ("127.0.0.2", relay.port))
            wait_for(lambda: relay.errors)
            with pytest.raises(TimeoutError):
                sink.recvfrom(65536)
            assert relay.messages == []


@pytest.mark.parametrize("text, expected", [
    ("こんにちは\nVRCTCHECKA\n", True), ("[VRCTCHECKA]", True),
    ("", False), ("VRCTCHECKB", False), ("XVRCTCHECKA", False),
    ("VRCTCHECKAX", False), ("VRCTCHECKA VRCTCHECKA", False),
])
def test_marker_requires_one_exact_token(text, expected):
    from native_chatbox import marker_visible
    assert marker_visible(text, "VRCTCHECKA") is expected


def pcm(values):
    import numpy as np
    return np.asarray(values, dtype="<i2").tobytes()


@pytest.mark.parametrize("kind", ["one", "overlap_50ms", "overlap_100ms", "sequential", "doubled_gain", "other_audio", "silence", "truncated", "partial_sample"])
def test_deterministic_source_rejects_duplicates_and_unexplained_audio(kind):
    import numpy as np
    from native_chatbox import compare_source_pcm
    rate = 8000
    ref = np.random.default_rng(42).integers(-10000, 10001, rate, dtype=np.int16).astype(np.float64)
    observed = np.pad(ref, (401, 8000))
    if kind.startswith("overlap"):
        delay = 400 if kind == "overlap_50ms" else 800
        mixed = np.zeros(len(ref) + delay)
        mixed[:len(ref)] += ref * .5
        mixed[delay:] += ref * .5
        observed = np.pad(mixed, (401, 8000))
    elif kind == "sequential":
        observed = np.concatenate((ref, np.zeros(400), ref))
    elif kind == "doubled_gain":
        observed *= 2
    elif kind == "other_audio":
        observed[-50:] = 100
    elif kind == "silence":
        observed *= 0
    elif kind == "truncated":
        observed = ref[:-1]
    data = pcm(observed) + (b"\x01" if kind == "partial_sample" else b"")
    result = compare_source_pcm(pcm(ref), data, rate)
    assert (result["verdict"] == "pass") is (kind == "one"), result
    if kind == "one":
        assert result["offset_samples"] == 401 and result["nonzero_outside"] is False


def test_deterministic_source_rejects_uninformative_reference():
    from native_chatbox import compare_source_pcm
    assert compare_source_pcm(bytes(16000), bytes(32000), 8000)["verdict"] != "pass"
