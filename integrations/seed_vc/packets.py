# SPDX-License-Identifier: GPL-3.0-only
"""Bounded local PoC pipe framing; EOF never represents silent audio."""
import json
import struct
import select
import time


def _read(stream, size, deadline=None):
    chunks = bytearray()
    while len(chunks) < size:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
                raise TimeoutError('vc_worker_stalled')
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise EOFError('vc_worker_eof')
        chunks.extend(chunk)
    return bytes(chunks)


def write_packet(stream, info, pcm=b''):
    header = json.dumps({**info, 'pcm_bytes': len(pcm)}, separators=(',', ':')).encode()
    if len(header) > 4096 or len(pcm) > 192000 or len(pcm) % 2:
        raise ValueError('vc_packet_size')
    stream.write(struct.pack('<I', len(header)) + header + pcm)
    stream.flush()


def read_packet(stream, timeout=None):
    """For timed pipe reads the caller must supply an unbuffered binary stream."""
    deadline = None if timeout is None else time.monotonic() + timeout
    size, = struct.unpack('<I', _read(stream, 4, deadline))
    if not 1 <= size <= 4096:
        raise ValueError('vc_packet_header')
    header = json.loads(_read(stream, size, deadline))
    if not isinstance(header, dict):
        raise ValueError('vc_packet_header')
    length = header.get('pcm_bytes')
    if type(length) is not int or not 0 <= length <= 192000 or length % 2:
        raise ValueError('vc_packet_pcm')
    return header, _read(stream, length, deadline)
