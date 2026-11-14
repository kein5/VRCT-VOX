"""Helpers for the TLS tests: self-signed certificates made at test time (no key is
committed) and a relay that stands for someone watching the network path."""
import asyncio
import datetime
import ipaddress
import socket
import ssl
import threading

import pytest


def make_certificate(folder, *, ip="127.0.0.1", passphrase=None, name="server"):
    """Write <name>.pem and <name>-key.pem for `ip` into `folder`; return their paths."""
    x509 = pytest.importorskip("cryptography.x509")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "VRCT-VOX test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    encryption = (serialization.BestAvailableEncryption(passphrase) if passphrase
                  else serialization.NoEncryption())
    cert_file = folder / f"{name}.pem"
    key_file = folder / f"{name}-key.pem"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption))
    return str(cert_file), str(key_file)


def client_context(cert_file):
    """A client that trusts only this test certificate and checks the address in it."""
    return ssl.create_default_context(cafile=cert_file)


# wss:// in the tests goes through websockets' asyncio client. The sync client reads in a
# thread while the caller writes, both on one TLS connection; on Windows that loses data (the
# opening request never reached the server about one time in seven, and the process once
# died with an access violation). The server was not involved: raw ssl sockets and the asyncio
# client got every answer, 300 times in a row.
def wss_open(uri, context):
    """Open and close a wss:// connection. Raises what connecting raises (InvalidStatus, SSLError…)."""
    from websockets.asyncio.client import connect

    async def run():
        async with connect(uri, ssl=context, open_timeout=5):
            pass
    asyncio.run(run())


def wss_receive(uri, context, on_open):
    """Open a wss:// connection, run on_open() in a worker thread, and return the first message."""
    from websockets.asyncio.client import connect

    async def run():
        async with connect(uri, ssl=context, open_timeout=5) as client:
            await asyncio.to_thread(on_open)
            return await asyncio.wait_for(client.recv(), 5)
    return asyncio.run(run())


class Relay:
    """A passive observer on the path: forwards bytes both ways and keeps a copy of them.

    It listens on 127.0.0.1 and forwards to `target`, so the leg to the server crosses
    whatever interface the server listens on.
    """

    def __init__(self, target_port, target_host="127.0.0.1"):
        self.target = (target_host, target_port)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self._captured = bytearray()
        self._lock = threading.Lock()
        self._sockets = []
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def captured(self):
        with self._lock:
            return bytes(self._captured)

    def _accept(self):
        while True:
            try:
                downstream, _ = self.listener.accept()
            except OSError:
                return
            upstream = socket.create_connection(self.target)
            self._sockets += [downstream, upstream]
            for source, sink in ((downstream, upstream), (upstream, downstream)):
                threading.Thread(target=self._pump, args=(source, sink), daemon=True).start()

    def _pump(self, source, sink):
        try:
            while data := source.recv(65536):
                with self._lock:
                    self._captured += data
                sink.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (source, sink):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        self.listener.close()
        for sock in self._sockets:
            sock.close()
