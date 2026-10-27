"""Small test-only OSC observer; it forwards original datagrams exactly once."""
import re
import socket
from threading import Event, Thread

from pythonosc.osc_packet import OscPacket, ParseError


def marker_visible(text, marker):
    return len(re.findall(r"(?<![A-Za-z0-9_])" + re.escape(marker) + r"(?![A-Za-z0-9_])", text)) == 1


class OscForwarder:
    def __init__(self, target):
        self.target = target
        self.messages = []
        self.errors = []
        self.stop = Event()

    def __enter__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(("127.0.0.2", 0))
            self.socket.settimeout(.1)
            self.port = self.socket.getsockname()[1]
            self.thread = Thread(target=self._run, daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.socket.close()
            raise

    def _run(self):
        while not self.stop.is_set():
            try:
                data, _ = self.socket.recvfrom(65536)
            except TimeoutError:
                continue
            except OSError as error:
                self.errors.append(type(error).__name__)
                return
            try:
                messages = [{"address": item.message.address, "params": list(item.message.params)}
                            for item in OscPacket(data).messages]
                if not messages or any(m["address"] not in ("/chatbox/input", "/chatbox/typing") for m in messages):
                    self.errors.append("disallowed_address")
                    continue
                self.socket.sendto(data, self.target)
                self.messages.extend(messages)
            except (ParseError, OSError) as error:
                self.errors.append(type(error).__name__)

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(2)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("OSC relay thread did not stop")
