"""Whether a local VRChat advertises OSC: read from discovery, with no sockets and no request to VRChat."""

import unittest
from unittest.mock import MagicMock, patch

import controller as controller_module
from model import Model
from models.osc.osc import OSCHandler
from osc_fakes import local_service


class VrchatPresenceTests(unittest.TestCase):
    def setUp(self):
        with patch("models.osc.osc.udp_client.SimpleUDPClient"):
            self.handler = OSCHandler()
        self.handler.is_osc_query_enabled = True
        self.handler.browser = MagicMock()

    def found(self, *services, answers=True):
        self.handler.browser.get_discovered_oscquery.return_value = list(services)
        with patch("models.osc.osc.OSCQueryClient") as client:
            if answers is True:
                client.return_value.get_host_info.return_value = MagicMock()
            elif answers is None:
                client.return_value.get_host_info.return_value = None
            else:
                client.return_value.get_host_info.side_effect = answers
            self.asked = client
            return self.handler.localVrchatPresence()

    def test_a_local_vrchat_service_that_answers_is_found(self):
        service = local_service()
        self.assertIs(self.found(service), True)
        self.asked.assert_called_once_with(service)
        self.handler.browser.ask_again.assert_not_called()

    def test_nothing_or_only_other_services_is_not_found_and_discovery_is_asked_again(self):
        self.assertIs(self.found(), False)
        self.handler.browser.ask_again.assert_called_once_with()
        # Another app's OSCQuery service, and a VRChat on another machine, are not this PC's VRChat.
        self.assertIs(self.found(local_service("VRCT:123"), local_service(ip=bytes([192, 168, 1, 5]))), False)
        self.asked.assert_not_called()
        self.assertIs(self.found(local_service("VRCT:123"), local_service()), True)
        # A malformed advertisement from something else does not hide VRChat or make the answer unknown.
        self.assertIs(self.found(local_service(ip=b"not an address")), False)
        self.assertIs(self.found(local_service(ip=b"not an address"), local_service()), True)

    def test_a_vrchat_that_was_closed_stays_in_discovery_but_is_not_found(self):
        for answers in (ConnectionError("refused"), None):
            with self.subTest(answers=answers):
                self.handler.browser.ask_again.reset_mock()
                self.assertIs(self.found(local_service(), answers=answers), False)
                self.handler.browser.ask_again.assert_called_once_with()

    def test_asking_again_failing_still_answers_not_found(self):
        self.handler.browser.ask_again.side_effect = OSError("network down")
        self.assertIs(self.found(), False)

    def test_unknown_when_this_pc_is_not_watched(self):
        self.handler.browser.get_discovered_oscquery.return_value = [local_service()]
        self.handler.is_osc_query_enabled = False  # the destination is another machine, or receiving failed
        self.assertIsNone(self.handler.localVrchatPresence())
        self.handler.is_osc_query_enabled = True
        self.handler._shutdown = True
        self.assertIsNone(self.handler.localVrchatPresence())
        self.handler._shutdown = False
        self.handler.browser = None
        self.assertIsNone(self.handler.localVrchatPresence())

    def test_a_failing_discovery_is_unknown_not_an_error(self):
        self.handler.browser.get_discovered_oscquery.side_effect = RuntimeError("zeroconf closed")
        self.assertIsNone(self.handler.localVrchatPresence())

    def test_the_endpoint_reports_the_three_states_in_words(self):
        model = object.__new__(Model)
        model.ensure_initialized = lambda: None
        model.osc_handler = MagicMock()
        for seen, word in ((True, "found"), (False, "not_found"), (None, "unknown")):
            model.osc_handler.localVrchatPresence.return_value = seen
            self.assertEqual(model.getVrchatOscPresence(), word)
            with patch.object(controller_module, "model", model):
                self.assertEqual(controller_module.Controller.getVrchatOscPresence(), {"status": 200, "result": word})


if __name__ == "__main__":
    unittest.main()
