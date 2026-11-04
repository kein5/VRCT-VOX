"""Memory-only transport owners shared by OSC lifecycle tests."""
from contextlib import contextmanager
from queue import Empty, Queue
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from models.osc import osc


class FakeServer:
    instances = []

    def __init__(self, address, dispatcher=None, **kwargs):
        self.address = address
        self.server_address = (address[0], 31000 + len(self.instances))
        self.dispatcher = dispatcher
        self.stopped = Event()
        self.entered = Event()
        self.packets = Queue()
        self.closed = False
        self.instances.append(self)

    def server_bind(self):
        pass

    def server_activate(self):
        pass

    def serve_forever(self, poll_interval=0.1):
        self.entered.set()
        while not self.stopped.is_set():
            try:
                packet = self.packets.get(timeout=0.01)
            except Empty:
                continue
            self.dispatcher.call_handlers_for_packet(packet, ("127.0.0.1", 9000))

    def shutdown(self):
        self.stopped.set()

    def server_close(self):
        self.closed = True


class FakeZeroconf:
    instances = []
    fail_register = False

    def __init__(self):
        self.registered = []
        self.unregistered = False
        self.closed = False
        self.instances.append(self)

    def register_service(self, service):
        self.registered.append(service)
        if self.fail_register:
            raise OSError("advertisement failed")

    def unregister_all_services(self):
        self.unregistered = True

    def close(self):
        self.closed = True


def local_service(name="VRChat-Client-test", ip=b"\x7f\x00\x00\x01"):
    return SimpleNamespace(name=name + "._oscjson._tcp.local.", type="_oscjson._tcp.local.",
                           addresses=[ip], port=32000)


def prepare_query(handler, client):
    handler.is_osc_query_enabled = True
    handler.browser = MagicMock()
    service = local_service()
    handler.browser.get_discovered_oscquery.return_value = [service]
    client.return_value.get_host_info.return_value = SimpleNamespace(
        name="VRChat-Client-test", osc_ip="127.0.0.1", osc_port=9000, osc_transport="UDP")
    return service


@contextmanager
def fake_transports():
    FakeServer.instances = []
    FakeZeroconf.instances = []
    FakeZeroconf.fail_register = False
    with (patch.object(osc.udp_client, "SimpleUDPClient") as client,
          patch.object(osc.osc_server, "BlockingOSCUDPServer", FakeServer),
          patch.object(osc, "HTTPServer", FakeServer),
          patch.object(osc, "Zeroconf", FakeZeroconf),
          patch.object(osc, "ServiceBrowser", MagicMock()),
          patch("tinyoscquery.queryservice.ServiceInfo", MagicMock())):
        yield client
