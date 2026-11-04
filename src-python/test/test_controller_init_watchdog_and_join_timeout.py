"""Controller.init() の startWatchdog() 前倒しと、重み DL スレッドの
join() タイムアウトに関するテスト (ロードマップ項目 9、残り部分)。

対象の欠陥:
  以前は startWatchdog() が init() の最終行にあり、ネットワーク判定や
  モデル重みのダウンロード等 (何らかの理由で無期限にハングしうる処理) が
  init() の前半〜中盤に集中していた。ハングが起きると watchdog 自体が
  まだ起動しておらず、自動復旧が一切効かなかった。

  フロントエンドは Python プロセスを spawn した直後から 20s 間隔で
  /run/feed_watchdog を送り続けており (StartPythonController.jsx)、この
  エンドポイントは初期化中でも処理可能 (mainloop.py の "status": True) で
  init() 自体はメインスレッドで同期実行されるため、init() の先頭で
  watchdog を起動しても安全 (ハンドラワーカーがフィードを処理できる)。

  また th_download_ctranslate2/th_download_whisper の join() は無制限で、
  ダウンロードスレッドが (HTTP タイムアウト+リトライの理論上の worst case
  を超えて) 本当にハングした場合、init() を無期限にブロックしていた。
"""

import unittest
from unittest.mock import MagicMock, patch

from controller import Controller


class _Sentinel(Exception):
    """init() の実行をここまで進んだことを示すための目印。"""


class StartWatchdogRunsFirstTests(unittest.TestCase):
    def test_start_watchdog_runs_before_startup_progress_without_network_probe(self) -> None:
        controller = Controller.__new__(Controller)
        controller._model = MagicMock()
        controller.run = MagicMock()
        controller.run_mapping = {"connected_network": "/run/connected_network"}
        calls = []
        controller.startWatchdog = lambda: calls.append("startWatchdog")
        def progress(_):
            calls.append("progress")
            raise _Sentinel()
        controller.initializationProgress = progress
        with patch("controller.isConnectedNetwork") as probe, patch("controller.removeLog"):
            with self.assertRaises(_Sentinel):
                controller.init()
        self.assertEqual(calls, ["startWatchdog", "progress"])
        probe.assert_not_called()
        controller.run.assert_called_once_with(200, "/run/connected_network", None)


def test_wait_timeout_cancels_and_joins_before_retry():
    from models.legacy_model_downloads import LegacyDownloads
    owner = LegacyDownloads()
    control, thread = MagicMock(), MagicMock()
    thread.is_alive.side_effect = [True, False]
    owner.jobs["base"] = control, thread
    assert owner.wait("base", timeout=0.01)
    control.cancel.assert_called_once()
    assert thread.join.call_args_list[0].args == (0.01,)
    join_timeout = thread.join.call_args_list[1].args[0]
    assert 0 <= join_timeout <= control.cancel.call_args.kwargs["timeout"] <= 2
