"""A short-lived helper exiting must not abort sidecar identity checks."""
from pathlib import Path
import sys
from types import SimpleNamespace

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform'))
from test_native_quick_chat import sidecars


def test_vanished_child_is_ignored_while_owned_sidecar_is_retained():
    def gone():
        raise psutil.NoSuchProcess(1)
    children = [SimpleNamespace(pid=1, exe=gone),
                SimpleNamespace(pid=2, exe=lambda: '/app/vrct-vox-sidecar')]
    ui = SimpleNamespace(app_process=SimpleNamespace(children=lambda **kwargs: children))
    assert sidecars(ui) == [2]


def test_missing_sidecar_is_not_invented_to_make_liveness_pass():
    ui = SimpleNamespace(app_process=SimpleNamespace(children=lambda **kwargs: []))
    assert sidecars(ui) == []
