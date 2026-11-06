import hmac
import ipaddress
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic
from urllib.parse import parse_qs, urlparse

from models.obs.settings import NUMERIC_RANGES
from config import config
from utils import printLog


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_REQUEST_TIMEOUT = 5.0
_MAX_HANDLERS = 16
_STOP_TIMEOUT = 2.0


class _ObsHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, handler):
        self._stopping = threading.Event()
        self._handlers_lock = threading.Lock()
        self._handlers = {}
        super().__init__(address, handler)

    def _prune_handlers(self):
        self._handlers = {request: worker for request, worker in self._handlers.items() if worker[0].is_alive()}

    @property
    def has_handlers(self):
        with self._handlers_lock:
            self._prune_handlers()
            return bool(self._handlers)

    def process_request(self, request, client_address):
        with self._handlers_lock:
            self._prune_handlers()
            if not self._stopping.is_set() and len(self._handlers) < _MAX_HANDLERS:
                request.settimeout(_REQUEST_TIMEOUT)
                worker = threading.Thread(target=self.process_request_thread,
                                          args=(request, client_address), daemon=True,
                                          name="obs_http_request")
                self._handlers[request] = (worker, monotonic() + _REQUEST_TIMEOUT)
                try:
                    worker.start()
                except Exception:
                    del self._handlers[request]
                    self.shutdown_request(request)
                    raise
                return
        self.shutdown_request(request)

    @staticmethod
    def _interrupt(request):
        try:
            request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        request.close()

    def service_actions(self):
        # A total deadline also covers clients that drip headers often enough
        # to avoid the socket's per-read timeout.
        with self._handlers_lock:
            self._prune_handlers()
            for request, (_, deadline) in self._handlers.items():
                if monotonic() >= deadline:
                    self._interrupt(request)

    def serve_forever(self, poll_interval=0.1):
        self.timeout = poll_interval
        while not self._stopping.is_set():
            try:
                self.handle_request()
            except (OSError, ValueError):
                if not self._stopping.is_set():
                    raise
            self.service_actions()

    def shutdown(self):
        # Unlike BaseServer.shutdown, this does not wait for a serving thread
        # that may never have started. The owner joins all workers below.
        self._stopping.set()
        with self._handlers_lock:
            for request in self._handlers:
                self._interrupt(request)

    def join_handlers(self, deadline):
        with self._handlers_lock:
            workers = [worker for worker, _ in self._handlers.values()]
        for worker in workers:
            worker.join(timeout=max(0, deadline - monotonic()))

    def handle_error(self, request, client_address):
        printLog("OBS browser source: HTTP request failed")


def _clamp_int(value, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except Exception:
        return min_value
    return max(min_value, min(max_value, number))


def _normalize_hex_color(value: str, fallback: str = "#FFFFFF") -> str:
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    if _HEX_COLOR_RE.match(value):
        return value
    return fallback


def _build_overlay_html(ws_token: str = "") -> str:
    ws_port = _clamp_int(getattr(config, "WEBSOCKET_PORT", 2231), 1, 65535)
    # WebSocket サーバー側の token 検証 (websocket_server.py 参照) に
    # 必要な接続トークン。JS 文字列リテラルへそのまま埋め込むが、
    # secrets.token_urlsafe() の出力は URL-safe base64
    # ([A-Za-z0-9_-]) のみなので、クォートや HTML/JS を壊す文字は含まない。
    ws_token_js = ws_token if isinstance(ws_token, str) else ""

    max_messages = _clamp_int(
        getattr(config, "OBS_BROWSER_SOURCE_MAX_MESSAGES", 14), *NUMERIC_RANGES["MAX_MESSAGES"]
    )
    display_duration = _clamp_int(
        getattr(config, "OBS_BROWSER_SOURCE_DISPLAY_DURATION", 60), *NUMERIC_RANGES["DISPLAY_DURATION"]
    )
    fadeout_duration = _clamp_int(
        getattr(config, "OBS_BROWSER_SOURCE_FADEOUT_DURATION", 12), *NUMERIC_RANGES["FADEOUT_DURATION"]
    )

    font_size = _clamp_int(getattr(config, "OBS_BROWSER_SOURCE_FONT_SIZE", 40), *NUMERIC_RANGES["FONT_SIZE"])
    font_color = _normalize_hex_color(
        getattr(config, "OBS_BROWSER_SOURCE_FONT_COLOR", "#FFFFFF")
    )
    outline_thickness = _clamp_int(
        getattr(config, "OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS", 3), *NUMERIC_RANGES["FONT_OUTLINE_THICKNESS"]
    )
    outline_color = _normalize_hex_color(
        getattr(config, "OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR", "#000000"),
        fallback="#000000",
    )

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>VRCT OBS Browser Source</title>
    <style>
      :root {{
        --font-size: {font_size}px;
        --font-color: {font_color};
        --outline-size: {outline_thickness}px;
        --outline-color: {outline_color};
        --display-duration: {display_duration}s;
        --fadeout-duration: {fadeout_duration}s;
      }}

      html, body {{
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
        background: transparent;
        overflow: hidden;
        color: var(--font-color);
        font-family:
          "Noto Sans CJK JP",
          "Noto Sans JP",
          "Noto Sans CJK",
          "Noto Sans",
          "Segoe UI",
          "Meiryo",
          system-ui,
          sans-serif;
        font-weight: 600;
        text-shadow: 0 2px 10px rgba(0,0,0,.85), 0 0 2px rgba(0,0,0,.95);
      }}

      #root {{
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 32px 48px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        pointer-events: none;
      }}

      .msg {{
        font-size: var(--font-size);
        line-height: 1.2;
        white-space: pre-wrap;
        opacity: 1;
        transform: translateY(0);
        animation: fadeout var(--fadeout-duration) ease var(--display-duration) forwards;
      }}

      .msg, .msg * {{
        -webkit-text-stroke-width: var(--outline-size);
        -webkit-text-stroke-color: var(--outline-color);
      }}

      .msg .translation {{
        font-weight: 700;
      }}

      .msg .original {{
        margin-top: 4px;
        font-size: calc(var(--font-size) * 0.75);
        opacity: 0.9;
      }}

      @keyframes fadeout {{
        to {{
          opacity: 0;
          transform: translateY(8px);
        }}
      }}
    </style>
  </head>
  <body>
    <div id="root"></div>

    <script>
      (() => {{
        const SETTINGS = {{
          wsPort: {ws_port},
          wsToken: "{ws_token_js}",
          maxMessages: {max_messages},
          displayDurationMs: {display_duration} * 1000,
          fadeoutDurationMs: {fadeout_duration} * 1000,
        }};

        const root = document.getElementById("root");
        let reconnectDelayMs = 500;
        let reconnectTimer = null;

        const asString = (v) => (typeof v === "string" ? v : "");
        const asStringArray = (v) =>
          Array.isArray(v) ? v.filter((x) => typeof x === "string" && x.length > 0) : [];

        const HEX_COLOR_RE = /^#[0-9a-fA-F]{{6}}$/;

        const numericRanges = {json.dumps({"maxMessages": NUMERIC_RANGES["MAX_MESSAGES"], "displayDuration": NUMERIC_RANGES["DISPLAY_DURATION"], "fadeoutDuration": NUMERIC_RANGES["FADEOUT_DURATION"], "fontSize": NUMERIC_RANGES["FONT_SIZE"], "outlineThickness": NUMERIC_RANGES["FONT_OUTLINE_THICKNESS"]})};
        const validNumber = (name, value) => Number.isInteger(value) &&
          value >= numericRanges[name][0] && value <= numericRanges[name][1];

        const applySettings = (settings) => {{
          if (!settings || typeof settings !== "object") return;
          const style = document.documentElement.style;

          if (validNumber("maxMessages", settings.maxMessages)) {{
            SETTINGS.maxMessages = settings.maxMessages;
          }}
          if (validNumber("displayDuration", settings.displayDuration)) {{
            SETTINGS.displayDurationMs = settings.displayDuration * 1000;
            style.setProperty("--display-duration", `${{settings.displayDuration}}s`);
          }}
          if (validNumber("fadeoutDuration", settings.fadeoutDuration)) {{
            SETTINGS.fadeoutDurationMs = settings.fadeoutDuration * 1000;
            style.setProperty("--fadeout-duration", `${{settings.fadeoutDuration}}s`);
          }}
          if (validNumber("fontSize", settings.fontSize)) {{
            style.setProperty("--font-size", `${{settings.fontSize}}px`);
          }}
          if (typeof settings.fontColor === "string" && HEX_COLOR_RE.test(settings.fontColor)) {{
            style.setProperty("--font-color", settings.fontColor);
          }}
          if (validNumber("outlineThickness", settings.outlineThickness)) {{
            style.setProperty("--outline-size", `${{settings.outlineThickness}}px`);
          }}
          if (typeof settings.outlineColor === "string" && HEX_COLOR_RE.test(settings.outlineColor)) {{
            style.setProperty("--outline-color", settings.outlineColor);
          }}
        }};

        const addMessage = (payload) => {{
          const type = asString(payload?.type) || "MESSAGE";
          const message = asString(payload?.message);
          const translations = asStringArray(payload?.translation);

          const translationText = translations.join("\\n");
          const primaryText = translationText || message;
          if (!primaryText) return;

          const msgEl = document.createElement("div");
          msgEl.className = `msg msg-${{type.toLowerCase()}}`;

          const translationEl = document.createElement("div");
          translationEl.className = "translation";
          translationEl.textContent = primaryText;
          msgEl.appendChild(translationEl);

          if (translationText && message && message !== translationText) {{
            const originalEl = document.createElement("div");
            originalEl.className = "original";
            originalEl.textContent = message;
            msgEl.appendChild(originalEl);
          }}

          root.appendChild(msgEl);

          while (root.childNodes.length > SETTINGS.maxMessages) {{
            root.removeChild(root.firstChild);
          }}

          window.setTimeout(() => {{
            msgEl.remove();
          }}, SETTINGS.displayDurationMs + SETTINGS.fadeoutDurationMs + 250);
        }};

        const scheduleReconnect = () => {{
          if (reconnectTimer) return;
          reconnectTimer = window.setTimeout(async () => {{
            reconnectTimer = null;
            // Re-read the port even if the old socket missed a settings event.
            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), 5000);
            try {{
              const response = await fetch("/obs/connection", {{
                headers: {{ Authorization: `Bearer ${{SETTINGS.wsToken}}` }},
                cache: "no-store", referrerPolicy: "no-referrer", signal: controller.signal,
              }});
              if (!response.ok) throw new Error("Connection settings unavailable");
              const settings = await response.json();
              if (!Number.isInteger(settings.wsPort) || settings.wsPort < 1 || settings.wsPort > 65535)
                throw new Error("Invalid connection settings");
              SETTINGS.wsPort = settings.wsPort;
            }} catch (e) {{
              scheduleReconnect();
              return;
            }} finally {{
              window.clearTimeout(timeout);
            }}
            connect();
          }}, reconnectDelayMs);
          reconnectDelayMs = Math.min(reconnectDelayMs * 1.5, 8000);
        }};

        const connect = () => {{
          const wsUrl = SETTINGS.wsToken
            ? `ws://${{location.hostname}}:${{SETTINGS.wsPort}}/?token=${{encodeURIComponent(SETTINGS.wsToken)}}`
            : `ws://${{location.hostname}}:${{SETTINGS.wsPort}}`;
          let ws;
          try {{
            ws = new WebSocket(wsUrl);
          }} catch (e) {{
            scheduleReconnect();
            return;
          }}

          ws.addEventListener("open", () => {{
            reconnectDelayMs = 500;
          }});

          ws.addEventListener("message", (event) => {{
            try {{
              const payload = JSON.parse(event.data);
              if (asString(payload?.type) === "SETTINGS_UPDATED") {{
                applySettings(payload?.settings);
                return;
              }}
              addMessage(payload);
            }} catch (e) {{
              // ignore malformed messages
            }}
          }});

          ws.addEventListener("close", () => {{
            scheduleReconnect();
          }});

          ws.addEventListener("error", () => {{
            try {{ ws.close(); }} catch (e) {{}}
          }});
        }};

        connect();
      }})();
    </script>
  </body>
</html>
"""


def _is_trusted_host_header(value) -> bool:
    """Accept only IP literals and localhost in the Host header.

    The overlay page embeds the WebSocket token. A web page can rebind its own
    domain name to 127.0.0.1 (DNS rebinding) and then read this page as
    same-origin; such a request carries that domain name in Host. OBS and LAN
    clients reach the server by IP address or localhost.
    """
    if not isinstance(value, str) or not value:
        return False
    host = value.strip()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    if host.lower() == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class ObsBrowserSourceServer:
    def __init__(self, host: str, port: int, ws_token: str = "") -> None:
        self.host = host
        self.port = port
        # ページの取得とWebSocket接続で同じトークンを使う。
        # 認証できた要求にだけ、トークンを含むページを返す。
        self.ws_token = ws_token
        self._server: _ObsHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._stopping = False
        self._stop_logged = False

    @property
    def is_running(self) -> bool:
        return not self._stopping and self._thread is not None and self._thread.is_alive()

    @property
    def is_stopped(self) -> bool:
        return ((self._thread is None or not self._thread.is_alive())
                and (self._server is None or not self._server.has_handlers))

    def start(self) -> None:
        with self._lifecycle_lock:
            self._start()

    def _start(self) -> None:
        if not self.is_stopped:
            return
        self._stopping = False
        self._stop_logged = False

        ws_token = self.ws_token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                # Keep request URLs (including secret query strings) out of logs.
                return

            def do_GET(self):  # noqa: N802
                if not _is_trusted_host_header(self.headers.get("Host")):
                    self.send_response(403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/obs", "/obs/connection"):
                    metadata = parsed.path == "/obs/connection"
                    tokens = ([self.headers.get("Authorization", "").removeprefix("Bearer ")]
                              if metadata else parse_qs(parsed.query, keep_blank_values=True).get("token", []))
                    if (
                        not ws_token
                        or (metadata and not self.headers.get("Authorization", "").startswith("Bearer "))
                        or len(tokens) != 1
                        or not hmac.compare_digest(
                            tokens[0].encode("utf-8"), ws_token.encode("utf-8")
                        )
                    ):
                        body = b"Forbidden\n"
                        self.send_response(403)
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.send_header("Cache-Control", "no-store, max-age=0")
                        self.send_header("Referrer-Policy", "no-referrer")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    body = (json.dumps({"wsPort": config.WEBSOCKET_PORT}) if metadata
                            else _build_overlay_html(ws_token)).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json" if metadata else "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store, max-age=0")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if parsed.path == "/health":
                    body = b"ok"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store, max-age=0")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

        self._server = _ObsHTTPServer((self.host, self.port), Handler)
        try:
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="obs_browser_source_server",
            )
            self._thread.start()
        except Exception:
            self._stop()
            raise

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop()

    def _stop(self) -> None:
        deadline = monotonic() + _STOP_TIMEOUT
        self._stopping = True
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass

        if self._thread is not None and self._thread.ident is not None:
            self._thread.join(timeout=max(0, deadline - monotonic()))
        if self._server is not None:
            self._server.join_handlers(deadline)
        if not self.is_stopped:
            if not self._stop_logged:
                self._stop_logged = True
                printLog("OBS browser source: stop timed out; retaining server until the workers exit")
            return

        self._server = None
        self._thread = None
