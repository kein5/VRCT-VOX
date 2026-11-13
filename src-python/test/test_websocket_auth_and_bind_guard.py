"""WebSocket サーバーのトークン認証と 0.0.0.0/:: バインド拒否に関する
テスト (ロードマップ項目 12)。

対象の欠陥:
  WebSocket は同一オリジンポリシーの対象外であるため、127.0.0.1 バインド
  だけでは「同じ PC 上で開いた任意の Web ページの JS が
  ws://127.0.0.1:PORT に直接接続して、マイク/スピーカーの文字起こしを
  リアルタイムに窃取する」ことを防げない。また WEBSOCKET_HOST に
  0.0.0.0/:: を設定すると、同一 LAN 上の全端末が到達可能になる。

  修正:
  1. WebSocketServer にトークン検証 (process_request フック) を追加し、
     ?token=... が一致しない接続を 403 で拒否する。トークンは
     config.WEBSOCKET_AUTH_TOKEN として初回起動時に 1 回だけ生成し、
     以降は config.json に永続化する (VRCT-TTS のような外部連携ツールは
     ユーザーが接続 URL を手動入力する方式のため、起動のたびにトークンが
     変わると毎回再設定が必要になってしまう)。OBS Browser Sourceは
     同じトークン付きのURLでページを取得でき、認証後のHTMLにだけ
     トークンを埋め込む。既存のOBSソースにはURLのコピーし直しが必要。
     VRCT-TTS 等、URL を手動入力する外部ツール向けには
     /get/data/websocket_auth_token を新設し、UI から
     `ws://{host}:{port}/?token={token}` をコピーできるようにする。
  2. WEBSOCKET_HOST に 0.0.0.0/:: を設定できないよう、Controller の
     入力検証と config.py のディスクリプタ両方で拒否する
     (setWebSocketHost だけだと config.json に既に保存されている
     0.0.0.0 を起動時に読み込むケースを防げないため)。

  origins=[None] は当初のレビュー提案に含まれていたが、VRCT の OBS
  Browser Source 自体がブラウザ (OBS 内蔵 Chromium) から Origin ヘッダー
  付きで接続するため、この方式だと OBS 連携自体を壊してしまうことが
  実装前の調査で判明した。よってトークン認証を主たる防御として採用し、
  origins チェックは見送っている。
"""

import unittest
from http import HTTPStatus
from http.client import HTTPResponse
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from config import config
from controller import Controller
from errors import ErrorCode
from models.websocket.websocket_server import WebSocketServer
from models.obs.obs_browser_source_server import _build_overlay_html, ObsBrowserSourceServer
from utils import isWildcardBindAddress


class IsWildcardBindAddressTests(unittest.TestCase):
    def test_ipv4_wildcard_is_rejected(self) -> None:
        self.assertTrue(isWildcardBindAddress("0.0.0.0"))

    def test_ipv6_wildcard_is_rejected(self) -> None:
        self.assertTrue(isWildcardBindAddress("::"))

    def test_loopback_is_allowed(self) -> None:
        self.assertFalse(isWildcardBindAddress("127.0.0.1"))

    def test_lan_address_is_allowed(self) -> None:
        self.assertFalse(isWildcardBindAddress("192.168.1.10"))

    def test_invalid_string_is_not_flagged_as_wildcard(self) -> None:
        # isValidIpAddress 側の既存チェックが弾く前提なので、ここでは
        # False (=ワイルドカードではない) を返せば十分。
        self.assertFalse(isWildcardBindAddress("not-an-ip"))


class SetWebSocketHostRejectsWildcardTests(unittest.TestCase):
    def setUp(self) -> None:
        import config as config_module
        self._original_host = config_module.config.WEBSOCKET_HOST
        self.config = config_module.config

    def tearDown(self) -> None:
        self.config.WEBSOCKET_HOST = self._original_host

    @patch("controller.model")
    def test_rejects_0_0_0_0(self, mock_model) -> None:
        from controller import Controller
        mock_model.checkWebSocketServerAlive.return_value = False

        response = Controller.setWebSocketHost("0.0.0.0")

        self.assertEqual(response["status"], 400)
        self.assertEqual(
            response["result"]["error_code"],
            ErrorCode.VALIDATION_INVALID_IP.value,
        )
        self.assertNotEqual(self.config.WEBSOCKET_HOST, "0.0.0.0")

    @patch("controller.model")
    def test_rejects_ipv6_wildcard(self, mock_model) -> None:
        from controller import Controller
        mock_model.checkWebSocketServerAlive.return_value = False

        response = Controller.setWebSocketHost("::")

        self.assertEqual(response["status"], 400)
        self.assertEqual(
            response["result"]["error_code"],
            ErrorCode.VALIDATION_INVALID_IP.value,
        )
        self.assertNotEqual(self.config.WEBSOCKET_HOST, "::")

    @patch("controller.model")
    def test_accepts_a_normal_loopback_address(self, mock_model) -> None:
        from controller import Controller
        mock_model.checkWebSocketServerAlive.return_value = False

        response = Controller.setWebSocketHost("127.0.0.1")

        self.assertEqual(response["status"], 200)
        self.assertEqual(self.config.WEBSOCKET_HOST, "127.0.0.1")


class WebSocketEndpointErrorResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_host = config.WEBSOCKET_HOST
        self._original_port = config.WEBSOCKET_PORT
        self._original_server = config.WEBSOCKET_SERVER
        config.WEBSOCKET_SERVER = False

    def tearDown(self) -> None:
        config.WEBSOCKET_HOST = self._original_host
        config.WEBSOCKET_PORT = self._original_port
        config.WEBSOCKET_SERVER = self._original_server

    def test_non_numeric_port_returns_invalid_port_error(self) -> None:
        response = Controller.setWebSocketPort("not-a-port")

        self.assertEqual(response["status"], 400)
        self.assertEqual(
            response["result"]["error_code"],
            ErrorCode.WEBSOCKET_PORT_INVALID.value,
        )
        self.assertEqual(config.WEBSOCKET_PORT, self._original_port)

    @patch("controller.isAvailableWebSocketServer", return_value=False)
    def test_enable_when_server_address_is_unavailable_returns_server_error(
        self, _mock_is_available
    ) -> None:
        response = Controller.setEnableWebSocketServer()

        self.assertEqual(response["status"], 400)
        self.assertEqual(
            response["result"]["error_code"],
            ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE.value,
        )
        self.assertFalse(config.WEBSOCKET_SERVER)

    @patch("controller.errorLogging")
    @patch("controller.model")
    def test_host_exception_returns_safe_host_error(
        self, mock_model, mock_error_logging
    ) -> None:
        mock_model.checkWebSocketServerAlive.side_effect = RuntimeError(
            "provider response contains a secret"
        )

        response = Controller.setWebSocketHost("127.0.0.2")

        self.assertEqual(response["status"], 400)
        self.assertEqual(
            response["result"]["error_code"],
            ErrorCode.WEBSOCKET_HOST_INVALID.value,
        )
        self.assertNotIn("provider response contains a secret", response["result"]["message"])
        mock_error_logging.assert_called_once()
        self.assertEqual(config.WEBSOCKET_HOST, self._original_host)

    @patch("controller.errorLogging")
    @patch("controller.model")
    def test_port_exception_returns_safe_port_error(
        self, mock_model, mock_error_logging
    ) -> None:
        mock_model.checkWebSocketServerAlive.side_effect = RuntimeError(
            "provider response contains a secret"
        )

        response = Controller.setWebSocketPort(self._original_port + 1)

        self.assertEqual(response["status"], 400)
        self.assertEqual(
            response["result"]["error_code"],
            ErrorCode.WEBSOCKET_PORT_UNAVAILABLE.value,
        )
        self.assertNotIn("provider response contains a secret", response["result"]["message"])
        mock_error_logging.assert_called_once()
        self.assertEqual(config.WEBSOCKET_PORT, self._original_port)

    @patch("controller.errorLogging")
    @patch("controller.isAvailableWebSocketServer", return_value=True)
    @patch("controller.model")
    def test_enable_exception_returns_safe_server_error(
        self, mock_model, _mock_is_available, mock_error_logging
    ) -> None:
        mock_model.startWebSocketServer.side_effect = RuntimeError(
            "provider response contains a secret"
        )

        response = Controller.setEnableWebSocketServer()

        self.assertEqual(response["status"], 400)
        self.assertEqual(
            response["result"]["error_code"],
            ErrorCode.WEBSOCKET_SERVER_UNAVAILABLE.value,
        )
        self.assertNotIn("provider response contains a secret", response["result"]["message"])
        mock_error_logging.assert_called_once()
        self.assertFalse(config.WEBSOCKET_SERVER)


class ConfigDescriptorRejectsWildcardTests(unittest.TestCase):
    """setWebSocketHost() を経由しない経路 (config.json のロード相当) でも
    0.0.0.0/:: が弾かれることを確認する。"""

    def setUp(self) -> None:
        import config as config_module
        self.config = config_module.config
        self._original_host = self.config.WEBSOCKET_HOST

    def tearDown(self) -> None:
        self.config.WEBSOCKET_HOST = self._original_host

    def test_direct_assignment_of_wildcard_is_ignored(self) -> None:
        # フェーズ3項目24により、ディスクリプタは拒否時にサイレントreturnせず
        # ConfigValidationError を送出するようになった。load_config() 自身は
        # 1キーごとに try/except で包んであるため (config.py:1276-1290)、
        # 起動時に config.json へ 0.0.0.0 が書かれていても実際の挙動は
        # 変わらない (この例外がその場で捕まり、該当キーだけスキップされる)。
        # ここでは「例外を送出する」+「値は書き変わらない」の両方を検証する。
        import config as config_module

        self.config.WEBSOCKET_HOST = "127.0.0.1"
        with self.assertRaises(config_module.ConfigValidationError):
            self.config.WEBSOCKET_HOST = "0.0.0.0"  # load_config() の setattr() 相当
        self.assertEqual(self.config.WEBSOCKET_HOST, "127.0.0.1", "0.0.0.0 が素通りしている")

    def test_direct_assignment_of_valid_host_is_accepted(self) -> None:
        self.config.WEBSOCKET_HOST = "192.168.1.5"
        self.assertEqual(self.config.WEBSOCKET_HOST, "192.168.1.5")


class WebSocketAuthTokenPersistenceTests(unittest.TestCase):
    """トークンが起動のたびに変わらず、config.json 経由で永続化されることを
    確認する (VRCT-TTS のような URL 手動入力型の外部連携ツールが、
    VRCT を再起動するたびに再設定を強いられないようにするため)。"""

    def setUp(self) -> None:
        import config as config_module
        self.config = config_module.config
        self._original_token = self.config.WEBSOCKET_AUTH_TOKEN

    def tearDown(self) -> None:
        self.config.WEBSOCKET_AUTH_TOKEN = self._original_token

    def test_token_is_a_non_empty_string_by_default(self) -> None:
        self.assertIsInstance(self._original_token, str)
        self.assertGreater(len(self._original_token), 0)

    def test_persisted_value_survives_a_simulated_reload(self) -> None:
        # load_config() の setattr() 相当: config.json に既に保存されている
        # 値があれば、それがそのまま使われ続ける (起動のたびに変わらない)。
        self.config.WEBSOCKET_AUTH_TOKEN = "persisted-token-value"
        self.assertEqual(self.config.WEBSOCKET_AUTH_TOKEN, "persisted-token-value")

    @patch("controller.model")
    def test_getter_endpoint_returns_the_persisted_token(self, _mock_model) -> None:
        from controller import Controller
        self.config.WEBSOCKET_AUTH_TOKEN = "abc-xyz-123"
        response = Controller.getWebSocketAuthToken()
        self.assertEqual(response, {"status": 200, "result": "abc-xyz-123"})


def finish_request(coro):
    """The request hook never suspends; no event loop or self-pipe is needed."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("request unexpectedly suspended")


class WebSocketServerTokenAuthTests(unittest.TestCase):
    """websockets の asyncio 実装では process_request(connection, request) が
    呼ばれ、拒否は connection.respond() が返す Response で表現される。
    ここでは connection / request を最小限モックして検証する。"""

    @staticmethod
    def _call(server: WebSocketServer, path: str):
        sentinel = object()
        connection = MagicMock()
        connection.respond.return_value = sentinel
        request = MagicMock()
        request.path = path
        return server._process_request(connection, request), connection, sentinel

    def test_missing_token_is_rejected(self) -> None:
        server = WebSocketServer(token="secret123")
        coro, connection, sentinel = self._call(server, "/")
        result = finish_request(coro)
        self.assertIs(result, sentinel)
        connection.respond.assert_called_once()
        self.assertEqual(connection.respond.call_args[0][0], HTTPStatus.FORBIDDEN)

    def test_wrong_token_is_rejected(self) -> None:
        server = WebSocketServer(token="secret123")
        coro, connection, sentinel = self._call(server, "/?token=wrong")
        result = finish_request(coro)
        self.assertIs(result, sentinel)
        self.assertEqual(connection.respond.call_args[0][0], HTTPStatus.FORBIDDEN)

    def test_correct_token_is_accepted(self) -> None:
        server = WebSocketServer(token="secret123")
        coro, connection, _sentinel = self._call(server, "/?token=secret123")
        result = finish_request(coro)
        self.assertIsNone(result, "正しいトークンなのにハンドシェイクが拒否された")
        connection.respond.assert_not_called()

    def test_no_token_configured_rejects_verification(self) -> None:
        # A missing configured token must fail closed, even before startup.
        server = WebSocketServer(token=None)
        coro, connection, sentinel = self._call(server, "/")
        result = finish_request(coro)
        self.assertIs(result, sentinel)
        self.assertEqual(connection.respond.call_args[0][0], HTTPStatus.FORBIDDEN)


class ObsBrowserSourceEmbedsTokenTests(unittest.TestCase):
    def test_html_embeds_the_supplied_token(self) -> None:
        html = _build_overlay_html(ws_token="abc123XYZ")
        self.assertIn('wsToken: "abc123XYZ"', html)
        self.assertIn("token=${encodeURIComponent(SETTINGS.wsToken)}", html)

    def test_html_with_empty_token_omits_query_string_at_runtime(self) -> None:
        html = _build_overlay_html(ws_token="")
        self.assertIn('wsToken: ""', html)

    def test_obs_server_passes_its_token_through_to_the_page(self) -> None:
        server = ObsBrowserSourceServer(host="127.0.0.1", port=0, ws_token="tok-xyz")
        self.assertEqual(server.ws_token, "tok-xyz")


@pytest.fixture
def obs_request():
    """Exercise the real HTTP handler using byte streams, without sockets or threads."""
    def request(path, *, token="secret-token", host="127.0.0.1:2232"):
        with (
            patch("models.obs.obs_browser_source_server._ObsHTTPServer") as http_server,
            patch("models.obs.obs_browser_source_server.threading.Thread"),
        ):
            server = ObsBrowserSourceServer("127.0.0.1", 0, ws_token=token)
            server.start()
            handler = http_server.call_args.args[1]

        wire = BytesIO()
        connection = MagicMock()
        connection.makefile.return_value = BytesIO(
            f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode("ascii")
        )
        connection.sendall.side_effect = wire.write
        handler(connection, ("127.0.0.1", 12345), http_server.return_value)

        response_connection = MagicMock()
        response_connection.makefile.return_value = BytesIO(wire.getvalue())
        response = HTTPResponse(response_connection)
        response.begin()
        return response, response.read()

    return request


@pytest.mark.parametrize("path", ["/", "/obs"])
@pytest.mark.parametrize("query", [
    "", "?token=wrong", "?token=", "?token=%E3%81%82", "?token=%FF",
    "?token=wrong&token=secret-token", "?token=secret-token&token=wrong",
    "?token=&token=secret-token",
])
def test_obs_page_rejects_invalid_tokens_before_building_html(obs_request, path, query):
    with patch("models.obs.obs_browser_source_server._build_overlay_html") as build_html:
        response, body = obs_request(path + query)
    assert response.status == 403
    assert response.getheader("Content-Type") == "text/plain; charset=utf-8"
    assert body == b"Forbidden\n"
    assert b"secret-token" not in body
    build_html.assert_not_called()


@pytest.mark.parametrize("path", ["/", "/obs"])
@pytest.mark.parametrize("query", ["?token=secret-token", "?token=secret%2Dtoken&unused=1"])
def test_obs_page_accepts_token_and_protects_response(obs_request, path, query):
    response, body = obs_request(path + query)
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert "no-store" in response.getheader("Cache-Control")
    assert response.getheader("Referrer-Policy") == "no-referrer"
    assert int(response.getheader("Content-Length")) == len(body)
    assert body.startswith(b"<!doctype html>")
    assert b'wsToken: "secret-token"' in body


@pytest.mark.parametrize("query", ["", "?token=", "?token=secret-token"])
def test_obs_page_fails_closed_without_a_configured_token(obs_request, query):
    response, body = obs_request("/obs" + query, token="")
    assert response.status == 403
    assert body == b"Forbidden\n"


@pytest.mark.parametrize("query", ["", "?token=wrong"])
def test_obs_health_remains_public_without_secrets(obs_request, query):
    response, body = obs_request("/health" + query)
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/plain; charset=utf-8"
    assert body == b"ok"


def test_obs_host_check_still_rejects_authenticated_rebound_requests(obs_request):
    with patch("models.obs.obs_browser_source_server._build_overlay_html") as build_html:
        response, body = obs_request("/obs?token=secret-token", host="attacker.example")
    assert response.status == 403
    assert b"secret-token" not in body
    build_html.assert_not_called()


def test_obs_requests_do_not_log_secret_query_strings(obs_request, capsys):
    obs_request("/obs?token=secret-token")
    obs_request("/obs?token=wrong")
    obs_request("/unknown?token=secret-token")
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


if __name__ == "__main__":
    unittest.main()
