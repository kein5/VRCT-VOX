"""Packets use one receive thread; transports are memory-only."""
import threading
from pythonosc.osc_message_builder import OscMessageBuilder
from models.osc.osc import OSCHandler
from osc_fakes import fake_transports


def test_every_packet_is_handled_on_the_one_receive_thread():
    with fake_transports():
        handler = OSCHandler()
        seen = []
        done = threading.Event()

        def receive(address, value):
            seen.append(threading.get_ident())
            if len(seen) == 5:
                done.set()

        handler.setDictFilterAndTarget({"/mute": receive})
        handler.receiveOscParameters()
        try:
            for value in (True, False, True, False, True):
                builder = OscMessageBuilder(address="/mute")
                builder.add_arg(value)
                handler.osc_server.packets.put(builder.build().dgram)
            assert done.wait(1)
            assert len(set(seen)) == 1
            assert seen[0] != threading.get_ident()
        finally:
            handler.oscServerStop()
