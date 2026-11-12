"""OSC delivery and owned, local-only OSCQuery receive/discovery resources."""

import ipaddress
import re
import socket
import time
from http.server import HTTPServer
from threading import Event, Lock, RLock, Thread, Timer
from types import SimpleNamespace
from typing import Callable, Dict, Optional

from pythonosc import udp_client, dispatcher, osc_packet, osc_server
try:
    from tinyoscquery.queryservice import OSCQueryService, OSCQueryHTTPHandler
    from tinyoscquery.query import OSCQueryBrowser, OSCQueryListener
    from tinyoscquery.shared.node import OSCQueryNode, OSCHostInfo, OSCAccess
    from zeroconf import ServiceBrowser, Zeroconf
    import requests
except ImportError:
    OSCQueryService = None
    OSCQueryBrowser = None
    OSCQueryHTTPHandler = object

try:
    from utils import errorLogging, printLog
except ImportError:
    def errorLogging():
        import traceback
        traceback.print_exc()

    def printLog(log, data=None):
        print(log, data)


OSC_QUERY_TIMEOUT_SECONDS = 2.0
OSC_STOP_TIMEOUT_SECONDS = 2.0
OSC_HTTP_REQUEST_TIMEOUT_SECONDS = 2.0
LOOPBACK = "127.0.0.1"


def usesOscQuery(ip_address) -> bool:
    """OSCQuery (receiving and advertising) runs only when VRChat is on this PC.

    A destination on another machine, such as a standalone headset, is a choice
    the user made in settings, not a failure.
    """
    return ip_address in (LOOPBACK, "localhost")


class ImmediateDispatcher(dispatcher.Dispatcher):
    """VRChat state packets are applied on receipt, including bundle contents."""

    def call_handlers_for_packet(self, data, client_address):
        results = []
        try:
            for message in osc_packet.OscPacket(data).messages:
                for handler in self.handlers_for_address(message.message.address):
                    result = handler.invoke(client_address, message.message)
                    if result is not None:
                        results.append(result)
        except osc_packet.ParseError:
            pass
        return results


class DeadlineOSCQueryHTTPHandler(OSCQueryHTTPHandler):
    def setup(self):
        self.request.settimeout(OSC_HTTP_REQUEST_TIMEOUT_SECONDS)
        super().setup()
        # An absolute deadline also stops a peer that drips partial headers.
        self._read_deadline = Timer(OSC_HTTP_REQUEST_TIMEOUT_SECONDS, self._expireRequest)
        self._read_deadline.daemon = True
        self._read_deadline.start()

    def _expireRequest(self):
        try:
            self.request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        self._read_deadline.cancel()
        super().finish()


class LocalOSCQueryService(OSCQueryService if OSCQueryService is not None else object):
    """Use tinyoscquery's metadata API, but own construction and all cleanup.

    Construction is inert; the lifecycle owner publishes this object before
    start(), so every partially acquired resource remains reachable on failure.
    """

    def __init__(self):
        self.http_server = None
        self.http_thread = None
        self._zeroconf = None

    def start(self, server_name, osc_port):
        self.serverName = server_name
        self.oscIp = LOOPBACK
        self.oscPort = osc_port
        self.root_node = OSCQueryNode("/", description="root node")
        self.host_info = OSCHostInfo(server_name, {
            "ACCESS": True, "CLIPMODE": False, "RANGE": True, "TYPE": True, "VALUE": True,
        }, LOOPBACK, osc_port, "UDP")
        # Assign ownership before bind/activate, including failures in bind.
        self.http_server = HTTPServer((LOOPBACK, 0), DeadlineOSCQueryHTTPHandler, bind_and_activate=False)
        self.http_server.root_node = self.root_node
        self.http_server.host_info = self.host_info
        self.http_server.server_bind()
        self.http_server.server_activate()
        self.httpPort = self.http_server.server_address[1]
        self.http_thread = Thread(target=self.http_server.serve_forever, args=(0.1,),
                                  name="osc_query_http", daemon=True)
        self.http_thread.start()
        self._zeroconf = Zeroconf()
        self._startOSCQueryService()
        self._advertiseOSCService()

    def close(self):
        # Called only by the bounded cleanup worker. Always attempt every owner.
        try:
            if self._zeroconf is not None:
                try:
                    self._zeroconf.unregister_all_services()
                finally:
                    self._zeroconf.close()
        finally:
            if self.http_server is not None:
                try:
                    if self.http_thread is not None and self.http_thread.is_alive():
                        self.http_server.shutdown()
                        self.http_thread.join()
                finally:
                    self.http_server.server_close()

    def __del__(self):
        # The dependency's destructor only unregisters, and races explicit close.
        pass


class LocalOSCQueryBrowser(OSCQueryBrowser if OSCQueryBrowser is not None else object):
    def __init__(self):
        self.zc = None
        self.browser = None

    def start(self):
        self.listener = OSCQueryListener()
        self.zc = Zeroconf()
        self.browser = ServiceBrowser(self.zc, ["_oscjson._tcp.local."], self.listener)

    def close(self):
        try:
            if self.browser is not None:
                self.browser.cancel()
        finally:
            if self.zc is not None:
                self.zc.close()


class OSCQueryClient:
    """Query a validated numeric loopback address without redirects or proxies."""

    def __init__(self, service):
        self.root = f"http://{ipaddress.ip_address(service.addresses[0])}:{service.port}"

    def _get(self, path):
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(self.root + path, timeout=OSC_QUERY_TIMEOUT_SECONDS, allow_redirects=False)
            if response.status_code != 200:
                return None
            return response.json()

    def get_host_info(self):
        value = self._get("/HOST_INFO")
        return SimpleNamespace(name=value.get("NAME"), osc_ip=value.get("OSC_IP"),
                               osc_port=value.get("OSC_PORT"), osc_transport=value.get("OSC_TRANSPORT")) if value else None

    def query_node(self, address):
        value = self._get(address)
        # Do not coerce OSCQuery values: bool("false") would authorize an invalid state.
        return SimpleNamespace(value=value.get("VALUE")) if value else None


class OSCHandler:
    def __init__(self, ip_address: str = LOOPBACK, port: int = 9000) -> None:
        self._lifecycle_lock = RLock()
        self._shutdown = False
        self._generation = 0
        self._cleanup_thread = None
        self._cleanup_failed = False
        self._query_cancel = Event()
        self._parameter_query_lock = Lock()
        self.is_osc_query_enabled = False
        self.osc_ip_address = ip_address
        self.osc_port = port
        self.osc_server_ip_address = LOOPBACK
        self.osc_parameter_muteself = "/avatar/parameters/MuteSelf"
        self.osc_parameter_chatbox_typing = "/chatbox/typing"
        self.osc_parameter_chatbox_input = "/chatbox/input"
        self.udp_client = udp_client.SimpleUDPClient(ip_address, port)
        self.osc_server_name = "VRChat-Client"
        self.osc_query_service_name = "VRCT"
        self.osc_server = None
        self._receive_thread = None
        self.osc_query_service = None
        self.browser = None
        self.http_port = None
        self.osc_server_port = None
        self.dict_filter_and_target: Dict[str, Callable] = {}

    def getIsOscQueryEnabled(self):
        with self._lifecycle_lock:
            return self.is_osc_query_enabled and not self._shutdown

    def setOscIpAddress(self, ip_address):
        with self._lifecycle_lock:
            self._replaceLocked(ip_address, self.osc_port)

    def setOscPort(self, port):
        with self._lifecycle_lock:
            self._replaceLocked(self.osc_ip_address, port)

    def _replaceLocked(self, ip_address, port):
        if self._shutdown:
            raise RuntimeError("OSC is shut down")
        client = udp_client.SimpleUDPClient(ip_address, port)
        previous_ip = self.osc_ip_address
        try:
            self._stopLocked()
            try:
                self._startLocked(ip_address)
            except Exception:
                self._stopLocked()
                try:
                    self._startLocked(previous_ip)
                except Exception:
                    self._stopLocked()
                    printLog("OSC: previous receiver could not be restored")
                raise
        except Exception:
            client._sock.close()
            raise
        previous_client = self.udp_client
        self.udp_client = client
        self.osc_ip_address = ip_address
        self.osc_port = port
        previous_client._sock.close()

    def sendTyping(self, flag=False):
        with self._lifecycle_lock:
            if not self._shutdown:
                self.udp_client.send_message(self.osc_parameter_chatbox_typing, [flag])

    def sendMessage(self, message="", notification=True, current=None):
        if message:
            with self._lifecycle_lock:
                if not self._shutdown and (current is None or current()):
                    self.udp_client.send_message(self.osc_parameter_chatbox_input, [message, True, notification])
                    return True
        return False

    def getOSCParameterValue(self, address):
        deadline = time.monotonic() + OSC_QUERY_TIMEOUT_SECONDS
        if not self._lifecycle_lock.acquire(timeout=OSC_QUERY_TIMEOUT_SECONDS):
            return None
        try:
            if not self.is_osc_query_enabled or self._shutdown:
                return None
            generation = self._generation
            browser = self.browser
            cancel = self._query_cancel
            port = self.osc_port
        finally:
            self._lifecycle_lock.release()
        if not self._parameter_query_lock.acquire(blocking=False):
            printLog("OSCQuery: query got no value", {"address": address, "reason": "previous query still running"})
            return None
        done = Event()
        result = []
        def query():
            try:
                if not cancel.is_set():
                    result.append(self._queryOSCParameterValue(address, browser, cancel, port))
            except Exception:
                printLog("OSCQuery: parameter query failed", {"address": address})
            finally:
                self._parameter_query_lock.release()
                done.set()

        try:
            Thread(target=query, name="osc_parameter_query", daemon=True).start()
        except Exception:
            self._parameter_query_lock.release()
            return None
        if not done.wait(max(0, deadline - time.monotonic())) or time.monotonic() >= deadline:
            printLog("OSCQuery: query timed out", {"address": address})
            return None
        if generation != self._generation or cancel.is_set():
            return None
        return result[0] if result else None

    @staticmethod
    def _localServiceName(service):
        if service is None or service.type != "_oscjson._tcp.local.":
            return None
        addresses = service.addresses
        if not addresses or not all(ipaddress.IPv4Address(a).is_loopback for a in addresses):
            return None
        suffix = "._oscjson._tcp.local."
        if not service.name.endswith(suffix):
            return None
        name = service.name[:-len(suffix)]
        return name if re.fullmatch(r"VRChat-Client(?:[-:][A-Za-z0-9_-]+)?", name) else None

    def _queryOSCParameterValue(self, address, browser, cancel, port):
        # The browser belongs to receive startup. A query can never create it.
        if browser is None or cancel.is_set():
            return None
        services = browser.get_discovered_oscquery()
        if not services:
            # Allow initial mDNS discovery within the same two-second deadline.
            if cancel.wait(1.0):
                return None
            services = browser.get_discovered_oscquery()
        candidates = []
        for service in services:
            try:
                name = self._localServiceName(service)
                if name is None or cancel.is_set():
                    continue
                client = OSCQueryClient(service)
                host = client.get_host_info()
                if (host is not None and host.name == name
                        and ipaddress.ip_address(host.osc_ip).is_loopback
                        and host.osc_port == port and host.osc_transport == "UDP"):
                    candidates.append(client)
            except (ValueError, TypeError, AttributeError):
                continue
        # Ambiguous local identities cannot establish which client owns the mic.
        if len(candidates) != 1 or cancel.is_set():
            return None
        node = candidates[0].query_node(address)
        values = getattr(node, "value", None)
        return values[0] if isinstance(values, list) and values else None

    def getOSCParameterMuteSelf(self) -> Optional[bool]:
        value = self.getOSCParameterValue(self.osc_parameter_muteself)
        return value if type(value) is bool else None

    def setDictFilterAndTarget(self, dict_filter_and_target):
        with self._lifecycle_lock:
            self.dict_filter_and_target = dict_filter_and_target

    def receiveOscParameters(self):
        with self._lifecycle_lock:
            if self._shutdown:
                raise RuntimeError("OSC is shut down")
            if self.is_osc_query_enabled:
                return
            self._stopLocked()
            try:
                self._startLocked(self.osc_ip_address)
            except Exception:
                self._stopLocked()
                raise

    def _startLocked(self, ip_address):
        if self._shutdown:
            raise RuntimeError("OSC is shut down")
        if not usesOscQuery(ip_address):
            return
        if OSCQueryService is None or OSCQueryBrowser is None:
            raise RuntimeError("OSCQuery is unavailable")
        self._query_cancel = Event()
        osc_dispatcher = ImmediateDispatcher()
        for address, target in self.dict_filter_and_target.items():
            osc_dispatcher.map(address, target)
        self.osc_server = osc_server.BlockingOSCUDPServer((LOOPBACK, 0), osc_dispatcher)
        self.osc_server_port = self.osc_server.server_address[1]
        # Capture this server, never look up a mutable field in the receive thread.
        self._receive_thread = Thread(target=self.oscServerServe, args=(self.osc_server,),
                                      name="osc_receive", daemon=True)
        self._receive_thread.start()
        self.osc_query_service = LocalOSCQueryService()
        self.osc_query_service.start(f"{self.osc_query_service_name}:{time.time_ns()}", self.osc_server_port)
        self.http_port = self.osc_query_service.httpPort
        for address in self.dict_filter_and_target:
            self.osc_query_service.advertise_endpoint(address, access=OSCAccess.READWRITE_VALUE)
        self.browser = LocalOSCQueryBrowser()
        self.browser.start()
        if self._shutdown:
            raise RuntimeError("OSC is shut down")
        self.is_osc_query_enabled = True

    def oscServerServe(self, server):
        server.serve_forever(0.1)

    def _stopLocked(self):
        self.is_osc_query_enabled = False
        self._generation += 1
        self._query_cancel.set()
        if self._cleanup_thread is None:
            self._cleanup_failed = False

            def cleanup():
                actions = []
                if self.osc_server is not None:
                    def stop_receiver():
                        try:
                            if self._receive_thread is not None and self._receive_thread.is_alive():
                                self.osc_server.shutdown()
                                self._receive_thread.join()
                        finally:
                            self.osc_server.server_close()
                    actions.append(stop_receiver)
                if self.osc_query_service is not None:
                    actions.append(self.osc_query_service.close)
                if self.browser is not None:
                    actions.append(self.browser.close)
                def close_owner(action):
                    try:
                        action()
                    except Exception:
                        self._cleanup_failed = True
                        printLog("OSC: resource cleanup failed")

                workers = [Thread(target=close_owner, args=(action,), daemon=True,
                                  name="osc_close_owner") for action in actions]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()
                if self._shutdown:
                    self.udp_client._sock.close()

            self._cleanup_thread = Thread(target=cleanup, name="osc_cleanup", daemon=True)
            self._cleanup_thread.start()
        self._cleanup_thread.join(OSC_STOP_TIMEOUT_SECONDS)
        if self._cleanup_thread.is_alive() or self._cleanup_failed:
            # Keep every owner and prohibit replacements until cleanup completes.
            raise RuntimeError("OSC cleanup did not complete")
        self._cleanup_thread = None
        self.osc_server = None
        self._receive_thread = None
        self.osc_query_service = None
        self.browser = None

    def requestStop(self):
        self._shutdown = True
        self._query_cancel.set()

    def oscServerStop(self):
        self.requestStop()
        if not self._lifecycle_lock.acquire(timeout=OSC_STOP_TIMEOUT_SECONDS):
            raise RuntimeError("OSC startup still owns lifecycle resources")
        try:
            self._stopLocked()
        finally:
            self.udp_client._sock.close()
            self._lifecycle_lock.release()
