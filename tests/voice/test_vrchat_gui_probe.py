"""Reject wrong GUI states and incomplete capture, rather than sending blind clicks."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.vrchat_gui_probe import image_score, capture_valid, require_focus


def test_flat_image_does_not_match_an_expected_button():
    assert image_score(bytes([30] * 6), bytes([0, 30, 100, 0, 50, 200])) == 0


def test_same_shape_matches_despite_brightness_offset():
    assert image_score(bytes([10, 30, 80, 20]), bytes([30, 50, 100, 40])) > .99


def test_incomplete_or_stalled_recording_is_not_a_valid_silent_capture():
    assert not capture_valid(48000, 3, 3, 0.02, 48000)
    assert not capture_valid(48000 * 3, 3, 3, 1.0, 48000)
    assert not capture_valid(48000 * 3, 3, 1, .02, 48000)
    assert capture_valid(48000 * 3, 3, 3, .02, 48000)


def test_wrong_focus_aborts_before_input():
    with pytest.raises(RuntimeError, match='focus_changed'):
        require_focus('expected', lambda: 'other')


def test_ambiguous_visual_state_is_rejected():
    from tools.vrchat_gui_probe import state_matches
    assert not state_matches({'ready': .85, 'recording': .82}, 'ready')
    assert state_matches({'ready': .86, 'recording': .52}, 'ready')
