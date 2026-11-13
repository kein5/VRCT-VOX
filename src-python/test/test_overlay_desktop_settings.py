"""The desktop caption overlay is a UI window; the backend keeps its switch and its look."""

import ast
import functools
import json
from unittest.mock import Mock

import pytest

from errors import ErrorCode, VRCTError
from test_config_persistence_regressions import SOURCE, definitions, isolated  # noqa: F401

DEFAULT = {"position": "bottom", "font_size": 28, "display_duration": 6, "opacity": 0.6}


@pytest.fixture
def controller(isolated):  # noqa: F811 - imported pytest fixture
    ns = dict(config=isolated.config, ConfigValidationError=isolated.ns["ConfigValidationError"],
              ErrorCode=ErrorCode, VRCTError=VRCTError, functools=functools, printLog=Mock())
    path = SOURCE / "controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_configValidationErrorResponse"]
    exec(compile(tree, str(path), "exec"), ns)
    definitions("controller.py", ns, class_methods={
        "setEnableOverlayDesktop", "setDisableOverlayDesktop", "setOverlayDesktopSettings"})
    return ns["Controller"]()


def test_overlay_is_off_until_the_user_turns_it_on(isolated, controller):  # noqa: F811
    config = isolated.config
    assert config.OVERLAY_DESKTOP is False
    assert config.OVERLAY_DESKTOP_SETTINGS == DEFAULT
    assert controller.setEnableOverlayDesktop() == {"status": 200, "result": True}
    assert config.OVERLAY_DESKTOP is True
    assert controller.setDisableOverlayDesktop() == {"status": 200, "result": False}
    assert config.OVERLAY_DESKTOP is False


def test_look_is_saved_and_survives_a_reload(isolated, controller):  # noqa: F811
    config = isolated.config
    wanted = {"position": "top", "font_size": 40, "display_duration": 12, "opacity": 0.25}
    assert controller.setOverlayDesktopSettings(wanted) == {"status": 200, "result": wanted}
    controller.setEnableOverlayDesktop()
    config.saveConfigToFile()
    saved = json.loads(isolated.path.read_text(encoding="utf-8"))
    assert saved["OVERLAY_DESKTOP"] is True and saved["OVERLAY_DESKTOP_SETTINGS"] == wanted
    config._OVERLAY_DESKTOP = False
    config._OVERLAY_DESKTOP_SETTINGS = dict(DEFAULT)
    config.load_config()
    assert config.OVERLAY_DESKTOP is True and config.OVERLAY_DESKTOP_SETTINGS == wanted


@pytest.mark.parametrize("field, value", [
    ("position", "left"), ("position", 1),
    ("font_size", 15), ("font_size", 73), ("font_size", 28.5),
    ("display_duration", 0), ("display_duration", 61),
    ("opacity", -0.1), ("opacity", 1.5),
])
def test_a_value_out_of_range_keeps_the_current_one(isolated, controller, field, value):  # noqa: F811
    response = controller.setOverlayDesktopSettings({**DEFAULT, field: value})
    assert response == {"status": 200, "result": DEFAULT}
    assert isolated.config.OVERLAY_DESKTOP_SETTINGS == DEFAULT


@pytest.mark.parametrize("damage", [
    None, [], "bottom", {}, {"position": "top"}, {**DEFAULT, "extra": 1},
    {**DEFAULT, "opacity": float("nan")}, {**DEFAULT, "font_size": True},
])
def test_a_malformed_object_is_refused_without_changing_anything(isolated, controller, damage):  # noqa: F811
    response = controller.setOverlayDesktopSettings(damage)
    assert response["status"] == 400
    assert response["result"]["error_code"] == "VALIDATION_CONFIG_VALUE_INVALID"
    assert isolated.config.OVERLAY_DESKTOP_SETTINGS == DEFAULT
