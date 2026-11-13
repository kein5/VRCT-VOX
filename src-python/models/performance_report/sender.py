"""Posts one report to the receiver. A failure is only a report that was not sent."""
import http.client
import ipaddress
import json
from urllib.parse import urlsplit

from .schema import MAX_BODY_BYTES, fault_of


def _target(endpoint):
    """(scheme, host, port, path) of an endpoint a report may go to, or None.

    The receiver is reached over HTTPS. Plain HTTP is taken for a loopback address alone,
    which is how the receiver is run on the developer's own PC.
    """
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


def send(endpoint, report, timeout=5.0):
    """Whether the receiver took the report. Never raises and never follows a redirect.

    Nothing is sent without an endpoint, to an endpoint of another kind, or when the report
    holds anything outside the list. The request carries the report and no cookies,
    credentials or identifiers of its own.
    """
    target = _target(endpoint)
    if target is None or fault_of(report) is not None:
        return False
    body = json.dumps(report, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(body) > MAX_BODY_BYTES:
        return False
    scheme, host, port, path = target
    connection = (http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection)(host, port, timeout=timeout)
    try:
        connection.request("POST", path, body=body, headers={
            "Content-Type": "application/json", "Content-Length": str(len(body)), "User-Agent": "VRCT-VOX"})
        response = connection.getresponse()
        response.read(1024)
        return 200 <= response.status < 300
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        connection.close()
