"""オーバーレイの起動・停止: 字幕 (一行 / 複数行) と VR UI のどれかがONなら動かし、全部OFFなら止める。"""

import unittest
from unittest.mock import patch

from config import config
from controller import Controller

_KEYS = ("OVERLAY_SMALL_LOG", "OVERLAY_LARGE_LOG", "OVERLAY_VR_PANEL")


class OverlayRunningCase(unittest.TestCase):
    supported = True  # VR UI を作れる OS (Windows) か

    def setUp(self) -> None:
        self.original = {key: getattr(config, key) for key in _KEYS}
        for key in _KEYS:
            setattr(config, key, False)
        patcher = patch("controller.model")
        self.model = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("controller.vrPanelSupported", lambda: self.supported)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        for key, value in self.original.items():
            setattr(config, key, value)


class TestOverlayRunning(OverlayRunningCase):
    def test_vr_panel_alone_starts_the_overlay(self) -> None:
        response = Controller.setEnableOverlayVrPanel()
        self.assertEqual(response, {"status": 200, "result": True})
        self.model.setVrPanelEnabled.assert_called_with(True)
        self.model.startOverlay.assert_called_once_with()
        self.model.shutdownOverlay.assert_not_called()

    def test_last_one_off_stops_the_overlay(self) -> None:
        Controller.setEnableOverlayVrPanel()
        Controller.setDisableOverlayVrPanel()
        self.model.setVrPanelEnabled.assert_called_with(False)
        self.model.shutdownOverlay.assert_called_once_with()

    def test_turning_off_subtitles_keeps_the_vr_panel_running(self) -> None:
        Controller.setEnableOverlaySmallLog()
        Controller.setEnableOverlayVrPanel()
        Controller.setDisableOverlaySmallLog()
        self.model.clearOverlayImageSmallLog.assert_called_once_with()
        self.model.shutdownOverlay.assert_not_called()

    def test_turning_off_the_vr_panel_keeps_subtitles_running(self) -> None:
        Controller.setEnableOverlayLargeLog()
        Controller.setEnableOverlayVrPanel()
        Controller.setDisableOverlayVrPanel()
        self.model.setVrPanelEnabled.assert_called_with(False)
        self.model.shutdownOverlay.assert_not_called()


class TestVrPanelUnsupported(OverlayRunningCase):
    """VR UI を作れない OS (Linux)。作ろうとすると失敗して、字幕のオーバーレイごと止まる。"""

    supported = False

    def test_turning_it_on_is_refused_and_leaves_subtitles_alone(self) -> None:
        Controller.setEnableOverlaySmallLog()
        self.model.reset_mock()
        response = Controller.setEnableOverlayVrPanel()
        self.assertEqual(response["status"], 400)
        self.assertEqual(response["result"]["error_code"], "OVERLAY_VR_PANEL_UNSUPPORTED")
        self.assertIs(response["result"]["data"], False)
        self.assertIs(config.OVERLAY_VR_PANEL, False)
        self.assertIs(config.OVERLAY_SMALL_LOG, True)
        self.assertEqual(self.model.method_calls, [])  # 起動も停止も、VR UI の切り替えもしない

    def test_a_saved_on_does_not_reach_the_overlay(self) -> None:
        config.OVERLAY_VR_PANEL = True
        config.OVERLAY_LARGE_LOG = True
        self.assertIs(Controller.syncOverlayRunning(), self.model.startOverlay.return_value)
        self.model.setVrPanelEnabled.assert_called_once_with(False)
        self.model.startOverlay.assert_called_once_with()

    def test_a_saved_on_alone_does_not_start_the_overlay(self) -> None:
        config.OVERLAY_VR_PANEL = True
        Controller.syncOverlayRunning()
        self.model.setVrPanelEnabled.assert_called_once_with(False)
        self.model.startOverlay.assert_not_called()

    def test_a_saved_on_can_be_turned_off(self) -> None:
        config.OVERLAY_VR_PANEL = True
        self.assertEqual(Controller.setDisableOverlayVrPanel(), {"status": 200, "result": False})


if __name__ == "__main__":
    unittest.main()
