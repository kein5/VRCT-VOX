"""OSC ミュート同期 (changeHandlerMute) の直列化に関するテスト
(ロードマップ項目 6)。

対象の欠陥:
  ThreadingOSCUDPServer は受信メッセージごとに新しいスレッドを起こすため、
  changeHandlerMute (model.py: startReceiveOSC 内) は
  mic_lifecycle_lock を一切持たない任意のスレッドで走っていた。
  Auto Mic Select のデバイス切替や mainloop ワーカーが直接呼ぶ start/stop 系
  (mic_lifecycle_worker 経由/直接ロック経由いずれも _stop()/_start() を
  実行しうる) とミュート連打による pause()/resume() が無ロックで交錯すると、
  壊れた Recorder に触れて例外になったり、resume() が新しい _audio_queue を
  drain して録音済み音声を取りこぼす。

  修正 (2 段階):
  1. changeHandlerMute は self.changeMicTranscriptStatus() をインラインで
     呼ぶのではなく、Auto Select の他のデバイス操作と同じ
     mic_lifecycle_worker の FIFO キューに投げて直列実行させる。
  2. 実行される関数自体を mic_mute_status_change_callback
     (= Controller.init() (_bootstrapModel()) が登録する
     mic_lifecycle_lock 付きラッパー _changeMicTranscriptStatusLocked)
     にすることで、ロックを直接
     取得する経路 (mainloop ワーカーが直接呼ぶ startTranscriptionSendMessage
     等) とも完全に排他制御する。未登録時は changeMicTranscriptStatus() に
     フォールバックする (Model が Controller を知らないままでも壊れない)。
"""

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import MagicMock, patch

import config as config_module
from controller import Controller
from model import Model
from models.osc.osc import OSCHandler
from osc_fakes import prepare_query


class OscMuteHandlerRoutesThroughWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        # Model はプロセス全体で共有されるシングルトン。他のテストが既に
        # init() 済みかもしれないので、実属性を保存してから上書きし、
        # tearDown で必ず元に戻す。
        self.model = object.__new__(Model)
        self._had_inited = hasattr(self.model, "_inited")
        self._original_inited = getattr(self.model, "_inited", None)
        self._had_mute_status = hasattr(self.model, "mic_mute_status")
        self._original_mute_status = getattr(self.model, "mic_mute_status", None)
        self._had_mic_session = hasattr(self.model, "_mic_session")
        self._original_mic_session = getattr(self.model, "_mic_session", None)
        self._had_worker = hasattr(self.model, "mic_lifecycle_worker")
        self._original_worker = getattr(self.model, "mic_lifecycle_worker", None)
        self._had_osc_handler = hasattr(self.model, "osc_handler")
        self._original_osc_handler = getattr(self.model, "osc_handler", None)
        self._had_mute_callback = hasattr(self.model, "mic_mute_status_change_callback")
        self._original_mute_callback = getattr(self.model, "mic_mute_status_change_callback", None)
        self._mute_state_patch = patch.multiple(
            self.model, _mute_status_generation=0, _mute_verification_pending=None,
            _osc_shutdown=False, _osc_query_admission=True,
            _mute_query_pending=None, _mute_query_future=None,
            _avatar_query_executor=ThreadPoolExecutor(max_workers=1)
        )
        self._mute_state_patch.start()

        self.model._inited = True  # ensure_initialized() の実init発火を防ぐ
        self.model.mic_mute_status = False
        self.model._mic_session = MagicMock()
        self.enqueued = []
        self.model.mic_lifecycle_worker = MagicMock()
        self.model.mic_lifecycle_worker.enqueue.side_effect = lambda fn: self.enqueued.append(fn)
        self.model.osc_handler = MagicMock()
        self.model.osc_handler.osc_parameter_muteself = "/avatar/parameters/MuteSelf"
        self.model.osc_handler.getOSCParameterMuteSelf.return_value = False
        # デフォルトは未登録 (フォールバック経路) を検証する。登録済みの
        # 場合の挙動は別のテストクラスで検証する。
        self.model.mic_mute_status_change_callback = None

        self._original_mute_sync = config_module.config.VRC_MIC_MUTE_SYNC
        config_module.config.VRC_MIC_MUTE_SYNC = True

    def tearDown(self) -> None:
        self._wait_for_queries()
        self.model._avatar_query_executor.shutdown(wait=True, cancel_futures=True)
        self._mute_state_patch.stop()
        config_module.config.VRC_MIC_MUTE_SYNC = self._original_mute_sync
        for attr, had, original in (
            ("_inited", self._had_inited, self._original_inited),
            ("mic_mute_status", self._had_mute_status, self._original_mute_status),
            ("_mic_session", self._had_mic_session, self._original_mic_session),
            ("mic_lifecycle_worker", self._had_worker, self._original_worker),
            ("osc_handler", self._had_osc_handler, self._original_osc_handler),
            ("mic_mute_status_change_callback", self._had_mute_callback, self._original_mute_callback),
        ):
            if had:
                setattr(self.model, attr, original)
            else:
                try:
                    delattr(self.model, attr)
                except AttributeError:
                    pass

    def _get_registered_mute_callback(self):
        self.model.startReceiveOSC()
        (dict_filter_and_target,), _ = self.model.osc_handler.setDictFilterAndTarget.call_args
        return dict_filter_and_target[self.model.osc_handler.osc_parameter_muteself]

    def _wait_for_queries(self):
        if self.model._osc_shutdown:
            self.model._avatar_query_executor.shutdown(wait=True)
        else:
            self.model._avatar_query_executor.submit(lambda: None).result(timeout=5)
            self.model._avatar_query_executor.submit(lambda: None).result(timeout=5)

    def test_mute_true_enqueues_instead_of_calling_pause_inline(self) -> None:
        callback = self._get_registered_mute_callback()
        callback(address="/x", osc_arguments=True)

        self.assertIs(self.model.mic_mute_status, True)
        self.model.osc_handler.getOSCParameterMuteSelf.assert_not_called()
        self.assertEqual(len(self.enqueued), 1)
        self.assertEqual(self.enqueued[0], self.model.changeMicTranscriptStatus)
        # OSC スレッド上でインラインには呼ばれていないこと。
        self.model._mic_session.pause.assert_not_called()

    def test_mute_false_enqueues_instead_of_calling_resume_inline(self) -> None:
        self.model.mic_mute_status = True
        callback = self._get_registered_mute_callback()
        callback(address="/x", osc_arguments=False)
        self._wait_for_queries()

        self.assertEqual(len(self.enqueued), 1)
        self.model._mic_session.resume.assert_not_called()

    def test_enqueued_function_performs_pause_when_actually_run(self) -> None:
        callback = self._get_registered_mute_callback()
        callback(address="/x", osc_arguments=True)

        # ワーカースレッドがキューから取り出して実行した場合の効果を検証する。
        self.enqueued[0]()
        self.model._mic_session.pause.assert_called_once()

    def test_enqueued_function_performs_resume_when_actually_run(self) -> None:
        self.model.mic_mute_status = True
        callback = self._get_registered_mute_callback()
        callback(address="/x", osc_arguments=False)
        self._wait_for_queries()

        self.enqueued[0]()
        self.model._mic_session.resume.assert_called_once()

    def test_forged_false_while_oscquery_says_true_stays_muted(self) -> None:
        self.model.mic_mute_status = True
        self.model.osc_handler.getOSCParameterMuteSelf.return_value = True
        callback = self._get_registered_mute_callback()
        with patch("model.printLog") as log:
            callback("/x", False)
            self._wait_for_queries()
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(self.enqueued, [])
        self.model._mic_session.resume.assert_not_called()
        log.assert_called_once_with("OSC: unmute not confirmed by OSCQuery; keeping microphone muted")

    def test_false_confirmed_by_oscquery_resumes_through_locked_callback(self) -> None:
        self.model.mic_mute_status = True
        locked_wrapper = MagicMock(side_effect=self.model.changeMicTranscriptStatus)
        self.model.mic_mute_status_change_callback = locked_wrapper
        callback = self._get_registered_mute_callback()
        callback("/x", False)
        self._wait_for_queries()
        self.model.osc_handler.getOSCParameterMuteSelf.assert_called_once_with()
        self.assertIs(self.model.mic_mute_status, False)
        self.assertEqual(self.enqueued, [locked_wrapper])
        self.model._mic_session.resume.assert_not_called()
        self.enqueued[0]()
        self.model._mic_session.resume.assert_called_once_with()

    def test_oscquery_unavailable_or_non_boolean_stays_muted(self) -> None:
        self.model.mic_mute_status = True
        callback = self._get_registered_mute_callback()
        for value in (None, 0, "false", [], False):
            with self.subTest(value=value):
                self.model.osc_handler.getOSCParameterMuteSelf.return_value = value
                # Exceptions must also fail closed, without logging their text.
                self.model.osc_handler.getOSCParameterMuteSelf.side_effect = (
                    RuntimeError("private service details") if value is False else None
                )
                with patch("model.printLog") as log:
                    callback("/x", False)
                    self._wait_for_queries()
                self.assertIs(self.model.mic_mute_status, True)
                self.assertFalse(self.model._mute_verification_pending)
                self.assertEqual(self.enqueued, [])
                self.assertTrue(log.called)
                self.assertNotIn("private service details", str(log.call_args_list))
        self.model._mic_session.resume.assert_not_called()

    def _block_query(self, value=False):
        entered = threading.Event()
        release = threading.Event()

        def query():
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release the query")
            return value

        self.model.osc_handler.getOSCParameterMuteSelf.side_effect = query
        return entered, release

    def test_true_during_pending_verification_wins_and_receive_does_not_block(self) -> None:
        self.model.mic_mute_status = True
        entered, release = self._block_query()
        callback = self._get_registered_mute_callback()
        returned = threading.Event()
        receiver = threading.Thread(target=lambda: (callback("/x", False), returned.set()))
        try:
            receiver.start()
            self.assertTrue(entered.wait(1))
            self.assertTrue(returned.wait(1))  # The receive thread returns before the lookup finishes.
            self.assertIs(self.model.mic_mute_status, True)
            callback("/x", True)  # Must invalidate even though the state is already True.
            self.assertEqual(self.enqueued, [])
        finally:
            release.set()
            receiver.join(timeout=5)
            self._wait_for_queries()
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(self.enqueued, [])
        self.model._mic_session.resume.assert_not_called()

    def test_repeated_false_does_not_queue_more_pending_verifications(self) -> None:
        self.model.mic_mute_status = True
        entered, release = self._block_query()
        callback = self._get_registered_mute_callback()
        try:
            callback("/x", False)
            self.assertTrue(entered.wait(1))
            for _ in range(30):
                callback("/x", False)
            self.model.osc_handler.getOSCParameterMuteSelf.assert_called_once()
        finally:
            release.set()
            self._wait_for_queries()
        self.model.osc_handler.getOSCParameterMuteSelf.assert_called_once()
        self.assertEqual(len(self.enqueued), 1)

    def test_true_then_false_during_verification_requires_a_fresh_query(self) -> None:
        self.model.mic_mute_status = True
        entered, release = self._block_query()
        first_query = self.model.osc_handler.getOSCParameterMuteSelf.side_effect
        confirmed = threading.Event()

        def query():
            if not entered.is_set():
                return first_query()
            self.assertIs(self.model.mic_mute_status, True)
            confirmed.set()
            return False

        self.model.osc_handler.getOSCParameterMuteSelf.side_effect = query
        callback = self._get_registered_mute_callback()
        try:
            callback("/x", False)
            self.assertTrue(entered.wait(1))
            callback("/x", True)
            callback("/x", False)
            self.assertIs(self.model.mic_mute_status, True)
        finally:
            release.set()
        self.assertTrue(confirmed.wait(1))
        self._wait_for_queries()
        self.assertEqual(self.model.osc_handler.getOSCParameterMuteSelf.call_count, 2)
        self.assertIs(self.model.mic_mute_status, False)
        self.assertEqual(len(self.enqueued), 1)

    def test_sync_disabled_during_verification_discards_the_result(self) -> None:
        self.model.mic_mute_status = True
        entered, release = self._block_query()
        callback = self._get_registered_mute_callback()
        try:
            callback("/x", False)
            self.assertTrue(entered.wait(1))
            config_module.config.VRC_MIC_MUTE_SYNC = False
        finally:
            release.set()
            self._wait_for_queries()
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(self.enqueued, [])

    def test_stopping_receive_during_verification_discards_the_result(self) -> None:
        self.model.mic_mute_status = True
        entered, release = self._block_query()
        callback = self._get_registered_mute_callback()
        try:
            callback("/x", False)
            self.assertTrue(entered.wait(1))
            self.model.stopReceiveOSC()
        finally:
            release.set()
            self._wait_for_queries()
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(self.enqueued, [])

    def test_timeout_and_late_false_stay_muted_then_a_fresh_query_can_resume(self) -> None:
        # Exercise the real bounded helper with OSCQuery mocked below it. No sockets.
        with patch("models.osc.osc.udp_client.SimpleUDPClient"):
            handler = OSCHandler()
        handler.browser = MagicMock()
        entered = threading.Event()
        release = threading.Event()

        def query(address):
            entered.set()
            release.wait(5)
            return MagicMock(value=[False])

        self.model.mic_mute_status = True
        self.model.osc_handler.getOSCParameterMuteSelf.side_effect = handler.getOSCParameterMuteSelf
        callback = self._get_registered_mute_callback()
        with (patch("models.osc.osc.OSCQueryClient") as client,
              patch("models.osc.osc.OSC_QUERY_TIMEOUT_SECONDS", 0.05),
              patch("models.osc.osc.printLog") as log):
            prepare_query(handler, client)
            client.return_value.query_node.side_effect = query
            try:
                callback("/x", False)
                self.assertTrue(entered.wait(1))
                self._wait_for_queries()  # Completes while the underlying query is still blocked.
                self.assertIs(self.model.mic_mute_status, True)
                self.assertEqual(self.enqueued, [])
                log.assert_any_call("OSCQuery: query timed out", {"address": handler.osc_parameter_muteself})
                callback("/x", False)
                self._wait_for_queries()
                client.return_value.query_node.assert_called_once_with(handler.osc_parameter_muteself)
            finally:
                release.set()
                self.assertTrue(handler._parameter_query_lock.acquire(timeout=5))
                handler._parameter_query_lock.release()
            self.assertIs(self.model.mic_mute_status, True)
            self.assertEqual(self.enqueued, [])
            callback("/x", False)
            self._wait_for_queries()
        self.assertIs(self.model.mic_mute_status, False)
        self.enqueued[0]()
        self.model._mic_session.resume.assert_called_once_with()

    def test_true_from_unknown_state_pauses_without_oscquery(self) -> None:
        self.model.mic_mute_status = None
        callback = self._get_registered_mute_callback()
        callback("/x", True)
        self.assertIs(self.model.mic_mute_status, True)
        self.model.osc_handler.getOSCParameterMuteSelf.assert_not_called()
        self.enqueued[0]()
        self.model._mic_session.pause.assert_called_once_with()

    def test_true_after_verification_but_before_lifecycle_callback_prevents_resume(self) -> None:
        self.model.mic_mute_status = True
        callback = self._get_registered_mute_callback()
        callback("/x", False)
        self._wait_for_queries()
        callback("/x", True)
        for fn in self.enqueued:
            fn()
        self.assertIs(self.model.mic_mute_status, True)
        self.model._mic_session.resume.assert_not_called()

    def test_startup_query_failure_preserves_a_known_mute(self) -> None:
        self.model.mic_mute_status = True
        self.model.osc_handler.getOSCParameterMuteSelf.return_value = None
        self.model.setMuteSelfStatus()
        self.assertIs(self.model.mic_mute_status, True)

    def test_duplicate_mute_state_does_not_enqueue(self) -> None:
        self.model.mic_mute_status = True
        callback = self._get_registered_mute_callback()
        callback(address="/x", osc_arguments=True)  # 既に True なので変化なし
        self.assertEqual(self.enqueued, [])

    def test_sync_disabled_does_not_enqueue(self) -> None:
        config_module.config.VRC_MIC_MUTE_SYNC = False
        callback = self._get_registered_mute_callback()
        callback(address="/x", osc_arguments=True)
        self.assertEqual(self.enqueued, [])

    def test_registered_callback_is_enqueued_instead_of_the_unlocked_fallback(self) -> None:
        # Controller.__init__ が setMicMuteStatusChangeCallback() で
        # 自身の mic_lifecycle_lock 付きラッパーを登録した状態を模す。
        locked_wrapper = MagicMock(name="_changeMicTranscriptStatusLocked")
        self.model.mic_mute_status_change_callback = locked_wrapper

        callback = self._get_registered_mute_callback()
        callback(address="/x", osc_arguments=True)

        self.assertEqual(self.enqueued, [locked_wrapper])
        # フォールバックの changeMicTranscriptStatus ではなく、登録された
        # ロック付きラッパーが使われていること。
        self.assertNotIn(self.model.changeMicTranscriptStatus, self.enqueued)

    # --- /avatar/change: アバターを読み込んだときにミュートの状態を読み直す ---
    # VRCT を先に起動すると、VRChat が現れた直後の問い合わせはアバターの読み込み前で 404 になり、
    # 状態が None のまま決まらなかった (実機)。読み込み時の問い合わせは値を返した (実機)。

    def _avatar_callback(self, mute):
        self.model.osc_handler.getOSCParameterMuteSelf.return_value = mute
        self.model.startReceiveOSC()
        (dict_filter_and_target,), _ = self.model.osc_handler.setDictFilterAndTarget.call_args
        callback = dict_filter_and_target["/avatar/change"]

        def call_and_wait(*args):
            callback(*args)
            self.model._avatar_query_executor.submit(lambda: None).result(timeout=5)  # 問い合わせのスレッドを待つ
        return call_and_wait

    def test_avatar_load_settles_an_unknown_state_and_syncs(self) -> None:
        self.model.mic_mute_status = None
        self._avatar_callback(True)("/avatar/change", "avtr_x")
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(len(self.enqueued), 1)
        self.enqueued[0]()
        self.model._mic_session.pause.assert_called_once()

    def test_avatar_load_with_the_same_state_does_nothing(self) -> None:
        self.model.mic_mute_status = True
        self._avatar_callback(True)("/avatar/change", "avtr_x")
        self.assertEqual(self.enqueued, [])

    def test_avatar_load_without_a_readable_value_keeps_the_state(self) -> None:
        self.model.mic_mute_status = None
        self._avatar_callback(None)("/avatar/change", "avtr_x")
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(len(self.enqueued), 1)

    def test_avatar_load_is_ignored_while_sync_is_off(self) -> None:
        config_module.config.VRC_MIC_MUTE_SYNC = False
        callback = self._avatar_callback(True)
        callback("/avatar/change", "avtr_x")
        self.model.osc_handler.getOSCParameterMuteSelf.assert_not_called()
        self.assertEqual(self.enqueued, [])

    def test_avatar_change_returns_without_waiting_for_the_query(self) -> None:
        # 受信は1本のスレッドで順に処理する (osc.py)。問い合わせ (HTTP) を待つと、その間すべての受信が止まる
        self.model.mic_mute_status = None
        release = threading.Event()
        self.model.osc_handler.getOSCParameterMuteSelf.side_effect = lambda: release.wait(5) and True
        self.model.startReceiveOSC()
        (dict_filter_and_target,), _ = self.model.osc_handler.setDictFilterAndTarget.call_args
        callback = dict_filter_and_target["/avatar/change"]
        started = threading.Event()
        threading.Thread(target=lambda: (callback("/avatar/change", "avtr_x"), started.set())).start()
        self.assertTrue(started.wait(1))  # returned while the query is still waiting
        release.set()
        self.model._avatar_query_executor.submit(lambda: None).result(timeout=5)
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(len(self.enqueued), 1)

    def test_duplicate_avatar_change_syncs_once(self) -> None:
        # VRChat は同じ /avatar/change を続けて送ることがあり、パケットごとに別スレッドで届く
        self.model.mic_mute_status = None
        callback = self._avatar_callback(True)
        threads = [threading.Thread(target=callback, args=("/avatar/change", "avtr_x")) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.enqueued), 1)

    def test_avatar_query_false_cannot_overwrite_a_later_true_message(self) -> None:
        self.model.mic_mute_status = True
        entered, release = self._block_query()
        mute_callback = self._get_registered_mute_callback()
        (callbacks,), _ = self.model.osc_handler.setDictFilterAndTarget.call_args
        try:
            callbacks["/avatar/change"]("/avatar/change", "avtr_x")
            self.assertTrue(entered.wait(1))
            mute_callback("/x", True)
        finally:
            release.set()
            self._wait_for_queries()
        self.assertIs(self.model.mic_mute_status, True)
        self.assertEqual(self.enqueued, [])

    def test_avatar_load_can_still_resume_from_oscquery_false(self) -> None:
        self.model.mic_mute_status = True
        self._avatar_callback(False)("/avatar/change", "avtr_x")
        self.assertIs(self.model.mic_mute_status, False)
        self.enqueued[0]()
        self.model._mic_session.resume.assert_called_once_with()


class ControllerRegistersLockedMuteCallbackTests(unittest.TestCase):
    """Controller が起動時に mic_lifecycle_lock 付きラッパーを Model へ
    登録し、そのラッパー自体が実際にロックを取得することを確認する。

    フェーズ3項目22により、この登録は Controller.__init__ ではなく
    Controller.init() (実際には _bootstrapModel()) で行われる
    (model.init() がコールバックスロットを None にリセットするため、
    先に model.init() を終わらせてから登録する順序になっている)。
    """

    @patch("controller.model")
    def test_bootstrap_registers_the_locked_wrapper_with_model(self, mock_model) -> None:
        # controller.model をまるごとモックしているため、model.init() を
        # 含む _bootstrapModel() 全体を実行しても実デバイス/実ネットワークには
        # 一切触れない。
        controller = Controller()

        controller._bootstrapModel()

        mock_model.setMicMuteStatusChangeCallback.assert_called_once_with(
            controller._changeMicTranscriptStatusLocked
        )
        # 順序保証: setMicMuteStatusChangeCallback は init() の後に呼ばれる
        # (先にリセットされてから登録されないと、登録した値が消えてしまう)。
        assert mock_model.method_calls.index(("init", (), {})) < mock_model.method_calls.index(
            ("setMicMuteStatusChangeCallback", (controller._changeMicTranscriptStatusLocked,), {})
        )

    def test_locked_wrapper_acquires_the_lock_around_change_mic_transcript_status(self) -> None:
        controller = Controller.__new__(Controller)
        controller.mic_lifecycle_lock = threading.RLock()
        lock = controller.mic_lifecycle_lock
        observed_locked = []

        def locked_from_another_thread():
            acquired = []
            def probe():
                held = lock.acquire(blocking=False)
                acquired.append(held)
                if held:
                    lock.release()
            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            return acquired == [False]

        with patch("controller.model") as mock_model:
            mock_model.changeMicTranscriptStatus.side_effect = lambda: observed_locked.append(locked_from_another_thread())
            controller._changeMicTranscriptStatusLocked()

        self.assertEqual(observed_locked, [True])
        self.assertFalse(locked_from_another_thread())


if __name__ == "__main__":
    unittest.main()
