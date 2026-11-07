"""Public HTTPS only; never attach user credentials or execute downloaded content."""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import socket
from models.http_stream import InterruptibleSocket

HOSTS = frozenset(('huggingface.co', 'cdn-lfs.huggingface.co', 'cdn-lfs-us-1.hf.co',
                   'cdn-lfs-eu-1.hf.co', 'cas-bridge.xethub.hf.co', 'us.aws.cdn.hf.co'))


def validate_url(url, hosts=HOSTS):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in hosts or parts.port not in (None, 443)
            or parts.username is not None or parts.password is not None or parts.fragment
            or any(ord(c) < 32 for c in url)):
        raise ValueError('download_url_rejected')
    return url


class PublicRedirect(HTTPRedirectHandler):
    max_redirections = 5

    def __init__(self, hosts=HOSTS):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicResponse:
    """Interrupt a blocked CPython HTTP body without closing its buffered reader concurrently."""
    def __init__(self, response):
        self.response = response
        self.socket = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
        if self.socket is not None:
            self.socket = InterruptibleSocket(self.socket)
            response.fp.raw._sock = self.socket

    def read(self, size):
        # read1 returns available bytes; a slow trickle cannot trap a whole MiB read.
        return self.response.read1(size)

    def abort(self):
        if self.socket is not None:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.response.close()


def open_public(url, *, timeout=15, hosts=HOSTS):
    validate_url(url, hosts)
    opener = build_opener(ProxyHandler({}), PublicRedirect(hosts))
    response = opener.open(Request(url, headers={'User-Agent': 'VRCT-VOX-model-download/1',
                                                'Accept-Encoding': 'identity'}), timeout=timeout)
    if response.status != 200:
        response.close()
        raise ValueError('download_http_error')
    return PublicResponse(response)


class _NoProbeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('download_probe_redirect')


def probe_download_host(*, timeout=3):
    """No body, credentials, proxies or redirects; the artifact policy is unchanged."""
    url = validate_url('https://huggingface.co/')
    opener = build_opener(ProxyHandler({}), _NoProbeRedirect())
    try:
        with opener.open(Request(url, method='HEAD', headers={
                'User-Agent': 'VRCT-VOX-model-download/1'}), timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False
