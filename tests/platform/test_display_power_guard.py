"""Display preconditions must not turn an invalid GUI run into a pass."""
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import display_power_guard as guard


def test_only_connected_connectors_with_known_on_state_are_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "DRM", tmp_path)
    for name, status, power in [("card0-DP-1", "connected", "On"),
                                ("card0-DP-2", "disconnected", "Off")]:
        connector = tmp_path / name
        connector.mkdir()
        (connector / "status").write_text(status)
        (connector / "dpms").write_text(power)
    assert guard.connected_outputs() == {"card0-DP-1": "On"}
    assert guard.displays_on()
    (tmp_path / "card0-DP-1" / "dpms").unlink()
    assert not guard.displays_on()
    for state in [{}, {"DP-1": "Off"}, {"DP-1": "Unknown"},
                  {"DP-1": "On", "DP-2": "Off"}]:
        assert not guard.displays_on(state)


@pytest.mark.parametrize("arguments", [
    ["--hold", "0.01", "--poll", "0.01"],
    ["--", sys.executable, "-c", "pass"],
])
def test_loss_of_display_power_invalidates_success(arguments, monkeypatch, capsys):
    monkeypatch.setattr(guard, "Inhibitor", lambda: nullcontext(SimpleNamespace(kind="test")))
    monkeypatch.setattr(guard, "require_displays_on", lambda: {"DP-1": "On"})
    monkeypatch.setattr(guard, "connected_outputs", lambda: {"DP-1": "Off"})
    monkeypatch.setattr(sys, "argv", ["display_power_guard", *arguments])
    assert guard.main() == 2
    assert "display" in capsys.readouterr().err.lower()


def test_missing_dbus_binding_is_an_explicit_failure(monkeypatch):
    # A system idle inhibitor is not a verified replacement for KDE display inhibition.
    monkeypatch.setitem(sys.modules, "gi", None)
    with pytest.raises(RuntimeError, match="PyGObject"):
        with guard.Inhibitor():
            pytest.fail("GUI commands must not start without a verified inhibitor")


def test_guard_preserves_child_failure(monkeypatch):
    monkeypatch.setattr(guard, "Inhibitor", lambda: nullcontext(SimpleNamespace(kind="test")))
    monkeypatch.setattr(guard, "require_displays_on", lambda: {"DP-1": "On"})
    monkeypatch.setattr(guard, "connected_outputs", lambda: {"DP-1": "On"})
    monkeypatch.setattr(sys, "argv", ["display_power_guard", "--", sys.executable, "-c", "raise SystemExit(7)"])
    assert guard.main() == 7


def test_power_recovery_does_not_erase_an_invalid_interval(monkeypatch):
    monkeypatch.setattr(guard, "Inhibitor", lambda: nullcontext(SimpleNamespace(kind="test")))
    monkeypatch.setattr(guard, "require_displays_on", lambda: {"DP-1": "On"})
    states = iter([{"DP-1": "On"}, {"DP-1": "Off"}])
    monkeypatch.setattr(guard, "connected_outputs", lambda: next(states, {"DP-1": "On"}))
    monkeypatch.setattr(sys, "argv", ["display_power_guard", "--poll", "0.01", "--",
                                     sys.executable, "-c", "import time; time.sleep(0.1)"])
    assert guard.main() == 2
