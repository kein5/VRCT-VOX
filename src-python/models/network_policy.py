"""Outbound API policy. Model downloads have their own pinned transport."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from ipaddress import ip_address, ip_network
import os
import re
from threading import Lock, Timer
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

OPENAI_BASE_URL = "https://api.openai.com/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
DISCOVERY_TIMEOUT = 3.0
DISCOVERY_DEADLINE = 8.0
_LOCAL_NETWORKS = tuple(ip_network(value) for value in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10",
))
CUSTOM_URL_KEYS = ("LMSTUDIO_URL", "OPENAI_COMPATIBLE_URL", "TRANSCRIPTION_CUSTOM_URL")


def is_local_host(host):
    if host and host.lower().rstrip(".") == "localhost":
        return True
    try:
        address = ip_address(host)
        return any(address in network for network in _LOCAL_NETWORKS)
    except ValueError:
        return False


def validate_api_url(url, *, allow_empty=False):
    """Validate without DNS or I/O; only literal local addresses permit HTTP."""
    if allow_empty and url == "":
        return url
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("endpoint_url_invalid")
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.fragment or "\\" in url or parts.port == 0
                or (parts.scheme == "http" and not is_local_host(parts.hostname))):
            raise ValueError("endpoint_url_invalid")
        for key, _ in parse_qsl(parts.query, keep_blank_values=True):
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(word in normalized for word in ("key", "token", "secret", "password", "auth", "credential", "signature")) or normalized in ("sig", "code"):
                raise ValueError("endpoint_url_invalid")
    except (ValueError, TypeError):
        raise ValueError("endpoint_url_invalid") from None
    return url


def valid_saved_api_url(url):
    try:
        validate_api_url(url, allow_empty=True)
        return True
    except ValueError:
        return False


def redact_urls(value):
    """Remove URL userinfo and every query value, including nested log data."""
    if isinstance(value, dict):
        return {key: redact_urls(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_urls(item) for item in value]
    if not isinstance(value, str):
        return value

    def redact(match):
        try:
            parts = urlsplit(match.group())
            authority = parts.netloc.rsplit("@", 1)[-1]
            query = urlencode([(key, "REDACTED") for key, _ in parse_qsl(parts.query, keep_blank_values=True)])
            return urlunsplit((parts.scheme, authority, parts.path, query, ""))
        except ValueError:
            return "[redacted URL]"

    return re.sub(r"https?://[^\s<>]+", redact, value, flags=re.IGNORECASE)


def scrub_network_environment():
    """Run before SDK imports in the sidecar; never restore ambient tracing."""
    for name in tuple(os.environ):
        if name.startswith(("LANGSMITH_", "LANGCHAIN_")) or name in (
            "OLLAMA_API_KEY", "GOOGLE_GEMINI_BASE_URL", "GOOGLE_VERTEX_BASE_URL",
            "GOOGLE_GENAI_USE_VERTEXAI",
        ):
            os.environ.pop(name, None)
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


def without_tracing(function):
    """Disable env and inherited LangChain tracing in this invocation's context."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        scrub_network_environment()
        from langsmith import tracing_context
        from langchain_core.tracers.context import tracing_v2_callback_var
        token = tracing_v2_callback_var.set(None)
        try:
            with tracing_context(enabled=False, parent=None, client=None):
                return function(*args, **kwargs)
        finally:
            tracing_v2_callback_var.reset(token)
    return wrapped


class DiscoveryScope:
    """Own discovery transports, closing them on completion or abandonment."""
    def __init__(self, seconds=DISCOVERY_DEADLINE):
        self.deadline = monotonic() + seconds
        self.clients = []
        self.lock = Lock()
        self.closed = False
        self.timer = Timer(seconds, self.close)
        self.timer.daemon = True

    def check(self):
        if self.closed or monotonic() >= self.deadline:
            raise TimeoutError("discovery_deadline")

    def own(self, client):
        with self.lock:
            if self.closed:
                client.close()
                raise TimeoutError("discovery_deadline")
            self.clients.append(client)
        return client

    def close(self):
        with self.lock:
            self.closed = True
            clients, self.clients = self.clients, []
        for client in clients:
            try:
                client.close()
            except Exception:
                pass


_discovery_scope = ContextVar("discovery_scope", default=None)


@contextmanager
def discovery_scope(scope=None):
    existing = _discovery_scope.get()
    if existing is not None:
        existing.check()
        yield existing
        return
    scope = scope or DiscoveryScope()
    token = _discovery_scope.set(scope)
    scope.timer.start()
    try:
        scope.check()
        yield scope
        scope.check()
    finally:
        scope.timer.cancel()
        scope.close()
        _discovery_scope.reset(token)


def discovery(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with discovery_scope():
            return function(*args, **kwargs)
    return wrapped


def own_discovery_client(client):
    scope = _discovery_scope.get()
    return scope.own(client) if scope is not None else client


def check_discovery_deadline(*_args):
    scope = _discovery_scope.get()
    if scope is not None:
        scope.check()


def api_http_client(base_url, *, timeout, asynchronous=False):
    import httpx
    validate_api_url(base_url)
    client_type = httpx.AsyncClient if asynchronous else httpx.Client
    kwargs = {"timeout": timeout, "follow_redirects": False,
              "trust_env": not is_local_host(urlsplit(base_url).hostname)}
    if not asynchronous:
        kwargs["event_hooks"] = {"request": [check_discovery_deadline]}
    return client_type(**kwargs)


def chat_http_clients(base_url, timeout):
    return {
        "http_client": api_http_client(base_url, timeout=timeout),
        "http_async_client": api_http_client(base_url, timeout=timeout, asynchronous=True),
        "openai_proxy": "",  # Ignore OPENAI_PROXY; HTTP(S)_PROXY still works for cloud.
    }


def fetch_openai_models(client_type, api_key, base_url=OPENAI_BASE_URL):
    with discovery_scope():
        transport = own_discovery_client(api_http_client(base_url, timeout=DISCOVERY_TIMEOUT))
        client = own_discovery_client(client_type(api_key=api_key, base_url=base_url,
                                                timeout=DISCOVERY_TIMEOUT, max_retries=0,
                                                http_client=transport))
        return client.models.list()


def explicit_request_auth(request):
    """Keep the configured header; do not replace it with ambient netrc auth."""
    return request


def api_request(method, url, **kwargs):
    import requests
    validate_api_url(url)
    check_discovery_deadline()
    with requests.Session() as session:
        session.trust_env = not is_local_host(urlsplit(url).hostname)
        session.auth = explicit_request_auth
        own_discovery_client(session)
        return session.request(method, url, allow_redirects=False, **kwargs)


def nothing_answered(error):
    """True for a failed connection, which is what a stopped local engine gives."""
    import requests
    return isinstance(error, requests.ConnectionError)
