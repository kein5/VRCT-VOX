"""OSCQuery mute reads use VRChat's service and accept only boolean values; no sockets."""

import unittest
from unittest.mock import MagicMock, patch

from models.osc.osc import OSCHandler
from osc_fakes import prepare_query


class OscQueryMuteValueTests(unittest.TestCase):
    def setUp(self):
        with patch("models.osc.osc.udp_client.SimpleUDPClient"):
            self.handler = OSCHandler()
        self.client_patch = patch("models.osc.osc.OSCQueryClient")
        self.client = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.service = prepare_query(self.handler, self.client)

    def test_queries_vrchat_client_and_muteself_with_existing_client(self):
        with patch("models.osc.osc.OSCQueryClient", self.client) as client:
            client.return_value.query_node.return_value = MagicMock(value=[False])
            self.assertIs(self.handler.getOSCParameterMuteSelf(), False)
        client.assert_called_once_with(self.service)
        client.return_value.query_node.assert_called_once_with("/avatar/parameters/MuteSelf")

    def test_only_explicit_booleans_are_mute_values(self):
        with patch("models.osc.osc.OSCQueryClient", self.client) as client:
            for value in (True, False, None, [], 0, 1, "false", "true"):
                with self.subTest(value=value):
                    client.return_value.query_node.return_value = MagicMock(value=[value])
                    expected = value if type(value) is bool else None
                    self.assertIs(self.handler.getOSCParameterMuteSelf(), expected)

    def test_absent_service_node_or_value_returns_none(self):
        with patch("models.osc.osc.OSCQueryClient", self.client) as client:
            for node in (None, MagicMock(value=None), MagicMock(value=[])):
                with self.subTest(node=node):
                    client.return_value.query_node.return_value = node
                    self.assertIsNone(self.handler.getOSCParameterMuteSelf())
            client.reset_mock()
            self.handler.browser.get_discovered_oscquery.return_value = []
            self.assertIsNone(self.handler.getOSCParameterMuteSelf())
            client.assert_not_called()

    def test_unreachable_service_returns_none_and_logs_without_exception_details(self):
        with (patch("models.osc.osc.OSCQueryClient", self.client) as client,
              patch("models.osc.osc.printLog") as log):
            client.return_value.query_node.side_effect = OSError("private service details")
            self.assertIsNone(self.handler.getOSCParameterMuteSelf())
        log.assert_called_once_with(
            "OSCQuery: parameter query failed", {"address": "/avatar/parameters/MuteSelf"}
        )
        self.assertIsNotNone(self.handler.browser)  # lifecycle owner closes discovery, never a query

    def test_disabled_oscquery_does_not_create_a_client(self):
        self.handler.is_osc_query_enabled = False
        with patch("models.osc.osc.OSCQueryClient", self.client) as client:
            self.assertIsNone(self.handler.getOSCParameterMuteSelf())
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
