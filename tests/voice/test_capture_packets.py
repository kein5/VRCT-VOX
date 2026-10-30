import importlib
import struct

import pytest

HEADER = struct.Struct("<4sIQQII")
NOW = 10_000_000_000


def decoder():
    return importlib.import_module(
        "models.transcription.capture_packets"
    ).CapturePackets()


def packet(seq=0, frames=480, stamp=NOW - 20_000_000, **kwargs):
    fields = dict(
        magic=b"VCA1",
        sequence=seq,
        cycle=NOW - 1_000_000,
        first=stamp,
        rate=48000,
        frames=frames,
    )
    fields.update(kwargs)
    return HEADER.pack(*fields.values()) + b"\1\0" * frames


def test_partial_reads_assemble_20ms_preserving_first_sample_bound():
    d = decoder()
    output = []
    wire = packet() + packet(1, stamp=NOW - 10_000_000)
    for offset in range(0, len(wire), 73):
        output.extend(d.feed(wire[offset : offset + 73], NOW))
    assert len(output) == 1
    assert output[0].captured_ns == NOW - 20_000_000
    assert output[0].audio.pcm == b"\1\0" * 960
    assert output[0].audio.sample_rate == 48000


@pytest.mark.parametrize(
    "fields",
    [
        {"magic": b"bad!"},
        {"sequence": 1},
        {"rate": 24000},
        {"frames": 0},
        {"frames": 961},
        {"first": NOW + 1},
        {"first": NOW - 251_000_000},
        {"cycle": NOW + 1},
        {"first": 0},
    ],
)
def test_invalid_header_closes_decoder(fields):
    d = decoder()
    wire = packet(**fields)
    with pytest.raises(ValueError):
        d.feed(wire, NOW)
    with pytest.raises(ValueError):
        d.feed(packet(), NOW)


def test_queued_partial_payload_expires_without_retimestamping():
    d = decoder()
    wire = packet(frames=960)
    assert d.feed(wire[:-2], NOW) == ()
    with pytest.raises(ValueError, match="stale"):
        d.feed(wire[-2:], NOW + 300_000_000)


def test_sequence_gap_and_clock_regression_rejected():
    for later in (packet(2), packet(1, stamp=NOW - 30_000_000)):
        d = decoder()
        assert d.feed(packet(), NOW) == ()
        with pytest.raises(ValueError):
            d.feed(later, NOW)


def test_close_discards_incomplete_frame_and_large_read_rejected():
    d = decoder()
    d.feed(packet(), NOW)
    d.close()
    with pytest.raises(ValueError):
        d.feed(packet(1), NOW)
    with pytest.raises(ValueError):
        decoder().feed(b"x" * 8193, NOW)
