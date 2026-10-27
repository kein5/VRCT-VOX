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
