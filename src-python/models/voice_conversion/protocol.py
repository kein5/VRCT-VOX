"""Fixed live-VC pipe contract, independent of the optional inference runtime.

Timed reads require unbuffered binary pipes. This is not a UI/JSON IPC endpoint.
An engine's checked conversion state is evidence about its execution, not an
acoustic guarantee that no arbitrary input resembles an output.
"""
import json
import re
import select
import struct
import time

RATE = 48000
FRAMES = 3840
PCM_BYTES = FRAMES * 2
BLOCK_NS = 80_000_000
MAX_AGE_NS = 160_000_000
PREFIX = struct.Struct('<4sI')


class ProtocolError(RuntimeError):
    """Fixed diagnostic codes without worker output or private paths."""


def _session(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ProtocolError('vc_session_invalid')
    return value


def _same(actual, expected):
    return (isinstance(actual, dict) and actual.keys() == expected.keys()
            and all(type(actual[k]) is type(v) and actual[k] == v for k, v in expected.items()))


def ready_info(session):
    return dict(type='ready', protocol=1, session=_session(session), engine='seed-vc',
                profile='low', rate=RATE, channels=1, block_frames=FRAMES)


def input_info(session, sequence, start_ns):
    if (type(sequence) is not int or not 0 <= sequence < 2**63
            or type(start_ns) is not int or not 0 < start_ns < 2**63):
        raise ProtocolError('vc_input_invalid')
    return dict(type='input', session=_session(session), sequence=sequence,
                start_ns=start_ns, end_ns=start_ns + BLOCK_NS, rate=RATE, channels=1)


def require_ready(info, pcm, session):
    if pcm or not _same(info, dict(ready_info(session), pcm_bytes=0)):
        raise ProtocolError('vc_ready_invalid')


def require_fresh(end_ns, now_ns):
    if (type(end_ns) is not int or type(now_ns) is not int or not 0 < end_ns <= now_ns
            or now_ns - end_ns > MAX_AGE_NS):
        raise ProtocolError('vc_block_expired')


def require_input(info, pcm, session, sequence, now_ns):
    if not isinstance(info, dict):
        raise ProtocolError('vc_input_invalid')
    expected = dict(input_info(session, sequence, info.get('start_ns')), pcm_bytes=PCM_BYTES)
    if len(pcm) != PCM_BYTES or not _same(info, expected):
        raise ProtocolError('vc_input_invalid')
    require_fresh(expected['end_ns'], now_ns)


def require_output(info, pcm, source, original, now_ns):
    require_input(source, original, source['session'], source['sequence'], now_ns)
    state = info.get('state') if isinstance(info, dict) else None
    if (state not in ('converted', 'vad_silence') or len(pcm) != PCM_BYTES
            or not _same(info, dict(source, type='output', state=state))):
        raise ProtocolError('vc_output_invalid')
    if state == 'vad_silence' and any(pcm):
        raise ProtocolError('vc_silence_invalid')
    if any(original) and pcm == original:
        raise ProtocolError('vc_passthrough_forbidden')
    return state


def encode_packet(info, pcm=b''):
    if not isinstance(info, dict) or type(pcm) is not bytes or len(pcm) > PCM_BYTES or len(pcm) % 2:
        raise ProtocolError('vc_packet_invalid')
    try:
        header = json.dumps(dict(info, pcm_bytes=len(pcm)), separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ProtocolError('vc_packet_invalid') from None
    if len(header) > 2048:
        raise ProtocolError('vc_packet_invalid')
    return PREFIX.pack(b'VVC1', len(header)) + header + pcm


def _object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError('duplicate field')
    return value


def read_packet(stream, *, timeout=1, check=lambda: None):
    deadline = None if timeout is None else time.monotonic() + timeout

    def read_exact(size):
        result = bytearray()
        while len(result) < size:
            check()
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProtocolError('vc_worker_stalled')
                if not select.select([stream], [], [], min(.02, remaining))[0]:
                    continue
            check()
            chunk = stream.read(size - len(result))
            if not chunk:
                raise ProtocolError('vc_worker_eof')
            result.extend(chunk)
        check()
        return bytes(result)

    magic, length = PREFIX.unpack(read_exact(PREFIX.size))
    if magic != b'VVC1' or not 1 <= length <= 2048:
        raise ProtocolError('vc_packet_invalid')
    try:
        info = json.loads(read_exact(length), object_pairs_hook=_object)
    except (ValueError, UnicodeError):
        raise ProtocolError('vc_packet_invalid') from None
    if not isinstance(info, dict):
        raise ProtocolError('vc_packet_invalid')
    size = info.get('pcm_bytes')
    if type(size) is not int or not 0 <= size <= PCM_BYTES or size % 2:
        raise ProtocolError('vc_packet_invalid')
    return info, read_exact(size)
