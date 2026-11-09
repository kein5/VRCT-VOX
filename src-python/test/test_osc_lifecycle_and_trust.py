"""OSC/OSCQuery trust and ownership, with no sockets or multicast."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder

from models.osc import osc
from osc_fakes import FakeServer, FakeZeroconf, fake_transports, local_service, prepare_query


def packet(value):
    builder = OscMessageBuilder(address="/mute")
    builder.add_arg(value)
    return builder.build()


def test_future_bundle_does_not_delay_a_later_packet():
    with fake_transports(), patch("pythonosc.dispatcher.time.sleep", side_effect=AssertionError("timetag sleep")):
        handler = osc.OSCHandler()
        seen = []
        done = threading.Event()
        handler.setDictFilterAndTarget({"/mute": lambda address, value: (seen.append(value), done.set() if len(seen) == 2 else None)})
        handler.receiveOscParameters()
        try:
            bundle = OscBundleBuilder(time.time() + 3600)
            bundle.add_content(packet(True))
            handler.osc_server.packets.put(bundle.build().dgram)
            handler.osc_server.packets.put(packet(False).dgram)
            assert done.wait(1)
            assert seen == [True, False]
        finally:
            handler.oscServerStop()


@pytest.mark.parametrize("service", [
    local_service(ip=b"\xc0\xa8\x01\x05"),
    local_service(name="fake-VRChat-Client"),
    local_service(name="VRChat-ClientSpoof"),
    SimpleNamespace(type="_oscjson._tcp.local.", name="VRChat-Client._oscjson._tcp.local.", addresses=[], port=32000),
    local_service(ip=b"\0" * 15 + b"\x01"),
])
def test_nonlocal_or_spoofed_service_is_ignored_before_http(service):
    with fake_transports(), patch.object(osc, "OSCQueryClient") as client:
        handler = osc.OSCHandler()
        prepare_query(handler, client)
        handler.browser.get_discovered_oscquery.return_value = [service]
        assert handler.getOSCParameterMuteSelf() is None
        client.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"name": "VRChat-Client-other"}, {"osc_ip": "192.168.1.5"},
    {"osc_port": 9001}, {"osc_transport": "TCP"},
])
def test_host_identity_must_match_the_local_service_and_destination(changes):
    with fake_transports(), patch.object(osc, "OSCQueryClient") as client:
        handler = osc.OSCHandler()
        prepare_query(handler, client)
        for key, value in changes.items():
            setattr(client.return_value.get_host_info.return_value, key, value)
        assert handler.getOSCParameterMuteSelf() is None
        client.return_value.query_node.assert_not_called()


def test_lan_false_cannot_win_over_local_true():
    with fake_transports(), patch.object(osc, "OSCQueryClient") as client:
        handler = osc.OSCHandler()
        local = prepare_query(handler, client)
        handler.browser.get_discovered_oscquery.return_value = [local_service(ip=b"\xc0\xa8\x01\x05"), local]
        client.return_value.query_node.return_value = SimpleNamespace(value=[True])
        assert handler.getOSCParameterMuteSelf() is True
        client.assert_called_once_with(local)


def test_ambiguous_local_services_cannot_authorize_unmute():
    with fake_transports(), patch.object(osc, "OSCQueryClient") as client:
        handler = osc.OSCHandler()
        local = prepare_query(handler, client)
        handler.browser.get_discovered_oscquery.return_value = [local, local]
        assert handler.getOSCParameterMuteSelf() is None
        client.return_value.query_node.assert_not_called()


def test_query_disables_redirects_proxies_and_preserves_raw_booleans():
    with patch.object(osc.requests, "Session") as session:
        response = session.return_value.__enter__.return_value.get.return_value
        response.status_code = 200
        response.json.return_value = {"VALUE": ["false"]}
        client = osc.OSCQueryClient(local_service())
        assert client.query_node("/mute").value == ["false"]
        owner = session.return_value.__enter__.return_value
        assert owner.trust_env is False
        owner.get.assert_called_once_with("http://127.0.0.1:32000/mute", timeout=2.0, allow_redirects=False)


def test_overlapping_ip_and_port_setters_have_one_receiver():
    with fake_transports():
        handler = osc.OSCHandler()
        handler.receiveOscParameters()
        old = handler.osc_server
        entered, release = threading.Event(), threading.Event()
        original = osc.LocalOSCQueryService.start

        def blocked_start(service, *args):
            entered.set()
            assert release.wait(2)
            return original(service, *args)

        with patch.object(osc.LocalOSCQueryService, "start", blocked_start), ThreadPoolExecutor(2) as executor:
            first = executor.submit(handler.setOscIpAddress, "127.0.0.1")
            assert entered.wait(1)
            second = executor.submit(handler.setOscPort, 9001)
            assert not second.done()
            release.set()
            first.result(2)
            second.result(2)
        active = [server for server in FakeServer.instances if not server.closed]
        assert len(active) == 2  # one UDP receiver and its HTTP server
        assert old.stopped.is_set() and old.closed
        assert handler.osc_port == 9001
        assert handler.osc_server in active
        assert all(z.closed for z in FakeZeroconf.instances[:-2])
        handler.oscServerStop()
        assert all(s.closed for s in FakeServer.instances)
        assert all(z.closed for z in FakeZeroconf.instances)
        with pytest.raises(RuntimeError, match="shut down"):
            handler.receiveOscParameters()
        with pytest.raises(RuntimeError, match="shut down"):
            handler.setOscPort(9002)


def test_target_returns_to_loopback_receive_bind():
    with fake_transports():
        handler = osc.OSCHandler("192.0.2.5")
        handler.receiveOscParameters()
        assert not handler.getIsOscQueryEnabled()
        handler.setOscIpAddress("127.0.0.1")
        assert handler.osc_server.address == ("127.0.0.1", 0)
        assert handler.osc_query_service.http_server.address == ("127.0.0.1", 0)
        assert handler.getIsOscQueryEnabled()
        handler.oscServerStop()


def test_failed_replacement_restores_old_destination_and_one_receiver():
    with fake_transports():
        handler = osc.OSCHandler()
        handler.receiveOscParameters()
        original = osc.LocalOSCQueryService.start
        attempts = []

        def fail_once(service, *args):
            attempts.append(service)
            if len(attempts) == 1:
                raise OSError("replacement failed")
            original(service, *args)

        with patch.object(osc.LocalOSCQueryService, "start", fail_once):
            with pytest.raises(OSError):
                handler.setOscPort(9001)
        assert handler.osc_port == 9000
        assert handler.getIsOscQueryEnabled()
        assert len([s for s in FakeServer.instances if not s.closed]) == 2
        handler.oscServerStop()


@pytest.mark.parametrize("stage", ["bind", "register", "endpoint", "browser"])
def test_partial_failure_closes_every_acquired_owner(stage):
    with fake_transports():
        handler = osc.OSCHandler()
        handler.setDictFilterAndTarget({"/mute": lambda *args: None})
        target = {
            "bind": (FakeServer, "server_bind"),
            "register": (FakeZeroconf, "register_service"),
            "endpoint": (osc.LocalOSCQueryService, "advertise_endpoint"),
            "browser": (osc, "ServiceBrowser"),
        }[stage]
        with patch.object(*target, side_effect=OSError("partial failure")):
            with pytest.raises(OSError):
                handler.receiveOscParameters()
        assert not handler.getIsOscQueryEnabled()
        assert all(s.closed for s in FakeServer.instances)
        assert all(z.closed for z in FakeZeroconf.instances)
        assert all(z.unregistered for z in FakeZeroconf.instances[:1])
        handler.oscServerStop()


def test_stop_timeout_retains_owners_and_prevents_replacement():
    with fake_transports(), patch.object(osc, "OSC_STOP_TIMEOUT_SECONDS", 0.02):
        handler = osc.OSCHandler()
        handler.receiveOscParameters()
        server, service, browser = handler.osc_server, handler.osc_query_service, handler.browser
        release = threading.Event()
        shutdown = server.shutdown
        server.shutdown = lambda: (release.wait(2), shutdown())
        try:
            before = time.monotonic()
            with pytest.raises(RuntimeError, match="cleanup"):
                handler.setOscPort(9001)
            assert time.monotonic() - before < 0.5
            assert handler.osc_server is server
            assert handler.osc_query_service is service
            assert handler.browser is browser
            count = len(FakeServer.instances)
            with pytest.raises(RuntimeError, match="cleanup"):
                handler.setOscPort(9002)
            assert len(FakeServer.instances) == count
            assert handler.osc_port == 9000
        finally:
            release.set()
            handler._cleanup_thread.join(2)
            handler.oscServerStop()


def test_http_has_an_absolute_request_deadline():
    handler = object.__new__(osc.DeadlineOSCQueryHTTPHandler)
    handler.request = MagicMock()
    with (patch.object(osc.OSCQueryHTTPHandler, "setup"),
          patch.object(osc.OSCQueryHTTPHandler, "finish"),
          patch.object(osc, "Timer") as timer):
        handler.setup()
        timer.assert_called_once_with(2.0, handler._expireRequest)
        handler.request.settimeout.assert_called_once_with(2.0)
        handler._expireRequest()
        handler.request.shutdown.assert_called_once_with(osc.socket.SHUT_RDWR)
        handler.finish()
        timer.return_value.cancel.assert_called_once()


def test_stopped_query_never_creates_a_browser_or_applies_a_late_result():
    with fake_transports(), patch.object(osc, "OSCQueryClient") as client:
        handler = osc.OSCHandler()
        handler.receiveOscParameters()
        browser = handler.browser
        browser.listener.oscjson_services = {"local": local_service()}
        client.return_value.get_host_info.return_value = SimpleNamespace(
            name="VRChat-Client-test", osc_ip="127.0.0.1", osc_port=9000, osc_transport="UDP")
        entered, release = threading.Event(), threading.Event()
        client.return_value.query_node.side_effect = lambda address: (entered.set(), release.wait(2), SimpleNamespace(value=[False]))[-1]
        with ThreadPoolExecutor(1) as executor:
            query = executor.submit(handler.getOSCParameterMuteSelf)
            assert entered.wait(1)
            count = len(FakeZeroconf.instances)
            handler.oscServerStop()
            release.set()
            assert query.result(1) is None
        assert browser.zc.closed
        assert handler.getOSCParameterMuteSelf() is None
        assert len(FakeZeroconf.instances) == count


def test_shutdown_during_startup_is_bounded_and_late_resources_are_closed():
    with fake_transports():
        handler = osc.OSCHandler()
        entered, release = threading.Event(), threading.Event()
        original = osc.LocalOSCQueryService.start

        def delayed_start(service, *args):
            entered.set()
            assert release.wait(2)
            original(service, *args)

        with patch.object(osc.LocalOSCQueryService, "start", delayed_start), ThreadPoolExecutor(1) as executor:
            start = executor.submit(handler.receiveOscParameters)
            assert entered.wait(1)
            server = handler.osc_server
            before = time.monotonic()
            try:
                # Only the refused stop is bounded here. The cleanup after the
                # release runs with the normal limit, or a slow machine reports
                # a cleanup timeout in place of the shutdown.
                with patch.object(osc, "OSC_STOP_TIMEOUT_SECONDS", 0.02), pytest.raises(RuntimeError, match="startup"):
                    handler.oscServerStop()
                assert time.monotonic() - before < 0.5
                assert handler.osc_server is server
            finally:
                release.set()
            with pytest.raises(RuntimeError, match="shut down"):
                start.result(5)
        assert not handler.getIsOscQueryEnabled()
        assert all(s.closed for s in FakeServer.instances)
        assert all(z.closed for z in FakeZeroconf.instances)
        handler.udp_client._sock.close.assert_called()


def test_failed_rollback_also_closes_partial_resources():
    with fake_transports():
        handler = osc.OSCHandler()
        handler.receiveOscParameters()
        with patch.object(FakeZeroconf, "register_service", side_effect=OSError("offline")):
            with pytest.raises(OSError):
                handler.setOscPort(9001)
        assert handler.osc_port == 9000
        assert not handler.getIsOscQueryEnabled()
        assert all(s.closed for s in FakeServer.instances)
        assert all(z.closed for z in FakeZeroconf.instances)
        handler.oscServerStop()
