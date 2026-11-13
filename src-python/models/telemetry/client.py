"""Sends VRCT-VOX's usage events to VRCT-VOX's own receiver.

Two events exist and the receiver takes no others: "app_started" and "error" with its
fixed error code. Each carries the time (ISO 8601, UTC), the app's version, the OS and its version, the
display language, and the PC's CPU, memory and GPUs (hardware.py). No text, audio, audio
device or user names, paths or identifiers.

build_event() is the only place an event is put together: what the app shows the user as
"what is sent" and what is posted come from the same call, and differ only in the time.

This is not upstream VRCT's Aptabase telemetry. Nothing here reads a telemetry_keys file
or creates an Aptabase client, whatever an older build left on the disk.
"""
import asyncio
from datetime import datetime, timezone
import http.client
import ipaddress
import json
import os
import platform
import re
import ssl
from urllib.parse import urlsplit

# The receiver (Cloudflare Workers) and the key that marks a request as VRCT-VOX's. The key
# is public and is not a credential: it grants nothing but posting these two events.
ENDPOINT = "https://vrct-vox-telemetry.kei9d09.workers.dev/v1/events"
INGEST_KEY = "e77471acded45435be55c2fed04a05636e4eb00be5a277fb"
# A developer's stand-in receiver on this PC. Only a loopback HTTP address is taken, so
# the variable cannot send anyone's events to another host.
ENDPOINT_OVERRIDE = "VRCT_TELEMETRY_URL"
EVENTS = ("app_started", "error")
# The version of the event's shape. 1 had no "v" and no "hw".
SCHEMA = 2
ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
TIMEOUT = 5.0
# The display language as the tag the receiver stores.
LOCALES = {"en": "en-US", "ja": "ja-JP", "ko": "ko-KR", "zh-Hans": "zh-CN", "zh-Hant": "zh-TW"}
_PRINTABLE = re.compile(r"[\x20-\x7e]{1,64}")


def _target(endpoint):
    """(scheme, host, port, path) for HTTPS, or for plain HTTP on a loopback address; else None."""
    if not isinstance(endpoint, str) or not endpoint:
        return None
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        return None
    if url.username or url.password or url.query or url.fragment or not url.hostname or not url.path.startswith("/"):
        return None
    if url.scheme == "https":
        return "https", url.hostname, port or 443, url.path
    if url.scheme == "http":
        try:
            loopback = ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            loopback = False
        if loopback:
            return "http", url.hostname, port or 80, url.path
    return None


def _endpoint():
    override = os.environ.get(ENDPOINT_OVERRIDE)
    if override:
        target = _target(override)
        if target is not None and target[0] == "http":
            return override
    return ENDPOINT


def locale_tag(language):
    return LOCALES.get(language, "en-US")


def system_properties(app_version, language, hardware=None):
    """What every event carries about where it came from. hardware is hardware.collect()'s."""
    system = platform.system()
    version = platform.version() if system == "Windows" else platform.release()
    properties = {
        "app_version": app_version if isinstance(app_version, str) and _PRINTABLE.fullmatch(app_version) else "unknown",
        "os": system if system in ("Windows", "Linux") else "Other",
        "os_version": version if isinstance(version, str) and _PRINTABLE.fullmatch(version) else "unknown",
        "locale": locale_tag(language),
    }
    if isinstance(hardware, dict) and hardware:
        properties["hw"] = hardware
    return properties


def build_event(name, properties, error_code=None, now=None):
    """The event as it is sent, or None for anything that is not one of the two.

    The timestamp is ISO 8601 in UTC, to the second: the moment the event is put together.
    """
    if name not in EVENTS or not isinstance(properties, dict):
        return None
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {"event": name, "v": SCHEMA, "timestamp": stamp, **properties}
    if name == "error":
        if not isinstance(error_code, str) or not ERROR_CODE.fullmatch(error_code):
            return None
        body["error_code"] = error_code
    return body


class IngestClient:
    """One POST per event, never raising: a failure is only an event that was not sent."""

    def __init__(self, endpoint=None, key=INGEST_KEY, timeout=TIMEOUT):
        self._target = _target(endpoint if endpoint is not None else _endpoint())
        self._key, self._timeout = key, timeout
        self._properties = None
        self._context = None

    def prepare(self):
        """Builds the TLS context on the caller's thread.

        Loading the system's certificates allocates a lot. The telemetry thread never
        initializes COM, and a garbage collection that such work triggers there has
        released other threads' COM objects before (models/telemetry/__init__.py).
        """
        if self._target is not None and self._target[0] == "https" and self._context is None:
            try:
                self._context = ssl.create_default_context()
            except Exception:
                self._target = None  # Without verified TLS nothing is sent.

    @property
    def endpoint(self):
        """Where events go, or None when nothing can be sent."""
        if self._target is None:
            return None
        scheme, host, port, path = self._target
        default = 443 if scheme == "https" else 80
        return f"{scheme}://{host}{'' if port == default else ':' + str(port)}{path}"

    async def start(self, app_version="", locale="", hardware=None):
        self._properties = system_properties(app_version, locale, hardware)

    async def stop(self):
        self._properties = None

    def event(self, name, properties=None):
        """The event as it is sent, or None for anything that is not one of the two."""
        if self._properties is None:
            return None
        return build_event(name, self._properties, (properties or {}).get("error_code"))

    async def track(self, event_name, properties=None):
        """(the event as sent, whether the receiver accepted it); (None, False) when nothing was sent."""
        body = self.event(event_name, properties)
        if body is None or self._target is None:
            return None, False
        return body, await asyncio.to_thread(self._post, body)

    def _post(self, body):
        scheme, host, port, path = self._target
        data = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        try:
            if scheme == "https":
                if self._context is None:
                    self.prepare()
                connection = http.client.HTTPSConnection(host, port, timeout=self._timeout, context=self._context)
            else:
                connection = http.client.HTTPConnection(host, port, timeout=self._timeout)
        except Exception:
            return False
        try:
            connection.request("POST", path, body=data, headers={
                "Content-Type": "application/json", "Content-Length": str(len(data)),
                "X-Ingest-Key": self._key, "User-Agent": "VRCT-VOX"})
            response = connection.getresponse()
            answer = response.read(4096)
            if response.status != 200:
                return False
            reply = json.loads(answer)
            return isinstance(reply, dict) and reply.get("ok") is True and reply.get("accepted") == 1
        except (OSError, http.client.HTTPException, ValueError):
            return False
        finally:
            connection.close()
