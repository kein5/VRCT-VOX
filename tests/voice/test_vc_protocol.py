"""The external worker cannot authorize stale, replayed or unconverted audio."""
import io
import json
import os
import struct
from threading import Event, Thread
import time

import pytest

from models.voice_conversion import protocol as p

SESSION = 'a' * 32
STAMP = 1_000_000_000
NOW = STAMP + 100_000_000
RAW = b'\1\0' * 3840
CONVERTED = b'\2\0' * 3840


def packet(info, pcm):
    return p.read_packet(io.BytesIO(p.encode_packet(info, pcm)), timeout=None)


def input_packet():
    return packet(p.input_info(SESSION, 0, STAMP), RAW)


def output_packet(state='converted'):
    info, _ = input_packet()
    return {**info, 'type': 'output', 'state': state}, CONVERTED


def test_explicit_ready_and_one_correlated_converted_block():
    info, pcm = packet(p.ready_info(SESSION), b'')
    p.require_ready(info, pcm, SESSION)
    source, raw = input_packet()
    p.require_input(source, raw, SESSION, 0, NOW)
    result, converted = output_packet()
    assert p.require_output(result, converted, source, raw, NOW) == 'converted'


@pytest.mark.parametrize('key,value', [('session', 'b' * 32), ('rate', 16000),
    ('channels', 2), ('engine', 'unverified'), ('profile', 'baseline'), ('protocol', True)])
def test_ready_must_match_fixed_contract(key, value):
    info, pcm = packet(p.ready_info(SESSION), b'')
    info[key] = value
    with pytest.raises(p.ProtocolError):
        p.require_ready(info, pcm, SESSION)


@pytest.mark.parametrize('key,value', [('session', 'b' * 32), ('sequence', 1),
    ('sequence', False), ('rate', 44100), ('channels', 2), ('start_ns', True),
    ('end_ns', NOW + 1), ('pcm_bytes', True), ('state', 'bypass'), ('extra', 'unexpected')])
def test_mismatched_output_cannot_reach_audio(key, value):
    source, raw = input_packet()
    info, pcm = output_packet()
    info[key] = value
    with pytest.raises(p.ProtocolError):
        p.require_output(info, pcm, source, raw, NOW)


def test_expired_or_future_blocks_and_original_passthrough_are_rejected():
    source, raw = input_packet()
    info, pcm = output_packet()
    for clock in (STAMP - 1, STAMP + 240_000_001):
        with pytest.raises(p.ProtocolError):
            p.require_input(source, raw, SESSION, 0, clock)
        with pytest.raises(p.ProtocolError):
            p.require_output(info, pcm, source, raw, clock)
    with pytest.raises(p.ProtocolError, match='passthrough'):
        p.require_output(info, raw, source, raw, NOW)


def test_vad_silence_is_zero_and_not_conversion_proof():
    source, raw = input_packet()
    info, pcm = output_packet('vad_silence')
    with pytest.raises(p.ProtocolError):
        p.require_output(info, pcm, source, raw, NOW)
    assert p.require_output(info, b'\0' * len(raw), source, raw, NOW) == 'vad_silence'


@pytest.mark.parametrize('body', [b'', b'VVC1', b'BAD!' + struct.pack('<I', 3),
    b'VVC1' + struct.pack('<I', 2049),
    b'VVC1' + struct.pack('<I', 2) + b'[]',
    b'VVC1' + struct.pack('<I', 2) + b'{}'])
def test_invalid_framing_or_eof_is_never_silence(body):
    with pytest.raises(p.ProtocolError):
        p.read_packet(io.BytesIO(body), timeout=None)


def test_declared_pcm_is_bounded_before_reading_payload():
    data = json.dumps({'pcm_bytes': 7682}).encode()
    with pytest.raises(p.ProtocolError):
        p.read_packet(io.BytesIO(b'VVC1' + struct.pack('<I', len(data)) + data), timeout=None)


@pytest.mark.skipif(os.name != 'posix', reason='select on worker pipes requires POSIX file descriptors')
def test_partial_pipe_packet_times_out_and_can_be_cancelled():
    read, write = os.pipe()
    with os.fdopen(read, 'rb', buffering=0) as source, os.fdopen(write, 'wb', buffering=0) as sink:
        sink.write(b'VVC1')
        before = time.monotonic()
        with pytest.raises(p.ProtocolError, match='stalled'):
            p.read_packet(source, timeout=.04)
        assert time.monotonic() - before < .5
        cancelled = Event()
        def cancel():
            if cancelled.is_set():
                raise RuntimeError('stopped')
        thread = Thread(target=lambda: (time.sleep(.03), cancelled.set()))
        thread.start()
        try:
            with pytest.raises(RuntimeError, match='stopped'):
                p.read_packet(source, timeout=60, check=cancel)
        finally:
            thread.join()
