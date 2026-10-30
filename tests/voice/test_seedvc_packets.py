# SPDX-License-Identifier: GPL-3.0-only
import importlib
import io
import os
import struct

import pytest


def api():
    return importlib.import_module('integrations.seed_vc.packets')


def test_packet_keeps_pcm_and_timing_separate():
    stream = io.BytesIO()
    api().write_packet(stream, {'state': 'converted', 'input_ns': 123}, b'\1\0' * 4)
    stream.seek(0)
    info, pcm = api().read_packet(stream)
    assert info['state'] == 'converted' and info['input_ns'] == 123
    assert pcm == b'\1\0' * 4


@pytest.mark.parametrize('body', [b'', b'\1', struct.pack('<I', 10000),
    struct.pack('<I', 2) + b'{}', struct.pack('<I', 2) + b'[]'])
def test_eof_or_invalid_packet_is_a_failure_not_silence(body):
    with pytest.raises((EOFError, ValueError)):
        api().read_packet(io.BytesIO(body))


@pytest.mark.skipif(os.name != 'posix', reason='select on worker pipes requires POSIX file descriptors')
def test_partial_packet_from_stalled_worker_times_out():
    read, write = os.pipe()
    with os.fdopen(read, 'rb', buffering=0) as source, os.fdopen(write, 'wb', buffering=0) as sink:
        sink.write(struct.pack('<I', 40) + b'{')
        with pytest.raises(TimeoutError):
            api().read_packet(source, timeout=.03)
