"""Detector-free bubble finding on synthetic frames (models.ocr.ocr_detection)."""

import unittest

import numpy as np

from models.ocr.ocr_detection import (
    FULL_REGION,
    RegionCandidates,
    blockBounds,
    groupLines,
    looksLikeChatbox,
    normalizeRegion,
    regionPixels,
)
from ocr_synthetic import Scene


class TestRegion(unittest.TestCase):
    def test_dict_and_sequence_forms(self) -> None:
        self.assertEqual(normalizeRegion({"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.4}), (0.1, 0.2, 0.5, 0.4))
        self.assertEqual(normalizeRegion([0, 0, 1, 1]), FULL_REGION)

    def test_out_of_frame_values_are_clamped_inside(self) -> None:
        x, y, w, h = normalizeRegion((0.9, -1.0, 0.5, 3.0))
        self.assertAlmostEqual(x + w, 1.0)
        self.assertEqual(y, 0.0)
        self.assertAlmostEqual(h, 1.0)

    def test_garbage_falls_back_to_the_whole_window(self) -> None:
        for value in (None, "top", {"x": 0}, (0, 0, float("nan"), 1), {"x": "a", "y": 0, "width": 1, "height": 1}):
            self.assertEqual(normalizeRegion(value), FULL_REGION, value)

    def test_pixels(self) -> None:
        self.assertEqual(regionPixels((0.25, 0.5, 0.5, 0.25), 1280, 720), (320, 360, 640, 180))
        self.assertEqual(regionPixels(FULL_REGION, 7, 5), (0, 0, 7, 5))


class TestRegionCandidates(unittest.TestCase):
    def test_returns_the_configured_part_of_the_frame(self) -> None:
        frame = np.arange(720 * 1280 * 3, dtype=np.uint32).reshape(720, 1280, 3).astype(np.uint8)
        source = RegionCandidates((0.25, 0.5, 0.5, 0.25))
        [(bbox, crop)] = source.detect(frame)
        self.assertEqual(bbox, (320, 360, 640, 180))
        np.testing.assert_array_equal(crop, frame[360:540, 320:960])
        self.assertTrue(source.splits_bubbles)
        self.assertTrue(source.isAvailable())

    def test_very_large_windows_are_downscaled_for_ocr(self) -> None:
        frame = np.zeros((2160, 3840, 3), np.uint8)
        [(bbox, crop)] = RegionCandidates(FULL_REGION, max_side=1920).detect(frame)
        self.assertEqual(bbox, (0, 0, 3840, 2160))
        self.assertEqual(crop.shape[:2], (1080, 1920))

    def test_no_frame_no_candidates(self) -> None:
        self.assertEqual(RegionCandidates().detect(None), [])
        self.assertEqual(RegionCandidates().detect(np.zeros((0, 0, 3), np.uint8)), [])

    def test_region_can_change_while_running(self) -> None:
        source = RegionCandidates()
        source.setRegion({"x": 0.5, "y": 0.0, "width": 0.5, "height": 0.5})
        [(bbox, _)] = source.detect(np.zeros((100, 200, 3), np.uint8))
        self.assertEqual(bbox, (100, 0, 100, 50))


class TestGroupLines(unittest.TestCase):
    def test_lines_of_one_bubble_stay_together_and_bubbles_split(self) -> None:
        scene = Scene()
        first = scene.bubble(360, 120, ["こんにちは、元気ですか？", "今日はどこ行く？"])
        second = scene.bubble(960, 130, ["Hello there!", "How are you?"])
        third = scene.bubble(360, 420, ["See you later"])
        groups = groupLines(scene.lines)
        self.assertEqual([[line["text"] for line in group] for group in groups],
                         [[line["text"] for line in first], [line["text"] for line in second], [line["text"] for line in third]])

    def test_lines_without_boxes_are_kept_alone(self) -> None:
        groups = groupLines([{"text": "a"}, {"text": "b"}])
        self.assertEqual(len(groups), 2)

    def test_bounds(self) -> None:
        scene = Scene()
        lines = scene.bubble(400, 200, ["one", "two words"])
        x, y, w, h = blockBounds(lines)
        self.assertLessEqual(x, min(line["left"] for line in lines))
        self.assertGreaterEqual(x + w, max(line["right"] for line in lines))
        self.assertLess(y, lines[1]["top"])
        self.assertIsNone(blockBounds([{"text": "x"}]))


class TestChatboxStyle(unittest.TestCase):
    def test_white_text_on_the_dark_panel_is_a_chatbox(self) -> None:
        scene = Scene()
        bubble = scene.bubble(400, 200, ["こんにちは", "Nice to meet you"])
        self.assertTrue(looksLikeChatbox(scene.bgr(), bubble))

    def test_chatbox_over_a_bright_world_still_passes(self) -> None:
        scene = Scene()
        scene.image.paste((250, 250, 245, 255), (0, 0, 1280, 720))
        bubble = scene.bubble(640, 300, ["Bright world behind me"])
        self.assertTrue(looksLikeChatbox(scene.bgr(), bubble))

    def test_dark_ink_on_a_light_sign_is_world_text(self) -> None:
        scene = Scene()
        sign = scene.sign(200, 500, "WELCOME TO THE CLUB")
        self.assertFalse(looksLikeChatbox(scene.bgr(), [sign]))

    def test_coloured_text_on_dark_is_world_text(self) -> None:
        scene = Scene()
        neon = scene.bubble(640, 300, ["NEON BAR"], panel=(10, 10, 10, 255), text=(255, 40, 200, 255))
        self.assertFalse(looksLikeChatbox(scene.bgr(), neon))

    def test_white_text_without_a_dark_panel_is_world_text(self) -> None:
        scene = Scene()
        scene.image.paste((200, 200, 200, 255), (0, 0, 1280, 720))
        light = scene.bubble(640, 300, ["Floating label"], panel=(0, 0, 0, 0))
        self.assertFalse(looksLikeChatbox(scene.bgr(), light))

    def test_nothing_to_measure(self) -> None:
        self.assertFalse(looksLikeChatbox(np.zeros((10, 10, 3), np.uint8), [{"text": "x"}]))
        self.assertFalse(looksLikeChatbox(None, []))


if __name__ == "__main__":
    unittest.main()
