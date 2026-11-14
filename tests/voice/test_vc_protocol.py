"""The external worker cannot authorize stale, replayed or unconverted audio."""
import io
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
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


def test_a_model_of_a_format_the_engine_cannot_load_is_named():
    # Someone who brings their own RVC model learns that its version or sample rate is the
    # reason, instead of being told that the worker could not get ready.
    assert 'vc_engine_format_invalid' in p.WORKER_FAILURES


@pytest.mark.parametrize('code', sorted(p.WORKER_FAILURES))
def test_a_worker_can_say_why_it_cannot_become_ready(code):
    info, pcm = packet(p.failed_info(SESSION, code), b'')
    with pytest.raises(p.ProtocolError) as raised:
        p.require_ready(info, pcm, SESSION)
    assert str(raised.value) == code


@pytest.mark.parametrize('change', [
    lambda info: info.update(code='Traceback: C:\\Users\\name\\model.pth'),
    lambda info: info.update(code='vc_worker_eof'),
    lambda info: info.update(session='b' * 32),
    lambda info: info.update(extra='unexpected'),
    lambda info: info.update(protocol=2),
])
def test_only_a_listed_reason_for_this_session_is_passed_on(change):
    # Free text from a worker (a traceback, a path) never reaches the status or the notice.
    info, pcm = packet(p.failed_info(SESSION, 'vc_gpu_unavailable'), b'')
    change(info)
    with pytest.raises(p.ProtocolError, match='^vc_ready_invalid$'):
        p.require_ready(info, pcm, SESSION)
    with pytest.raises(p.ProtocolError, match='^vc_ready_invalid$'):
        p.failed_info(SESSION, 'not_listed')


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
    for clock in (STAMP - 1, STAMP + p.BLOCK_NS + p.MAX_AGE_NS + 1):
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


@pytest.mark.skipif(os.name != 'posix', reason='select on worker pipes requires POSIX file descriptors')
@pytest.mark.parametrize('part', ['prefix', 'header', 'pcm', 'short', 'full', 'consecutive'])
def test_worker_buffered_stdin_respects_packet_deadline_without_read_ahead(part):
    """Use the interpreter/stdin setup of both live workers, keeping stdin open."""
    short = p.encode_packet(p.ready_info(SESSION))
    full = p.encode_packet(p.input_info(SESSION, 0, STAMP), RAW)
    body = {'prefix': full[:1], 'header': full[:p.PREFIX.size + 1],
            'pcm': full[:-1], 'short': short, 'full': full,
            'consecutive': short * 2}[part]
    script = '''
import io, sys
sys.path.insert(0, sys.argv[1])
from models.voice_conversion import protocol as p
assert isinstance(sys.stdin.buffer, io.BufferedReader)
print('ready', flush=True)
try:
    for _ in range(int(sys.argv[2])):
        info, pcm = p.read_packet(sys.stdin.buffer, timeout=.15)
        assert info['pcm_bytes'] == len(pcm)
except p.ProtocolError as exc:
    print(str(exc), flush=True)
else:
    print('complete', flush=True)
'''
    process = subprocess.Popen(
        [sys.executable, '-u', '-c', script, str(Path(p.__file__).resolve().parents[2]),
         '2' if part == 'consecutive' else '1'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    try:
        assert select.select([process.stdout], [], [], 3)[0], 'worker did not start'
        assert process.stdout.readline() == b'ready\n'
        process.stdin.write(body)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pytest.fail('buffered worker stdin blocked past the packet deadline')
        assert process.returncode == 0, process.stderr.read()
        expected = b'vc_worker_stalled\n' if part in ('prefix', 'header', 'pcm') else b'complete\n'
        assert process.stdout.read() == expected
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=2)
