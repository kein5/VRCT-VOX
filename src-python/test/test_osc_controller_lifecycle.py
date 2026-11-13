"""Mic/OSC interleavings after #128, with memory-only transports and sessions."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import controller as controller_module
import model as model_module
from controller import Controller
from model import Model
from models.osc import osc
from osc_fakes import FakeZeroconf, fake_transports, local_service


@pytest.fixture
def context(monkeypatch):
    config = SimpleNamespace(VRC_MIC_MUTE_SYNC=True, ENABLE_TRANSCRIPTION_SEND=True,
                             OSC_IP_ADDRESS="127.0.0.1", OSC_PORT=9000)
    model = object.__new__(Model)
    model._inited = True
    model._osc_shutdown = False
    model._osc_query_admission = True
    model._mute_status_lock = threading.Lock()
    model._osc_lifecycle_lock = threading.RLock()
    model._mute_status_generation = 0
    model._mute_query_pending = None
    model._mute_query_future = None
    model._avatar_query_executor = None
    model.mic_mute_status = True
    model.mic_lifecycle_worker = MagicMock()
    model.message_delivery = MagicMock()
    model._mic_session = MagicMock()
    model.osc_handler = MagicMock()
    model.osc_handler.osc_parameter_muteself = "/avatar/parameters/MuteSelf"
    model.osc_handler.getIsOscQueryEnabled.return_value = True
    controller = Controller.__new__(Controller)
    controller.mic_lifecycle_lock = threading.RLock()
    controller.run = MagicMock()
    controller.run_mapping = {"enable_osc_query": "/run/enable_osc_query"}
    controller._realtimeToggles = lambda: False
    controller._stopTranscriptionSendMessageLocked = MagicMock()
    model.mic_mute_status_change_callback = controller._changeMicTranscriptStatusLocked
    monkeypatch.setattr(controller_module, "model", model)
    monkeypatch.setattr(controller_module, "config", config)
    monkeypatch.setattr(model_module, "config", config)
    yield SimpleNamespace(model=model, controller=controller, config=config)
    if model._avatar_query_executor is not None:
        model._avatar_query_executor.shutdown(wait=True, cancel_futures=True)


def callbacks(context):
    context.model.startReceiveOSC()
    return context.model.osc_handler.setDictFilterAndTarget.call_args.args[0]


def test_avatar_storm_has_one_job_and_shutdown_cancels_queued_work(context):
    model = context.model
    calls = callbacks(context)
    entered, release = threading.Event(), threading.Event()
    # Occupy the executor before admitting an avatar refresh.
    blocker = model._avatar_query_executor.submit(lambda: (entered.set(), release.wait(2)))
    assert entered.wait(1)
    try:
        for _ in range(1000):
            calls["/avatar/change"]("/avatar/change", "avatar")
        future = model._mute_query_future
        assert model._avatar_query_executor._work_queue.qsize() == 1
        model.stopReceiveOSC()
        assert future.cancelled()
        for _ in range(10):
            calls["/avatar/change"]("/avatar/change", "avatar")
        model.osc_handler.getOSCParameterMuteSelf.assert_not_called()
        with pytest.raises(RuntimeError):
            model._avatar_query_executor.submit(lambda: None)
        with pytest.raises(RuntimeError, match="shut down"):
            model.startReceiveOSC()
    finally:
        release.set()
        blocker.result(1)


def test_avatar_checks_generation_before_network_query(context):
    model = context.model
    calls = callbacks(context)
    entered, release = threading.Event(), threading.Event()
    model._avatar_query_executor.submit(lambda: (entered.set(), release.wait(2)))
    assert entered.wait(1)
    calls["/avatar/change"]("/avatar/change", "avatar")
    future = model._mute_query_future
    calls["/avatar/parameters/MuteSelf"]("/mute", True)
    release.set()
    future.result(1)
    model.osc_handler.getOSCParameterMuteSelf.assert_not_called()
    assert model.mic_mute_status is True


@pytest.mark.parametrize("failure", ["udp", "advertisement", "library"])
def test_setup_failure_disables_capability_and_stops_mic_before_disabling_sync(context, failure):
    with fake_transports():
        context.model.osc_handler = osc.OSCHandler()
        target = {
            "udp": (osc.osc_server, "BlockingOSCUDPServer"),
            "advertisement": (FakeZeroconf, "register_service"),
            "library": (osc, "OSCQueryService"),
        }[failure]
        kwargs = {"new": None} if failure == "library" else {"side_effect": OSError("setup failed")}
        with patch.object(*target, **kwargs):
            context.controller._initOscReceive()
        assert not context.model.getIsOscQueryEnabled()
        assert context.config.VRC_MIC_MUTE_SYNC is False
        assert context.config.ENABLE_TRANSCRIPTION_SEND is False
        context.controller._stopTranscriptionSendMessageLocked.assert_called_once()
        context.model._mic_session.resume.assert_not_called()
        context.controller.run.assert_any_call(200, "/run/enable_osc_query", {
            "data": False, "disabled_functions": ["vrc_mic_mute_sync"],
            "reason": "setup_failed", "microphone_stopped": True,
        })
        context.controller.run.assert_any_call(200, "/set/disable/vrc_mic_mute_sync", False)
        context.controller.run.assert_any_call(200, "/set/disable/transcription_send", False)
        context.model.stopReceiveOSC()


def _readiness_notices(context):
    return [call.args[2] for call in context.controller.run.call_args_list
            if call.args[1] == "/run/enable_osc_query"]


def test_startup_with_a_remote_destination_and_sync_off_does_not_warn(context):
    """A standalone headset is a setting, not a failure: nothing was switched off."""
    context.config.OSC_IP_ADDRESS = "192.168.0.20"
    context.config.VRC_MIC_MUTE_SYNC = False
    context.model.osc_handler.getIsOscQueryEnabled.return_value = False
    context.controller._initOscReceive()
    # The capability is still reported as unavailable; only the warning is left out.
    assert _readiness_notices(context) == [{"data": False, "disabled_functions": [],
                                            "reason": "remote_destination", "microphone_stopped": False}]
    assert context.config.ENABLE_TRANSCRIPTION_SEND is True
    context.controller._stopTranscriptionSendMessageLocked.assert_not_called()


def test_startup_with_a_remote_destination_warns_when_it_switches_sync_off(context):
    context.config.OSC_IP_ADDRESS = "192.168.0.20"
    context.model.osc_handler.getIsOscQueryEnabled.return_value = False
    context.controller._initOscReceive()
    assert context.config.VRC_MIC_MUTE_SYNC is False
    assert context.config.ENABLE_TRANSCRIPTION_SEND is False
    assert _readiness_notices(context) == [{"data": False, "disabled_functions": ["vrc_mic_mute_sync"],
                                            "reason": "remote_destination", "microphone_stopped": True}]


def test_startup_failure_for_this_pc_warns_even_with_sync_off(context):
    """The destination is local, so an unusable receiver is unexpected."""
    context.config.VRC_MIC_MUTE_SYNC = False
    context.model.osc_handler.getIsOscQueryEnabled.return_value = False
    context.controller._initOscReceive()
    assert _readiness_notices(context) == [{"data": False, "disabled_functions": ["vrc_mic_mute_sync"],
                                            "reason": "setup_failed", "microphone_stopped": False}]


def test_changing_the_destination_to_another_machine_warns_once_with_sync_off(context):
    """Right after the user's own change, say what it made unavailable."""
    context.config.VRC_MIC_MUTE_SYNC = False
    context.model.osc_handler.getIsOscQueryEnabled.return_value = False
    assert context.controller.setOscIpAddress("192.168.0.20")["status"] == 200
    assert _readiness_notices(context) == [{"data": False, "disabled_functions": ["vrc_mic_mute_sync"],
                                            "reason": "remote_destination", "microphone_stopped": False}]


@pytest.mark.parametrize("toggle", ["enable", "disable", "startup"])
def test_mute_sync_transitions_wait_for_mic_reconfigure_lock(context, toggle):
    context.config.VRC_MIC_MUTE_SYNC = toggle != "enable"
    context.model.osc_handler.getOSCParameterMuteSelf.return_value = False
    controller = context.controller
    operation = {"enable": controller.setEnableVrcMicMuteSync,
                 "disable": controller.setDisableVrcMicMuteSync,
                 "startup": controller._initVrcMicMuteSync}[toggle]
    entered = threading.Event()
    with ThreadPoolExecutor(1) as executor:
        with controller.mic_lifecycle_lock:
            future = executor.submit(lambda: (entered.set(), operation()))
            assert entered.wait(1)
            assert not future.done()
            context.model._mic_session.pause.assert_not_called()
            context.model._mic_session.resume.assert_not_called()
        future.result(1)
    assert context.model._mic_session.pause.called or context.model._mic_session.resume.called


def test_toggle_query_wait_is_outside_mic_lock_and_cannot_override_off(context):
    context.config.VRC_MIC_MUTE_SYNC = False
    entered, release = threading.Event(), threading.Event()
    context.model.osc_handler.getOSCParameterMuteSelf.side_effect = lambda: (entered.set(), release.wait(2), False)[-1]
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(context.controller.setEnableVrcMicMuteSync)
        assert entered.wait(1)
        assert context.controller.mic_lifecycle_lock.acquire(timeout=0.2)
        try:
            context.controller.setDisableTranscriptionSend()
            context.controller.setDisableVrcMicMuteSync()
            context.model._mic_session.resume.reset_mock()
        finally:
            context.controller.mic_lifecycle_lock.release()
            release.set()
        future.result(1)
    assert context.config.ENABLE_TRANSCRIPTION_SEND is False
    assert context.config.VRC_MIC_MUTE_SYNC is False
    assert context.model.mic_mute_status is True
    context.model._mic_session.resume.assert_not_called()


def test_untrusted_service_keeps_unknown_mic_paused(context):
    with fake_transports(), patch.object(osc, "OSCQueryClient") as client:
        handler = osc.OSCHandler()
        handler.is_osc_query_enabled = True
        handler.browser = MagicMock()
        handler.browser.get_discovered_oscquery.return_value = [local_service(ip=b"\xc0\xa8\x01\x05")]
        context.model.osc_handler = handler
        context.model.mic_mute_status = None
        context.controller._initVrcMicMuteSync()
        assert context.model.mic_mute_status is True
        context.model._mic_session.pause.assert_called()
        context.model._mic_session.resume.assert_not_called()
        client.assert_not_called()


def test_unknown_mute_blocks_message_publication(context):
    context.model.mic_mute_status = None
    assert context.controller._messagePublicationGuard("mic")() is False


def test_failed_port_replacement_does_not_commit_configuration(context):
    context.model.osc_handler.setOscPort.side_effect = OSError("bind failed")
    with pytest.raises(OSError):
        context.controller.setOscPort(9001)
    assert context.config.OSC_PORT == 9000


def test_startup_query_cannot_unmute_after_disable_then_enable(context):
    entered, release = threading.Event(), threading.Event()
    context.model.osc_handler.getOSCParameterMuteSelf.side_effect = lambda: (entered.set(), release.wait(2), False)[-1]
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(context.controller._initVrcMicMuteSync)
        assert entered.wait(1)
        context.controller.setDisableVrcMicMuteSync()
        # A new enable invalidates the old query even if the bool flag matches again.
        context.config.VRC_MIC_MUTE_SYNC = True
        context.model.invalidateMuteSelfStatus()
        release.set()
        future.result(1)
    assert context.model.mic_mute_status is True


def test_late_background_start_after_shutdown_does_not_rewrite_sync_settings(context):
    context.model.requestOSCShutdown()
    context.model.osc_handler.getIsOscQueryEnabled.return_value = False
    context.controller._initOscReceive()
    context.model.osc_handler.receiveOscParameters.assert_not_called()
    context.controller.run.assert_not_called()
    assert context.config.VRC_MIC_MUTE_SYNC is True
    assert context.config.ENABLE_TRANSCRIPTION_SEND is True
