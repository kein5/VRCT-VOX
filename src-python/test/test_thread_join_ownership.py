"""Shutdown timeout regressions, without sockets, devices, models or GPU work."""
from threading import Event, Lock, Thread
from unittest.mock import Mock, patch

import pytest

import device_manager as devices
import model as model_module
from model import Model, MicSession, threadFnc
from models.ocr.ocr_pipeline import OcrPipeline
from models.overlay.overlay import Overlay
from models.telemetry import Telemetry


class PendingThread(Thread):
    """A join timeout that consumes no wall-clock time and runs no target."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alive = True
        self.joins = []

    def start(self):
        pass

    def join(self, timeout=None):
        self.joins.append(timeout)

    def is_alive(self):
        return self.alive


class PendingWatchdog(threadFnc):
    def __init__(self):
        super().__init__(lambda: None)
        self.alive = True

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return self.alive


def bare_model():
    owner = object.__new__(Model)
    owner.ensure_initialized = lambda: None
    return owner


def test_device_monitor_keeps_stop_set_and_refuses_restart_until_dead():
    owner = object.__new__(devices.DeviceManager)
    owner._lifecycle_lock = Lock()
    owner._stop_event, owner._notify_event = Event(), Event()
    old = owner.th_monitoring = PendingThread()
    with patch.object(devices, 'Thread', PendingThread), patch.object(devices, 'printLog') as log:
        owner.stopMonitoring()
        owner.stopMonitoring()
        owner.startMonitoring()
        assert owner.th_monitoring is old
        assert owner._stop_event.is_set()
        assert old.joins == [0.5, 0.5]
        log.assert_called_once()
        old.alive = False
        owner.startMonitoring()
        assert owner.th_monitoring is not old
        assert not owner._stop_event.is_set()


def test_ocr_timeout_keeps_capture_and_does_not_report_restart_success():
    callback = Mock()
    pipeline = OcrPipeline(callback)
    old = pipeline._thread = PendingThread()
    capture = pipeline._capture = Mock()
    with patch.object(pipeline, 'isEngineAvailable', return_value=True), \
            patch('models.ocr.ocr_pipeline.printLog') as log, \
            patch('models.ocr.ocr_pipeline.Thread') as spawn:
        assert pipeline.stop() is False
        assert pipeline.stop() is False
        assert pipeline._thread is old
        assert pipeline._capture is capture
        assert pipeline.start() is False
        pipeline._emit('late OCR result')
        callback.assert_not_called()
        spawn.assert_not_called()
        log.assert_called_once()
        old.alive = False
        assert pipeline.stop() is True
        assert pipeline._thread is None
        assert pipeline._capture is None
        capture.close.assert_not_called()  # Only the owner thread may close capture.


def test_model_keeps_timed_out_ocr_owner_and_replaces_it_only_after_exit():
    owner = bare_model()
    pipeline = owner.ocr_pipeline = OcrPipeline(Mock())
    old = pipeline._thread = PendingThread()
    with patch('models.ocr.ocr_pipeline.printLog'), patch.object(pipeline, 'isEngineAvailable', return_value=True):
        owner.stopOCRCapture()
        assert owner.ocr_pipeline is pipeline
        assert owner.startOCRCapture(Mock()) is False
        assert owner.ocr_pipeline is pipeline
        old.alive = False
        owner.stopOCRCapture()
        assert owner.ocr_pipeline is None


def test_watchdog_keeps_timed_out_worker_and_refuses_second_instance():
    owner = bare_model()
    old = owner.th_watchdog = PendingWatchdog()
    owner.watchdog = Mock()
    owner._armFreezeDump = Mock()
    with patch.object(model_module.faulthandler, 'cancel_dump_traceback_later'), \
            patch.object(model_module, 'printLog') as log, patch.object(threadFnc, 'start') as spawn:
        owner.stopWatchdog()
        owner.stopWatchdog()
        owner.startWatchdog()
        assert owner.th_watchdog is old
        assert old.loop is False
        spawn.assert_not_called()
        log.assert_called_once()
        old.alive = False
        owner.startWatchdog()
        assert owner.th_watchdog is not old
        spawn.assert_called_once()


def test_overlay_timeout_retains_handles_and_refuses_new_owner():
    owner = Overlay({})
    owner.initialized = True
    old = owner.thread_overlay = PendingThread()
    with patch.object(owner, 'destroyOverlays') as destroy, \
            patch.object(owner, 'releaseSession') as release, \
            patch('models.overlay.overlay.printLog') as log, \
            patch.object(Thread, 'start') as spawn:
        owner.shutdownOverlay()
        owner.shutdownOverlay()
        owner.startOverlay()
        assert owner.thread_overlay is old
        assert owner.initialized is False  # OFF revokes readiness while the owner is retained.
        spawn.assert_not_called()
        destroy.assert_not_called()
        release.assert_not_called()
        log.assert_called_once()
        old.alive = False
        owner.shutdownOverlay()
        owner.startOverlay()
        assert owner.thread_overlay is not old
        spawn.assert_called_once()


@pytest.mark.parametrize('worker_attr', ['_print_transcript', '_energy_progressbar'])
def test_audio_reconfigure_waits_for_all_old_delivery_workers(worker_attr):
    session = MicSession()
    old = PendingWatchdog()
    setattr(session, worker_attr, old)
    session.features = {'transcript'}
    device = {'name': 'fake', 'index': 0}
    with patch.object(session, '_resolve_device', return_value=device), \
            patch.object(session, '_start') as start, patch.object(model_module, 'printLog') as log:
        session.reconfigure(transcript=True)
        session.reconfigure(transcript=True)
        assert old in session._cleanup_workers
        assert not session.features
        start.assert_not_called()
        log.assert_called_once()
        old.alive = False
        session.reconfigure(transcript=True)
        start.assert_called_once_with(device=device, previous_device=None)


def test_audio_reconfigure_waits_for_recorder_cleanup():
    session = MicSession()
    session.features = {'transcript'}
    session._recorder = Mock()
    device = {'name': 'fake', 'index': 0}
    with patch.object(model_module, 'Thread', PendingThread), \
            patch.object(session, '_resolve_device', return_value=device), \
            patch.object(session, '_start') as start, patch.object(model_module, 'printLog') as log:
        session.reconfigure(transcript=True)
        old, = session._cleanup_workers
        session.reconfigure(transcript=True)
        assert session._cleanup_workers == [old]
        assert not session.features
        start.assert_not_called()
        log.assert_called_once()
        old.alive = False
        session.reconfigure(transcript=True)
        start.assert_called_once_with(device=device, previous_device=None)


def telemetry_owner():
    owner = object.__new__(Telemetry)
    owner._initialized = False
    owner.__init__()
    return owner


def test_telemetry_keeps_timed_out_loop_and_rejects_reinitialization():
    owner = telemetry_owner()
    old = owner._loop_thread = PendingThread()
    loop = owner._loop = Mock()
    loop.is_closed.return_value = False
    with patch('models.telemetry.threading.Thread') as spawn, \
            patch('models.telemetry.printLog') as log:
        owner._stop_event_loop(timeout=0.01)
        owner._stop_event_loop(timeout=0.01)
        assert owner._loop_thread is old
        assert owner._loop is loop
        owner.init(enabled=True)
        assert not owner.is_enabled()
        assert not owner._init_called
        spawn.assert_not_called()
        log.assert_called_once()
        old.alive = False
        owner._stop_event_loop(timeout=0.01)
        assert owner._loop_thread is None
        assert owner._loop is None


def test_telemetry_readiness_timeout_cancels_late_loop_before_it_runs():
    owner = telemetry_owner()
    ready = Mock()
    ready.wait.return_value = False
    loop = Mock()
    with patch('models.telemetry.threading.Thread', PendingThread), \
            patch('models.telemetry.threading.Event', return_value=ready), \
            patch('models.telemetry.asyncio.new_event_loop', return_value=loop), \
            patch('models.telemetry.asyncio.set_event_loop'), patch('models.telemetry.printLog'):
        assert owner._start_event_loop() is False
        old = owner._loop_thread
        assert old is not None
        # Simulate an OS call completing after the startup/stop deadlines.
        old._target()
        loop.run_forever.assert_not_called()
        loop.close.assert_called_once()
        assert owner._loop is None


@pytest.mark.parametrize('fails', [False, True])
def test_late_asr_result_or_error_is_not_published_after_timeout(fails):
    class AudioThread(PendingThread):
        def __init__(self, fnc, end_fnc=None, **kwargs):
            super().__init__(**kwargs)
            self.fnc, self.end_fnc = fnc, end_fnc

        def stop(self):
            pass

    session = MicSession()
    session.features = {'transcript'}
    callback = session.transcript_fnc = Mock()
    recorder = Mock(device_error_event=Event(), stop=None)
    transcriber = Mock()
    transcriber.hasTranscript.return_value = True
    transcriber.getAudioWaitTimeout.return_value = 0  # process this round now

    def late_transcription(*args):
        session._stop()
        if fails:
            raise RuntimeError('late failure')

    with patch.object(model_module, 'threadFnc', AudioThread), \
            patch.object(model_module, 'printLog'), patch.object(model_module, 'errorLogging'), \
            patch.object(session, '_create_recorder', return_value=recorder), \
            patch.object(session, '_create_transcriber', return_value=transcriber), \
            patch.object(session, '_transcribe', side_effect=late_transcription), \
            patch.object(session, '_handle_pipeline_error') as error:
        session._start(device={'name': 'fake', 'index': 0})
        worker = session._print_transcript
        worker.fnc()
        assert worker in session._cleanup_workers
        callback.assert_not_called()
        error.assert_not_called()
        transcriber.getTranscript.assert_not_called()


def test_queued_old_audio_error_cleanup_cannot_stop_replacement():
    session = MicSession()
    old = session._recorder = Mock()
    workers = []

    def spawn(*args, **kwargs):
        thread = PendingThread(*args, **kwargs)
        workers.append(thread)
        return thread

    with patch.object(model_module, 'Thread', side_effect=spawn), \
            patch.object(session, '_stop') as stop, \
            patch.object(session, '_notify_pipeline_error') as notify:
        session._handle_pipeline_error(Mock(), old)
        new = session._recorder = Mock()
        session._pipeline_error_started = False
        workers[0]._target()
        session._handle_pipeline_error(Mock(), old)
        assert session._recorder is new
        assert session._pipeline_error_started is False
        assert len(workers) == 1
        stop.assert_not_called()
        notify.assert_not_called()


def test_obs_timeout_keeps_server_and_refuses_second_listener():
    from models.obs.obs_browser_source_server import ObsBrowserSourceServer

    server = ObsBrowserSourceServer('127.0.0.1', 2232)
    old = server._thread = PendingThread()
    http = server._server = Mock(has_handlers=False)
    with patch('models.obs.obs_browser_source_server._ObsHTTPServer') as spawn, \
            patch('models.obs.obs_browser_source_server.printLog') as log:
        server.stop()
        server.stop()
        server.start()
        assert server._thread is old
        assert server._server is http
        assert not server.is_stopped
        assert not server.is_running  # Cancellation is not a successful start.
        spawn.assert_not_called()
        log.assert_called_once()
        old.alive = False
        server.stop()
        assert server.is_stopped
        assert server._server is None


def test_model_does_not_forget_obs_worker_when_stop_times_out():
    from models.obs.obs_browser_source_server import ObsBrowserSourceServer

    owner = bare_model()
    server = owner.obs_browser_source_server = ObsBrowserSourceServer('127.0.0.1', 2232)
    old = server._thread = PendingThread()
    server._server = Mock(has_handlers=False)
    with patch.object(model_module, 'ObsBrowserSourceServer') as spawn, \
            patch('models.obs.obs_browser_source_server.printLog'):
        owner.stopObsBrowserSourceServer()
        owner.startObsBrowserSourceServer('127.0.0.1', 2233)
        assert owner.obs_browser_source_server is server
        assert owner.checkObsBrowserSourceServerAlive() is False
        spawn.assert_not_called()
        old.alive = False
        owner.startObsBrowserSourceServer('127.0.0.1', 2233)
        assert owner.obs_browser_source_server is spawn.return_value
        spawn.assert_called_once()


def test_obs_port_change_cannot_publish_during_previous_stop_cleanup():
    owner = bare_model()
    old = owner.obs_browser_source_server = Mock(is_running=False, is_stopped=False)
    stopping, release, starting, constructed = Event(), Event(), Event(), Event()
    errors = []

    def stop_old():
        stopping.set()
        assert release.wait(2)
        old.is_stopped = True

    old.stop.side_effect = stop_old
    replacement = Mock()

    def create(**kwargs):
        constructed.set()
        return replacement

    def call(fn):
        try:
            fn()
        except BaseException as exc:
            errors.append(exc)

    def start_new():
        starting.set()
        owner.startObsBrowserSourceServer('127.0.0.1', 2233)

    with patch.object(model_module, 'ObsBrowserSourceServer', side_effect=create):
        stopper = Thread(target=call, args=(owner.stopObsBrowserSourceServer,))
        starter = Thread(target=call, args=(start_new,))
        stopper.start()
        try:
            assert stopping.wait(1)
            starter.start()
            assert starting.wait(1)
            assert not constructed.wait(.05)
            assert owner.obs_browser_source_server is old
        finally:
            release.set()
            stopper.join(2)
            if starter.ident is not None:
                starter.join(2)
        assert not stopper.is_alive() and not starter.is_alive()
        assert not errors
        assert constructed.is_set()
        assert owner.obs_browser_source_server is replacement
        replacement.start.assert_called_once()


def test_recorder_stop_failure_allows_normal_restart_but_blocks_exclusive_handoff():
    session = MicSession()
    recorder = session._recorder = Mock()
    recorder.stop.side_effect = RuntimeError('recorder cleanup failed')
    session.features = {'transcript'}
    device = {'name': 'fake', 'index': 0}

    session._stop()
    recorder.stop.assert_called_once_with(wait_for_stop=True)
    assert session._cleanup_failed.is_set()
    assert not session._cleanup_workers

    with patch.object(session, '_resolve_device', return_value=device), \
            patch.object(session, '_start') as start:
        session.reconfigure(transcript=True)
        start.assert_called_once_with(device=device, previous_device=None)
        assert session.stop_for_handoff() is False
