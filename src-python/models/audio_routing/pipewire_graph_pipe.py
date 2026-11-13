"""Forward shared observations to the isolated VC process, never its audio loop."""
import os
import select
import struct
from threading import Event, Thread
import time
import json

from . import pipewire_graph as graph

_HEADER = struct.Struct('!QdI')
_ENV = 'VRCT_PIPEWIRE_GRAPH_FD'


class GraphFeed:
    def __init__(self, names):
        self.names = frozenset(names)
        self.source = graph.graph_source()
        self.wake, self.stop = Event(), Event()
        self.user = self.source.subscribe(self.wake)
        self.read_fd = self.write_fd = None
        try:
            self.read_fd, self.write_fd = os.pipe()
            os.set_blocking(self.write_fd, False)
            self.thread = Thread(target=self._work, name='vrct-graph-feed', daemon=True)
            self.thread.start()
        except BaseException:
            for fd in (self.read_fd, self.write_fd):
                if fd is not None:
                    os.close(fd)
            self.user.close()
            raise

    def _work(self):
        sequence, wire = None, b''
        try:
            try:
                self.source.read()
            except graph.GraphUnavailable:
                pass
            while not self.stop.is_set():
                self.wake.clear()
                try:
                    value = self.source.read(wait=False)
                    if value.sequence != sequence:
                        # Preserve ALL matches (including duplicates) and Core
                        # cookies; the isolated reader runs the same validators.
                        data = [item for item in value.data
                                if item.get('type') == 'PipeWire:Interface:Core'
                                or (item.get('type') == 'PipeWire:Interface:Node'
                                    and item.get('info', {}).get('props', {}).get('node.name') in self.names)]
                        wire = json.dumps(data, separators=(',', ':')).encode()
                        sequence = value.sequence
                except graph.GraphUnavailable:
                    value, wire = self.source.observation(), b''
                    sequence = None
                pending = memoryview(_HEADER.pack(value.sequence, value.captured, len(wire)) + wire)
                # Finish this frame under backpressure, then select the latest
                # observation. Only the receiver decides whether it is fresh.
                while pending and not self.stop.is_set():
                    if select.select([], [self.write_fd], [], .02)[1]:
                        try:
                            pending = pending[os.write(self.write_fd, pending):]
                        except BlockingIOError:
                            continue
                self.wake.wait(graph.INTERVAL)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        finally:
            os.close(self.write_fd)
            self.user.close()

    def close_reader(self):
        if self.read_fd is not None:
            os.close(self.read_fd)
            self.read_fd = None

    def close(self):
        self.stop.set()
        self.wake.set()
        self.thread.join(graph.MAX_AGE + graph.INTERVAL + .1)
        self.close_reader()


class RemoteGraph(graph.GraphSource):
    def __init__(self, fd):
        super().__init__()
        self.fd = fd
        os.set_inheritable(fd, False)
        os.set_blocking(fd, False)
        # Drain startup traffic before a start request or the first graph read.
        self._thread = Thread(target=self._work, name='vrct-graph-receiver', daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self._thread = None
            os.close(self.fd)
            self.fd = None
            raise

    def _read(self, size):
        result = bytearray()
        deadline = time.monotonic() + graph.MAX_AGE
        while len(result) < size:
            if self._stop.is_set() or time.monotonic() >= deadline:
                raise graph.GraphUnavailable()
            if select.select([self.fd], [], [], .02)[0]:
                try:
                    part = os.read(self.fd, min(65536, size - len(result)))
                except BlockingIOError:
                    continue
                if not part:
                    raise graph.GraphUnavailable()
                result.extend(part)
        return bytes(result)

    def _work(self):
        previous = -1
        try:
            while not self._stop.is_set():
                sequence, captured, size = _HEADER.unpack(self._read(_HEADER.size))
                if sequence < previous or size > graph.MAX_BYTES:
                    raise graph.GraphUnavailable()
                previous = sequence
                wire = self._read(size)
                if not 0 <= self._clock() - captured < graph.MAX_AGE:
                    continue
                data = json.loads(wire) if wire else None
                if data is not None and (not isinstance(data, list)
                                         or any(not isinstance(item, dict) for item in data)):
                    raise graph.GraphUnavailable()
                with self._condition:
                    if not 0 <= self._clock() - captured < graph.MAX_AGE:
                        continue
                    self._observation = graph.Observation(sequence, captured, data)
                    self._condition.notify_all()
        except (OSError, ValueError, graph.GraphUnavailable):
            pass
        finally:
            self._publish(time.monotonic(), None)

    def close(self):
        super().close()
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def receive_from_parent():
    descriptor = os.environ.pop(_ENV, None)
    if descriptor is None:
        return None
    source = RemoteGraph(int(descriptor))
    graph._remote = source
    return source
