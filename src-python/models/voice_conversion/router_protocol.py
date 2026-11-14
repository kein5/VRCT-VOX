"""Bounded control for the isolated VC transport, and speech for it to convert (ADR-007)."""
import base64
import json
import os
import re
import time

from models.owned_child import wait_readable

LIMIT = 32768
BASE_STATE = dict(requested=False, active=False, pending=False, stopping=False,
                  conversion_verified=False, error=None, state='off', converted_blocks=0,
                  monitor_error=None, monitor_revision=0, round_trip_ms=None)


def encode(value):
    data = json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
    if len(data) > LIMIT:
        raise ValueError('vc_router_frame_invalid')
    return data


def validate_health(value):
    if not isinstance(value, dict) or set(value) != set(BASE_STATE) | {'kind', 'sent_ns'}:
        raise ValueError('vc_router_health_invalid')
    if (value['kind'] != 'health' or type(value['sent_ns']) is not int
            or not 0 <= time.monotonic_ns()-value['sent_ns'] <= 1_000_000_000
            or any(type(value[key]) is not bool for key in BASE_STATE if type(BASE_STATE[key]) is bool)
            or type(value['converted_blocks']) is not int or not 0 <= value['converted_blocks'] < 2**63
            or type(value['monitor_revision']) is not int or not 0 <= value['monitor_revision'] < 2**63
            or (value['round_trip_ms'] is not None and (type(value['round_trip_ms']) is not int
                or not 0 <= value['round_trip_ms'] <= 60_000))
            or value['state'] not in ('off', 'preparing', 'ready', 'converted', 'idle', 'failed', 'stopped')
            or (value['error'] is not None and (not isinstance(value['error'], str)
                or not re.fullmatch(r'(?:vc|asr_capture)_[a-z_]{1,56}', value['error'])))
            or (value['monitor_error'] is not None and (not isinstance(value['monitor_error'], str)
                or not re.fullmatch(r'monitor_[a-z_]{1,56}', value['monitor_error'])))):
        raise ValueError('vc_router_health_invalid')
    return {key: value[key] for key in BASE_STATE}


def validate_monitor_control(value):
    if (not isinstance(value, dict) or set(value) - {'suppressed'} != {'kind', 'muted', 'revision'}
            or value['kind'] != 'monitor_mute' or type(value['muted']) is not bool
            or type(value.get('suppressed', False)) is not bool
            or type(value['revision']) is not int or not 0 <= value['revision'] < 2**63):
        raise ValueError('vc_router_request_invalid')
    return value['muted'], value['revision']


# Speech spoken through the conversion (ADR-007). Audio on this pipe, as base64 in a
# bounded frame: at most one 80 ms block of 48 kHz mono s16le. Never logged.
SPEECH_KINDS = ('speech', 'speech_end', 'speech_cancel')


def speech_frame(pcm):
    if type(pcm) is not bytes or not pcm or len(pcm) % 2 or len(pcm) > 7680:
        raise ValueError('vc_router_request_invalid')
    return encode(dict(kind='speech', pcm=base64.b64encode(pcm).decode('ascii')))


def control_kind(value):
    """'monitor_mute' or one of SPEECH_KINDS, for a frame from the owner; else invalid."""
    kind = value.get('kind') if isinstance(value, dict) else None
    if kind == 'monitor_mute':
        validate_monitor_control(value)
        return kind
    if kind in ('speech_end', 'speech_cancel') and set(value) == {'kind'}:
        return kind
    if kind == 'speech' and set(value) == {'kind', 'pcm'} and isinstance(value['pcm'], str):
        return kind
    raise ValueError('vc_router_request_invalid')


def speech_pcm(value):
    try:
        pcm = base64.b64decode(value['pcm'], validate=True)
    except (ValueError, TypeError):
        raise ValueError('vc_router_request_invalid') from None
    if not pcm or len(pcm) % 2 or len(pcm) > 7680:
        raise ValueError('vc_router_request_invalid')
    return pcm


class Reader:
    def __init__(self, stream):
        self.stream, self.pending = stream, bytearray()

    def read(self, *, timeout, check=lambda: None):
        deadline = time.monotonic() + timeout
        while True:
            check()
            if b'\n' in self.pending:
                line, _, tail = self.pending.partition(b'\n')
                self.pending = bytearray(tail)
                return json.loads(line)
            if len(self.pending) >= LIMIT:
                raise ValueError('vc_router_frame_invalid')
            if time.monotonic() >= deadline:
                raise TimeoutError('vc_router_timeout')
            if not wait_readable(self.stream, .02):
                continue
            part = os.read(self.stream.fileno(), min(4096, LIMIT-len(self.pending)))
            if not part:
                raise EOFError('vc_router_closed')
            self.pending.extend(part)
