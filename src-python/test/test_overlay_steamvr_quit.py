"""SteamVR が終わった (VREvent_Quit) あと、オーバーレイは起動を待ってつなぎ直す。

以前は mainloop がハンドルを片付けても initialized が True のまま残った。次の字幕は
作り直しを5秒待ち (メッセージの残りの処理も待たされる)、VR画面だけを使っていると
SteamVR を起動し直しても戻らず、スイッチを入れ直すまで消えたままだった。
"""

import unittest
from unittest.mock import patch

from models.overlay.overlay import Overlay


def _settings() -> dict:
    return {"small": {
        "x_pos": 0.0, "y_pos": 0.0, "z_pos": 0.0,
        "x_rotation": 0.0, "y_rotation": 0.0, "z_rotation": 0.0,
        "display_duration": 5, "fadeout_duration": 2,
        "opacity": 1.0, "ui_scaling": 1.0, "tracker": "HMD",
    }}


class SteamvrQuitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.overlay = Overlay(_settings())
        self.inits = []
        self.after_quit = []

    def _init(self) -> None:
        self.inits.append(self.overlay.initialized)
        self.overlay.initialized = True
        self.overlay.init_process = False

    def _run(self, mainloop, waits) -> None:
        with patch.object(Overlay, "checkSteamvrRunning", return_value=True), \
                patch.object(self.overlay, "init", side_effect=self._init), \
                patch.object(self.overlay, "mainloop", side_effect=mainloop), \
                patch.object(self.overlay, "waitUnlessCancelled", side_effect=waits), \
                patch("models.overlay.overlay.printLog"):
            self.overlay.main()

    def test_a_quit_clears_the_state_and_waits_to_reconnect(self) -> None:
        def quit_then_stop():
            self.overlay.loop = True  # mainloop ended by VREvent_Quit, not by shutdownOverlay
            if len(self.inits) == 2:
                self.overlay.loop = False  # the user turned it off after reconnecting

        def waits(seconds):
            self.after_quit.append((self.overlay.initialized, self.overlay.init_process))
            return False

        self._run(quit_then_stop, waits)
        self.assertEqual(self.inits, [False, False])  # connected again
        # While waiting it reports "starting", so ON reuses the attempt and OFF cancels it.
        self.assertIn((False, True), self.after_quit)

    def test_turning_it_off_does_not_reconnect(self) -> None:
        def stopped():
            self.overlay.loop = False

        self._run(stopped, lambda seconds: False)
        self.assertEqual(len(self.inits), 1)

    def test_turning_it_off_while_waiting_ends_the_thread(self) -> None:
        def quit_once():
            self.overlay.loop = True

        # shutdownOverlay cancels the wait after the quit (the first check before init is 0 s)
        self._run(quit_once, lambda seconds: seconds > 0)
        self.assertEqual(len(self.inits), 1)
        self.assertFalse(self.overlay.initialized)


if __name__ == "__main__":
    unittest.main()
