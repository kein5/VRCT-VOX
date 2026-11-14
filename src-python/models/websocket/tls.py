"""TLS for the WebSocket and OBS servers when they listen beyond this PC (SEC-01).

On a loopback address (127.0.0.0/8) nothing leaves the PC, so both servers stay plain
`ws://` and `http://`. Any other address needs a certificate and key that the user
chose: the WebSocket server then speaks `wss://` and OBS `https://`, and the token and the
conversation are encrypted on the network. Without a usable certificate the servers do not
listen there at all.
"""
import ipaddress
import os
import ssl
import stat

# A certificate chain and key in PEM are a few KB. A cap keeps a mistyped path to a large
# file (or a device) from being read whole.
MAX_PEM_BYTES = 1024 * 1024


class TlsSettingsError(ValueError):
    """The certificate or key cannot be used. The reason never holds a path or file contents."""

    REASONS = ("missing", "unreadable", "not_a_file", "size", "load_failed")


def requires_tls(host) -> bool:
    """Only loopback addresses may listen without TLS. Anything unparsable counts as remote."""
    try:
        return not ipaddress.IPv4Address(host).is_loopback
    except (ValueError, TypeError):
        return True


def _check_file(path) -> None:
    if not isinstance(path, str) or not path.strip():
        raise TlsSettingsError("missing")
    try:
        info = os.stat(path)
    except OSError:
        raise TlsSettingsError("unreadable") from None
    if not stat.S_ISREG(info.st_mode):
        raise TlsSettingsError("not_a_file")
    if info.st_size == 0 or info.st_size > MAX_PEM_BYTES:
        raise TlsSettingsError("size")


def _no_passphrase():
    # A key with a passphrase is not supported. Without this callback OpenSSL would ask
    # for the passphrase on the console and the sidecar would wait for it forever.
    return b""


def server_context(cert_file, key_file) -> ssl.SSLContext:
    """A TLS 1.2+ server context for this certificate chain and key (both PEM, one file allowed)."""
    _check_file(cert_file)
    _check_file(key_file)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(cert_file, key_file, password=_no_passphrase)
    except (ssl.SSLError, OSError, ValueError):
        # OpenSSL's message can quote the file; keep it out of logs and responses.
        raise TlsSettingsError("load_failed") from None
    return context


def listener_context(host, cert_file, key_file):
    """The context a listener on `host` must use: None on loopback, else a loaded certificate.

    Raises TlsSettingsError when `host` is beyond this PC and the certificate cannot be used,
    so no caller can open a plain listener there.
    """
    if not requires_tls(host):
        return None
    return server_context(cert_file, key_file)
