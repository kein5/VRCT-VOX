"""SEC-02 and SEC-07: the backend refuses what the VR panel may not ask for.

The main window relays the VR panel's requests and marks them {"origin": "vr_panel"}. The UI
relays only VR_PANEL_RELAY_PATHS (src-ui/logics/common/vrPanelWire.js); the backend checks the
same list, so a slip in the UI or a compromised VR page still cannot reach anything else.
"""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import mainloop as mainloop_module
from mainloop import Main
from models.vr_panel_policy import VR_PANEL_ENDPOINTS, VR_PANEL_ORIGIN, request_allowed

WIRE = Path(__file__).resolve().parents[2] / "src-ui" / "logics" / "common" / "vrPanelWire.js"


def _ui_list():
    """VR_PANEL_RELAY_PATHS as the UI writes it: path strings and toggle("name") pairs."""
    source = WIRE.read_text(encoding="utf-8")
    block = source.split("export const VR_PANEL_RELAY_PATHS = new Set([", 1)[1].split("]);", 1)[0]
    block = re.sub(r"//[^\n]*", "", block)
    paths = set(re.findall(r'"(/(?:get|set|run)/[a-z0-9_/]+)"', block))
    for name in re.findall(r'toggle\("([a-z0-9_]+)"\)', block):
        paths |= {f"/set/enable/{name}", f"/set/disable/{name}"}
    return paths


def test_the_backend_and_the_ui_list_the_same_requests():
    assert _ui_list() == set(VR_PANEL_ENDPOINTS)


def test_every_listed_request_is_an_endpoint_the_backend_has():
    assert VR_PANEL_ENDPOINTS <= set(mainloop_module.mapping)


@pytest.mark.parametrize("endpoint", [
    "/set/enable/telemetry", "/set/disable/telemetry", "/set/data/telemetry_notice",  # SEC-07
    "/run/shutdown", "/run/update_software", "/run/open_filepath_logs", "/run/open_filepath_config_file",
    "/set/data/deepl_auth_key", "/get/data/deepl_auth_key", "/get/data/websocket_auth_token",
    "/run/regenerate_websocket_auth_token", "/set/data/websocket_host", "/set/data/websocket_tls",
    "/set/data/openai_compatible_url", "/set/data/osc_ip_address", "/set/data/voice_settings",
    "/run/start_model_download", "/run/start_vc_runtime_setup", "/set/data/a_setting_added_later",
])
def test_requests_outside_the_list_are_refused_for_the_vr_panel(endpoint):
    assert request_allowed(VR_PANEL_ORIGIN, endpoint) is False
    # The main window itself may still ask for them.
    assert request_allowed(None, endpoint) is True


def test_an_unknown_origin_is_refused_even_for_a_listed_request():
    assert request_allowed(VR_PANEL_ORIGIN, "/set/enable/translation") is True
    for origin in ("VR_PANEL", "quick_chat", "", 1, {"vr_panel": True}):
        assert request_allowed(origin, "/set/enable/translation") is False


def _receive(lines):
    """Feed stdin lines to Main.receiver; return (responses, queued requests, handler calls)."""
    handled, responses = [], []
    mapping = {endpoint: {"status": True, "variable": lambda data, endpoint=endpoint: handled.append(endpoint) or {"status": 200}}
               for endpoint in ("/set/enable/telemetry", "/set/enable/translation", "/set/data/deepl_auth_key")}
    main = Main(MagicMock(), mapping)
    feed = iter(json.dumps(line) + "\n" for line in lines)

    def readline():
        line = next(feed, "")
        if not line:
            main._stop_event.set()
        return line

    with patch.object(mainloop_module.sys.stdin, "readline", side_effect=readline), \
            patch.object(mainloop_module, "printLog"), patch.object(mainloop_module, "errorLogging"), \
            patch.object(mainloop_module, "printResponse", side_effect=lambda *args: responses.append(args)):
        main.receiver()
    queued = []
    while not main.queue.empty():
        queued.append(main.queue.get_nowait()[0])
    return responses, queued, handled


def test_the_receiver_refuses_a_relayed_request_outside_the_list_before_reading_its_data():
    # The data would not even decode; a refused request is not looked at.
    responses, queued, handled = _receive([
        {"endpoint": "/set/enable/telemetry", "origin": "vr_panel"},
        {"endpoint": "/set/data/deepl_auth_key", "origin": "vr_panel", "data": "not base64 at all"},
    ])
    assert responses == [
        (403, "/set/enable/telemetry", {"error_code": "vr_panel_request_refused"}),
        (403, "/set/data/deepl_auth_key", {"error_code": "vr_panel_request_refused"}),
    ]
    assert queued == [] and handled == []


def test_the_receiver_passes_listed_relayed_requests_and_the_main_windows_own():
    responses, queued, handled = _receive([
        {"endpoint": "/set/enable/translation", "origin": "vr_panel"},
        {"endpoint": "/set/enable/telemetry"},
    ])
    assert responses == []
    assert queued == ["/set/enable/translation", "/set/enable/telemetry"]
