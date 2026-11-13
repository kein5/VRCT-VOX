"""The receive thread captures its own server and polls frequently."""
import unittest
from unittest.mock import MagicMock
from models.osc.osc import OSCHandler


class OscServerServePollIntervalTests(unittest.TestCase):
    def test_serve_uses_captured_server(self):
        handler = OSCHandler.__new__(OSCHandler)
        handler.osc_server = MagicMock()
        owned = MagicMock()
        handler.oscServerServe(owned)
        owned.serve_forever.assert_called_once_with(0.1)
        handler.osc_server.serve_forever.assert_not_called()
