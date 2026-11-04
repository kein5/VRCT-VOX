"""WebSocket サーバーが bind できなかったら、有効にしたと返さない。

空きポートの確認 (isAvailableWebSocketServer) は一時的に bind して閉じるだけなので、
そのあと実際に bind するまでの間にほかのプロセスがポートを取ることがある。以前は
bind の失敗が別スレッドの中で起き、設定は有効のまま、生存フラグも立ったままだった。
"""

import socket
import threading
import unittest
from unittest.mock import patch

import pytest

from config import config
from controller import Controller
from errors import ErrorCode
from model import Model
from models.websocket.websocket_server import WebSocketServer


def _occupied_port() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


@pytest.fixture
def loopback_socket_permission():
    """These integration tests require TCP on 127.0.0.1, ephemeral port 0."""
    try:
        sock, _ = _occupied_port()
    except PermissionError:
        pytest.skip("sandbox denies localhost TCP sockets (127.0.0.1:0)")
    else:
        sock.close()


@pytest.mark.usefixtures("loopback_socket_permission")
class WebSocketServerStartTests(unittest.TestCase):
    def test_start_raises_when_the_port_is_taken(self) -> None:
        sock, port = _occupied_port()
        self.addCleanup(sock.close)
        server = WebSocketServer(host="127.0.0.1", port=port, token="test-token")

        with self.assertRaises(OSError):
            server.start(timeout=5.0)
        self.assertFalse(server.is_running)

    def test_start_returns_once_the_server_is_listening(self) -> None:
        server = WebSocketServer(host="127.0.0.1", port=0, token="test-token")
        self.addCleanup(server.stop)

        server.start(timeout=5.0)

        self.assertTrue(server.is_running)


@pytest.mark.usefixtures("loopback_socket_permission")
class ModelStartWebSocketServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = object.__new__(Model)
        self.model._inited = True
        self.model._websocket_lifecycle_lock = threading.Lock()
        self.model.websocket_server = None

    def tearDown(self) -> None:
        self.model.stopWebSocketServer()

    def test_returns_false_and_stays_down_when_bind_fails(self) -> None:
        sock, port = _occupied_port()
        self.addCleanup(sock.close)

        with patch("model.errorLogging"):
            started = self.model.startWebSocketServer("127.0.0.1", port)

        self.assertFalse(started)
        self.assertFalse(self.model.checkWebSocketServerAlive())

    def test_returns_true_when_the_server_is_listening(self) -> None:
        self.assertTrue(self.model.startWebSocketServer("127.0.0.1", 0))
        self.assertTrue(self.model.checkWebSocketServerAlive())


class ControllerEnableWebSocketServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = config.WEBSOCKET_SERVER
        config.WEBSOCKET_SERVER = False

    def tearDown(self) -> None:
        config.WEBSOCKET_SERVER = self._original

    @patch("controller.isAvailableWebSocketServer", return_value=True)
    @patch("controller.model")
    def test_enable_reports_an_error_when_the_server_did_not_start(self, mock_model, _) -> None:
        mock_model.startWebSocketServer.return_value = False

        response = Controller.setEnableWebSocketServer()

        self.assertEqual(response["status"], 400)
        self.assertEqual(response["result"]["error_code"], ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE.value)
        self.assertFalse(config.WEBSOCKET_SERVER)

    @patch("controller.isAvailableWebSocketServer", return_value=True)
    @patch("controller.model")
    def test_port_change_restores_the_old_port_when_the_new_one_fails(self, mock_model, _) -> None:
        original_port = config.WEBSOCKET_PORT
        self.addCleanup(setattr, config, "WEBSOCKET_PORT", original_port)
        mock_model.checkWebSocketServerAlive.return_value = True
        mock_model.startWebSocketServer.side_effect = [False, True]

        response = Controller.setWebSocketPort(original_port + 1)

        self.assertEqual(response["status"], 400)
        self.assertEqual(response["result"]["error_code"], ErrorCode.WEBSOCKET_PORT_UNAVAILABLE.value)
        self.assertEqual(config.WEBSOCKET_PORT, original_port)
        self.assertEqual(
            mock_model.startWebSocketServer.call_args_list[-1].args,
            (config.WEBSOCKET_HOST, original_port),
        )

    @patch("controller.isAvailableWebSocketServer", return_value=True)
    @patch("controller.model")
    def test_failed_restore_turns_websocket_and_obs_off(self, mock_model, _) -> None:
        # 止めている間に元のポートも取られた。有効のまま何も配信しない状態にしない
        original = (config.WEBSOCKET_HOST, config.WEBSOCKET_PORT, config.OBS_BROWSER_SOURCE)
        self.addCleanup(lambda: (setattr(config, "WEBSOCKET_HOST", original[0]),
                                 setattr(config, "WEBSOCKET_PORT", original[1]),
                                 setattr(config, "OBS_BROWSER_SOURCE", original[2])))
        config.WEBSOCKET_SERVER = True
        config.OBS_BROWSER_SOURCE = True
        mock_model.checkWebSocketServerAlive.return_value = True
        for change in (lambda: Controller.setWebSocketPort(original[1] + 1),
                       lambda: Controller.setWebSocketHost("127.0.0.2")):
            with self.subTest(change=change):
                config.WEBSOCKET_SERVER = True
                config.OBS_BROWSER_SOURCE = True
                mock_model.startWebSocketServer.side_effect = [False, False]

                response = change()

                self.assertEqual(response["status"], 400)
                self.assertFalse(config.WEBSOCKET_SERVER)
                self.assertFalse(config.OBS_BROWSER_SOURCE)
                mock_model.stopObsBrowserSourceServer.assert_called()


if __name__ == "__main__":
    unittest.main()
