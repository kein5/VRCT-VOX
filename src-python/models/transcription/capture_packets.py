"""Bounded native-capture framing; preserve PipeWire's reported timestamp bound."""
from collections import deque
import struct

from models.voice_events import AudioFrame
from .realtime_audio import CapturedAudio

HEADER = struct.Struct('<4sIQQII')


class CapturePackets:
    def __init__(self):
        self._wire = bytearray()
        self._pieces = deque()
        self._bytes = self._sequence = 0
        self._last_stamp = self._last_cycle = 0
        self.closed = False

    def close(self):
        self.closed = True
        self._wire.clear()
        self._pieces.clear()
        self._bytes = 0

    def _fail(self, code):
        self.close()
        raise ValueError(code)

    def feed(self, data, now_ns):
        if self.closed:
            raise ValueError('capture_decoder_closed')
        if type(data) is not bytes or len(data) > 8192 or type(now_ns) is not int:
            self._fail('invalid_capture_packet')
        self._wire.extend(data)
        result = []
        while len(self._wire) >= HEADER.size:
            magic, sequence, cycle, stamp, rate, frames = HEADER.unpack_from(self._wire)
            if (magic != b'VCA1' or sequence != self._sequence or rate != 48000
                    or not 1 <= frames <= 960 or not 0 < stamp <= cycle <= now_ns
                    or stamp <= self._last_stamp or cycle < self._last_cycle):
                self._fail('invalid_capture_packet')
            if now_ns - stamp > 250_000_000:
                self._fail('stale_capture_packet')
            size = HEADER.size + frames * 2
            if len(self._wire) < size:
                break
            pcm = bytes(self._wire[HEADER.size:size])
            del self._wire[:size]
            self._sequence += 1
            self._last_stamp, self._last_cycle = stamp, cycle
            self._pieces.append((pcm, stamp))
            self._bytes += len(pcm)
            while self._bytes >= 1920:
                first = self._pieces[0][1]
                if now_ns - first > 250_000_000:
                    self._fail('stale_capture_packet')
                output = bytearray()
                while len(output) < 1920:
                    piece, timestamp = self._pieces.popleft()
                    take = min(1920 - len(output), len(piece))
                    output.extend(piece[:take])
                    if take < len(piece):
                        self._pieces.appendleft((piece[take:], timestamp + (take // 2) * 1_000_000_000 // 48000))
                self._bytes -= 1920
                result.append(CapturedAudio(AudioFrame(bytes(output), 48000), first))
        return tuple(result)
