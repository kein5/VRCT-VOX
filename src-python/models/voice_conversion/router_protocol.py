"""Bounded metadata-only control for the isolated Linux VC transport."""
import json
import os
import re
import select
import time

LIMIT = 32768
BASE_STATE = dict(requested=False, active=False, pending=False, stopping=False,
                  conversion_verified=False, error=None, state='off', converted_blocks=0,
                  monitor_error=None)


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
            or value['state'] not in ('off', 'preparing', 'ready', 'converted', 'idle', 'failed', 'stopped')
            or (value['error'] is not None and (not isinstance(value['error'], str)
                or not re.fullmatch(r'(?:vc|asr_capture)_[a-z_]{1,56}', value['error'])))
            or (value['monitor_error'] is not None and (not isinstance(value['monitor_error'], str)
                or not re.fullmatch(r'monitor_[a-z_]{1,56}', value['monitor_error'])))):
        raise ValueError('vc_router_health_invalid')
    return {key: value[key] for key in BASE_STATE}


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
            if not select.select([self.stream], [], [], .02)[0]:
                continue
            part = os.read(self.stream.fileno(), min(4096, LIMIT-len(self.pending)))
            if not part:
                raise EOFError('vc_router_closed')
            self.pending.extend(part)
