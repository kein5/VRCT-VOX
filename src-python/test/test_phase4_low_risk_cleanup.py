"""バックエンドレビュー フェーズ4項目32(小粒4件)のテスト。

対象の欠陥:
  1. Telemetry._start_event_loop() の `while self._loop is None: pass` が
     ビジースピンで、asyncio.new_event_loop() が失敗すると CPU 1コアを
     100%使って無限に回り続けた。
  2. Model.startWebSocketServer()/stopWebSocketServer() が check-then-set
     (TOCTOU) で無ロックだった。2本の別エンドポイント
     (/set/enable/websocket_server と /set/enable/obs_browser_source) が
     ほぼ同時に startWebSocketServer() を呼ぶと、両方とも「未起動」を
     観測して同じポートへの2本目のbindを試み、後勝ちの
     th_websocket_server代入で先に起動した方のスレッド参照が失われ
     二度と停止できなくなり得た。あわせて stopWebSocketServer() の
     タイムアウト時警告が self.logger (LOGGER_FEATURE無効時はNone) に
     依存しており AttributeError になっていた。
  3. threadFnc.pause()/resume() はデッドコード(呼び出し元が存在しない)
     で、かつ while self._pause が self.loop を見ていないため stop() で
     抜けられないバグを内包していた。未使用と確認の上で削除。
  4. DeviceManager.update() が mic_devices/default_mic_device/
     speaker_devices/default_speaker_device の4属性を個別に代入しており、
     別スレッドから見ると新旧が混在した組み合わせを観測しうった。
     1つの不変スナップショットへの単一代入に一本化した。
"""

import time
import unittest
from unittest.mock import patch

from model import threadFnc


class TelemetryEventLoopStartupTests(unittest.TestCase):
    """models/telemetry/__init__.py の Telemetry._start_event_loop()。"""

    def setUp(self) -> None:
        from models.telemetry import Telemetry

        Telemetry._instance = None
        self.telemetry = Telemetry()
        self.addCleanup(self._cleanup_loop)

    def _cleanup_loop(self) -> None:
        try:
            self.telemetry._stop_event_loop(timeout=2.0)
        except Exception:
            pass

    def test_start_event_loop_sets_loop_promptly_on_success(self) -> None:
        start = time.monotonic()
        self.telemetry._start_event_loop()
        elapsed = time.monotonic() - start

        self.assertIsNotNone(self.telemetry._loop)
        self.assertLess(elapsed, 2.0)

    def test_gives_up_promptly_without_hanging_when_loop_creation_fails(self) -> None:
        with patch("asyncio.new_event_loop", side_effect=RuntimeError("boom")), \
             patch("models.telemetry._EVENT_LOOP_READY_TIMEOUT_SEC", 0.2):
            start = time.monotonic()
            self.telemetry._start_event_loop()
            elapsed = time.monotonic() - start

        self.assertLess(
            elapsed, 2.0,
            "タイムアウトを超えて長時間ブロック(ビジースピン含む)してはいけない",
        )
        self.assertIsNone(self.telemetry._loop)


# WebSocket lifecycle regressions now exercise actual concurrent starts and
# bounded cleanup in test_websocket_startup_cancel.py. The former outer
# monitoring thread and its shared alive/loop flags were removed for OI-20.


class ThreadFncPauseResumeRemovedTests(unittest.TestCase):
    """threadFnc からデッドコードの pause()/resume() を削除したことの確認。"""

    def test_pause_and_resume_no_longer_exist(self) -> None:
        self.assertFalse(hasattr(threadFnc, "pause"))
        self.assertFalse(hasattr(threadFnc, "resume"))

    def test_stop_still_terminates_the_thread_promptly(self) -> None:
        calls = []
        thread = threadFnc(lambda: calls.append(1) or time.sleep(0.01))
        thread.start()
        time.sleep(0.05)
        thread.stop()
        thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive())
        self.assertGreater(len(calls), 0)


class DeviceManagerAtomicSnapshotTests(unittest.TestCase):
    """device_manager.py の DeviceManager.update() の原子的スワップ。"""

    def _make_manager(self):
        from device_manager import DeviceManager

        manager = DeviceManager.__new__(DeviceManager)
        manager.init()
        return manager

    def test_update_replaces_all_four_fields_via_a_single_snapshot_assignment(
        self,
    ) -> None:
        manager = self._make_manager()

        # 更新前後で _device_snapshot オブジェクト自体が「まるごと」
        # 入れ替わること(=個別属性の逐次代入ではないこと)を確認する。
        before = manager._device_snapshot

        with patch("device_manager.PyAudio", None):
            manager.update()

        after = manager._device_snapshot
        self.assertIsNot(before, after)
        # 4つのプロパティ全てが同じスナップショットオブジェクトを
        # 参照していること(=一部だけ新しく一部だけ古い、という組み合わせが
        # 起こり得ない)。
        self.assertIs(manager.mic_devices, after.mic_devices)
        self.assertIs(manager.default_mic_device, after.default_mic_device)
        self.assertIs(manager.speaker_devices, after.speaker_devices)
        self.assertIs(manager.default_speaker_device, after.default_speaker_device)

    def test_properties_are_read_only(self) -> None:
        manager = self._make_manager()
        with self.assertRaises(AttributeError):
            manager.mic_devices = {}


if __name__ == "__main__":
    unittest.main()
