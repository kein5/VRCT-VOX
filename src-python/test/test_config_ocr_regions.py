"""Single-region migration and independent persistence with fake config dependencies."""

import json

import pytest

from test_config_persistence_regressions import isolated  # noqa: F401


WINDOW = {"x": 0.6, "y": 0.1, "width": 0.2, "height": 0.2}
VR = {"x": 0.1, "y": 0.5, "width": 0.3, "height": 0.4}
FULL = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}


@pytest.mark.parametrize("saved, window, vr", [
    ({}, FULL, FULL),
    ({"OCR_CAPTURE_REGION": WINDOW}, WINDOW, FULL),
    ({"OCR_CAPTURE_REGION": WINDOW, "OCR_VR_CAPTURE_REGION": VR}, WINDOW, VR),
    ({"OCR_CAPTURE_REGION": {"x": 9}, "OCR_VR_CAPTURE_REGION": VR}, FULL, VR),
    ({"OCR_CAPTURE_REGION": WINDOW, "OCR_VR_CAPTURE_REGION": {"width": 9}}, WINDOW, FULL),
])
def test_region_migration_preserves_window_and_never_copies_it_to_vr(isolated, saved, window, vr):
    isolated.path.write_text(json.dumps(saved), encoding="utf-8")
    isolated.config.load_config()
    assert isolated.config.OCR_CAPTURE_REGION == window
    assert isolated.config.OCR_VR_CAPTURE_REGION == vr
    persisted = json.loads(isolated.path.read_text(encoding="utf-8"))
    assert persisted["OCR_CAPTURE_REGION"] == window
    assert persisted["OCR_VR_CAPTURE_REGION"] == vr
    isolated.config.load_config()
    assert isolated.config.OCR_CAPTURE_REGION == window
    assert isolated.config.OCR_VR_CAPTURE_REGION == vr


def test_each_region_round_trips_after_editing(isolated):
    config = isolated.config
    config.OCR_CAPTURE_REGION = WINDOW
    config.OCR_VR_CAPTURE_REGION = VR
    config.saveConfigToFile()
    config.OCR_CAPTURE_REGION = FULL
    config.OCR_VR_CAPTURE_REGION = FULL
    config.load_config()
    assert config.OCR_CAPTURE_REGION == WINDOW
    assert config.OCR_VR_CAPTURE_REGION == VR
    config.OCR_VR_CAPTURE_REGION = FULL
    config.saveConfigToFile()
    saved = json.loads(isolated.path.read_text(encoding="utf-8"))
    assert saved["OCR_CAPTURE_REGION"] == WINDOW
    assert saved["OCR_VR_CAPTURE_REGION"] == FULL
