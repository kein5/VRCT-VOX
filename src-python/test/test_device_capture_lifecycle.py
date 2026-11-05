"""Legacy capture ownership under controlled interleavings; no audio/COM calls."""
from threading import Event, Lock, RLock, Thread
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as controller_module
import model as model_module
from controller import Controller
from model import MicSession, SpeakerSession, Model
from models.message_delivery import DeliveryEpochs
from models.transcription import transcription_recorder as recorders


class QueuedWorker:
    def __init__(self):
        self.jobs = {}
        self.queued = Event()

    def enqueue(self, fn, coalesce_key=None):
        self.jobs[coalesce_key] = fn
        self.queued.set()
        return True

    def drain(self):
        jobs, self.jobs = list(self.jobs.values()), {}
        for job in jobs:
            job()


class Recorder:
    def __init__(self, device):
        self.device = device
        self.device_error_event = Event()
        self.device_error_info = None
        self.stop = Mock()
        self.pause = Mock()
        self.resume = Mock()

    def recordIntoQueue(self, audio, energy):
        self.audio, self.energy = audio, energy


class Consumer:
    """Consumers are deliberately never run: recorder errors must work anyway."""
    def __init__(self, fnc, **kwargs):
        self.fnc = fnc

    def start(self):
        pass

    def stop(self):
        pass

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


class CheckedLock:
    """A real non-reentrant mutex; fail a test instead of hanging on re-entry."""
    def __init__(self):
        self.lock = Lock()

    def __enter__(self):
        assert self.lock.acquire(timeout=2), 'source lifecycle lock acquired recursively'
        return self

    def __exit__(self, *args):
        self.lock.release()



@pytest.fixture(params=['mic', 'speaker'])
def rig(request, monkeypatch):
    source = request.param
    kind = source.capitalize()
    suffix = 'SEND' if source == 'mic' else 'RECEIVE'
    a = dict(id='endpoint-a', name='Device A', index=1, defaultSampleRate=48000, maxInputChannels=2)
    b = dict(id='endpoint-b', name='Device B', index=6, defaultSampleRate=16000, maxInputChannels=1)
    devices = [a, b]
    config = SimpleNamespace(SELECTED_MIC_HOST='Host', SELECTED_MIC_DEVICE=a['name'],
        SELECTED_MIC_DEVICE_ID=a['id'], SELECTED_SPEAKER_DEVICE=a['name'], SELECTED_SPEAKER_DEVICE_ID=a['id'],
        AUTO_MIC_SELECT=False, AUTO_SPEAKER_SELECT=False, SELECTED_TRANSCRIPTION_ENGINE='Google',
        ENABLE_TRANSCRIPTION_SEND=False, ENABLE_TRANSCRIPTION_RECEIVE=False,
        ENABLE_CHECK_ENERGY_SEND=False, ENABLE_CHECK_ENERGY_RECEIVE=False)
    dm = Mock()
    dm.getMicDevices.side_effect = lambda: {'Host': devices}
    dm.getSpeakerDevices.side_effect = lambda: devices
    dm.getDefaultMicDevice.side_effect = lambda: {'host': {'name': 'Host'}, 'device': b}
    dm.getDefaultSpeakerDevice.side_effect = lambda: {'device': b}
    backend = SimpleNamespace(_mic_session=MicSession(), _speaker_session=SpeakerSession(),
        mic_lifecycle_worker=QueuedWorker(), speaker_lifecycle_worker=QueuedWorker(),
        ensure_initialized=lambda: None, changeMicTranscriptStatus=lambda: None,
        message_delivery=DeliveryEpochs(), detectVRAMError=lambda error: (False, None))
    for method in ('startMicTranscript', 'stopMicTranscript', 'startSpeakerTranscript', 'stopSpeakerTranscript',
                   'startCheckMicEnergy', 'stopCheckMicEnergy', 'startCheckSpeakerEnergy', 'stopCheckSpeakerEnergy'):
        setattr(backend, method, MethodType(getattr(Model, method), backend))
    backend.getListMicDevice = backend.getListSpeakerDevice = lambda: [d['name'] for d in devices]
    c = Controller.__new__(Controller)
    c.mic_lifecycle_lock = CheckedLock()
    c.speaker_lifecycle_lock = CheckedLock()
    c._realtime_lock = RLock()
    c._realtime_requested = {'mic': False, 'speaker': False}
    c._realtimeToggles = lambda: False
    c._drainRealtimeASR = lambda _: True
    c.stopRealtimeASR = lambda _: None
    c.run_mapping = {name: '/run/' + name for name in
        ('selectable_mic_device_list', 'selectable_speaker_device_list', 'error_device',
         'check_mic_volume', 'check_speaker_volume')}
    calls = []
    c.run = lambda status, endpoint, result: calls.append((status, endpoint, result))
    monkeypatch.setattr(controller_module, 'config', config)
    monkeypatch.setattr(controller_module, 'device_manager', dm)
    monkeypatch.setattr(controller_module, 'model', backend)
    monkeypatch.setattr(model_module, 'config', config)
    monkeypatch.setattr(model_module, 'device_manager', dm)
    monkeypatch.setattr(model_module, 'threadFnc', Consumer)
    session = getattr(backend, '_' + source + '_session')
    opened = []
    def create(device):
        opened.append(device)
        return Recorder(device)
    session._create_recorder = create
    session._create_transcriber = lambda: SimpleNamespace(setAudioSource=Mock())
    energy = 'Check' + kind + 'Threshold'
    transcript = 'Transcription' + ('Send' if source == 'mic' else 'Receive')
    result = SimpleNamespace(c=c, config=config, dm=dm, session=session, opened=opened, calls=calls,
        source=source, a=a, b=b, devices=devices, backend=backend,
        worker=getattr(backend, source+'_lifecycle_worker'),
        enable=lambda feature: getattr(c, 'setEnable'+(energy if feature == 'energy' else transcript))(),
        disable=lambda feature: getattr(c, 'setDisable'+(energy if feature == 'energy' else transcript))(),
        energy_flag='ENABLE_CHECK_ENERGY_'+suffix, transcript_flag='ENABLE_TRANSCRIPTION_'+suffix,
        id_key='SELECTED_'+source.upper()+'_DEVICE_ID')
    yield result
    session._stop()


@pytest.mark.parametrize('feature', ['energy', 'transcript'])
def test_off_wins_over_queued_restart_even_after_on_again(rig, feature):
    r = rig
    assert r.enable(feature)['result'] is True
    r.c._queueAudioReconciliation(r.source)
    old_job = next(iter(r.worker.jobs.values()))
    assert r.disable(feature)['result'] is False
    old_job()
    assert r.session._recorder is None
    assert len(r.opened) == 1
    assert r.enable(feature)['result'] is True
    old_job()
    assert len(r.opened) == 2
    assert r.session._active_device == r.a


@pytest.mark.parametrize('feature', ['energy', 'transcript'])
def test_off_cleans_owner_even_when_flag_is_already_false(rig, feature):
    r = rig
    r.enable(feature)
    recorder = r.session._recorder
    setattr(r.config, r.energy_flag if feature == 'energy' else r.transcript_flag, False)
    r.disable(feature)
    recorder.stop.assert_called_once()
    assert not r.session.features


def test_auto_on_reconciles_active_device_and_publishes_one_notice(rig):
    r = rig
    r.enable('energy')
    getattr(r.c, 'setEnableAuto'+r.source.capitalize()+'Select')()
    r.worker.drain()
    assert r.session._active_device == r.b
    assert getattr(r.config, r.id_key) == 'endpoint-b'
    assert len(r.opened) == 2
    notices = [v for _, endpoint, v in r.calls if endpoint == '/run/audio_device_switched']
    assert notices == [{'source': r.source, 'old_device': {'id': 'endpoint-a', 'name': 'Device A'},
                        'new_device': {'id': 'endpoint-b', 'name': 'Device B'}}]


def test_auto_off_during_refresh_preserves_user_capture(rig):
    r = rig
    r.enable('energy')
    entered, release = Event(), Event()
    def refresh():
        entered.set()
        assert release.wait(2)
        r.c._queueAudioReconciliation(r.source)
    r.dm.update.side_effect = refresh
    thread = Thread(target=getattr(r.c, 'setEnableAuto'+r.source.capitalize()+'Select'))
    thread.start()
    try:
        assert entered.wait(1)
        getattr(r.c, 'setDisableAuto'+r.source.capitalize()+'Select')()
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    r.worker.drain()
    assert r.session._active_device == r.a
    assert getattr(r.config, r.energy_flag) is True
    assert len(r.opened) == 1


def test_manual_hotplug_continues_and_reports_actual_device(rig):
    r = rig
    r.enable('energy')
    r.devices.remove(r.a)
    getattr(r.c, 'update'+r.source.capitalize()+'DeviceList')()
    # A remains displayed until the queued switch has actually succeeded.
    assert getattr(r.config, r.id_key) == 'endpoint-a'
    options = [value for _, endpoint, value in r.calls
               if endpoint == '/run/selectable_'+r.source+'_device_options'][-1]
    assert {'id': 'endpoint-a', 'label': 'Device A'} in options
    r.worker.drain()
    assert r.session._active_device == r.b
    assert getattr(r.config, r.id_key) == 'endpoint-b'
    options = getattr(r.c, 'get'+r.source.capitalize()+'DeviceOptions')()['result']
    assert options == [{'id': 'endpoint-b', 'label': 'Device B'}]
    assert len([e for _, e, _ in r.calls if e == '/run/audio_device_switched']) == 1


def test_explicit_open_failure_uses_identified_alternate(rig):
    r = rig
    create = r.session._create_recorder
    def fail_a(device):
        if device['id'] == 'endpoint-a':
            raise OSError('busy')
        return create(device)
    r.session._create_recorder = fail_a
    assert r.enable('energy')['result'] is True
    assert r.session._active_device == r.b
    assert getattr(r.config, r.id_key) == 'endpoint-b'
    assert len([e for _, e, _ in r.calls if e == '/run/audio_device_switched']) == 1


def test_duplicate_labels_resolve_by_id_and_legacy_names_only_when_unique(rig):
    r = rig
    r.b['name'] = r.a['name']
    setattr(r.config, r.id_key, 'endpoint-b')
    assert r.c._selectedAudioDevice(r.source) is r.b
    setattr(r.config, r.id_key, '')
    assert r.c._selectedAudioDevice(r.source) is None
    for _ in range(2):
        r.c._queueAudioReconciliation(r.source)
    assert getattr(r.config, r.id_key) == ''
    assert not r.opened
    r.devices.remove(r.b)
    r.c._queueAudioReconciliation(r.source)
    assert getattr(r.config, r.id_key) == 'endpoint-a'
    assert not r.opened


def test_same_endpoint_format_change_restarts_capture(rig):
    r = rig
    r.enable('energy')
    r.devices[0] = dict(r.a, defaultSampleRate=16000, maxInputChannels=1)
    r.c._queueAudioReconciliation(r.source)
    r.worker.drain()
    assert len(r.opened) == 2
    assert r.session._active_device['defaultSampleRate'] == 16000


@pytest.mark.parametrize('transcript', [False, True])
def test_recorder_error_clears_every_feature_without_consumers(rig, transcript):
    r = rig
    r.enable('energy')
    if transcript:
        r.enable('transcript')
    recorder = r.session._recorder
    epoch = r.backend.message_delivery.snapshot(r.source)
    cleanup_delivery = []
    recorder.stop.side_effect = lambda **kwargs: cleanup_delivery.append(
        r.backend.message_delivery.current(r.source, epoch))
    completed = Event()
    original = r.c.run
    def run(status, endpoint, result):
        original(status, endpoint, result)
        if endpoint == '/run/transcription_recognition_error':
            completed.set()
    r.c.run = run
    recorder.device_error_event.set()
    assert r.worker.queued.wait(2)
    r.worker.drain()
    assert completed.wait(2)
    assert not r.session.features
    assert cleanup_delivery == [not transcript]
    assert not getattr(r.config, r.energy_flag)
    assert not getattr(r.config, r.transcript_flag)
    assert (200, '/set/disable/check_'+r.source+'_threshold', False) in r.calls
    assert (200, '/run/check_'+r.source+'_volume', 0) in r.calls


def test_meter_missing_device_returns_false(rig):
    r = rig
    r.devices.clear()
    assert r.enable('energy') == {'status': 200, 'result': False}
    assert not r.session.features
    assert not getattr(r.config, r.energy_flag)


@pytest.fixture
def opener(monkeypatch):
    monkeypatch.setattr(recorders, '_MIC_OPEN_TIMEOUT_SEC', 0.02)
    monkeypatch.setattr(recorders, '_openers', {})
    yield
    for owner in recorders._openers.values():
        owner.thread.join(2)
        assert not owner.thread.is_alive()


def test_cancelled_lock_waiter_never_opens_after_timeout(opener, monkeypatch):
    microphone = Mock()
    monkeypatch.setattr(recorders, 'Microphone', microphone)
    with recorders.pyaudio_op_lock:
        with pytest.raises(recorders.AudioOpenBusy, match='Timed out'):
            recorders._create_microphone({}, device_index=1)
    recorders._openers['mic'].thread.join(1)
    microphone.assert_not_called()


def test_late_native_open_retains_owner_rejects_overlap_and_closes(opener, monkeypatch):
    entered, release = Event(), Event()
    class Source:
        stream = None
        def __enter__(self):
            entered.set()
            assert release.wait(2)
            self.stream = object()
        def __exit__(self, *args):
            self.stream = None
            closed.set()
    closed = Event()
    microphone = Mock(return_value=Source())
    monkeypatch.setattr(recorders, 'Microphone', microphone)
    try:
        with pytest.raises(recorders.AudioOpenBusy):
            recorders._create_microphone({'device_index': 2}, device_index=1)
        assert entered.is_set()
        with pytest.raises(recorders.AudioOpenBusy, match='outstanding'):
            recorders._create_microphone({}, device_index=3)
        assert microphone.call_count == 1
    finally:
        release.set()
    assert closed.wait(1)


def test_cancel_before_fallback_does_not_open_another_device(opener, monkeypatch):
    release = Event()
    def microphone(**kwargs):
        assert release.wait(2)
        raise OSError('device failed')
    call = Mock(side_effect=microphone)
    monkeypatch.setattr(recorders, 'Microphone', call)
    try:
        with pytest.raises(recorders.AudioOpenBusy):
            recorders._create_microphone({'device_index': 2}, device_index=1)
    finally:
        release.set()
    recorders._openers['mic'].thread.join(1)
    assert call.call_count == 1


def test_read_error_before_hotplug_notification_reconciles_once(rig):
    r = rig
    r.enable('energy')
    r.enable('transcript')
    recorder = r.session._recorder
    epoch = r.backend.message_delivery.snapshot(r.source)
    cleanup_delivery = []
    recorder.stop.side_effect = lambda **kwargs: cleanup_delivery.append(
        r.backend.message_delivery.current(r.source, epoch))
    r.dm.update.side_effect = lambda: r.devices.remove(r.a)
    recorder.device_error_event.set()
    assert r.worker.queued.wait(2)
    r.worker.drain()
    assert r.session._active_device == r.b
    assert getattr(r.config, r.id_key) == 'endpoint-b'
    assert getattr(r.config, r.energy_flag) is True
    assert getattr(r.config, r.transcript_flag) is True
    assert cleanup_delivery == [True]
    assert r.backend.message_delivery.current(r.source, epoch)
    assert len([e for _, e, _ in r.calls if e == '/run/audio_device_switched']) == 1


@pytest.mark.parametrize('transcript', [False, True])
def test_device_loss_revokes_only_transcription_before_real_session_cleanup(rig, transcript):
    r = rig
    r.enable('energy')
    if transcript:
        r.enable('transcript')
    epoch = r.backend.message_delivery.snapshot(r.source)
    cleanup_delivery = []
    r.session._recorder.stop.side_effect = lambda **kwargs: cleanup_delivery.append(
        r.backend.message_delivery.current(r.source, epoch))
    r.devices.clear()
    getattr(r.c, 'update'+r.source.capitalize()+'DeviceList')()
    r.worker.drain()
    assert cleanup_delivery == [not transcript]
    assert r.backend.message_delivery.current(r.source, epoch) is not transcript
    assert not r.session.features
    assert not getattr(r.config, r.transcript_flag)
    assert not getattr(r.config, r.energy_flag)


def test_start_failure_revokes_before_partial_recorder_cleanup(rig):
    r = rig
    epoch = r.backend.message_delivery.snapshot(r.source)
    cleanup_delivery = []
    create = r.session._create_recorder
    def recording(device):
        recorder = create(device)
        recorder.stop.side_effect = lambda **kwargs: cleanup_delivery.append(
            r.backend.message_delivery.current(r.source, epoch))
        # Recognizer preparation precedes capture now. Fail listener startup
        # to retain this test's partially opened recorder cleanup boundary.
        recorder.recordIntoQueue = Mock(side_effect=RuntimeError('audio listener unavailable'))
        return recorder
    r.session._create_recorder = recording
    assert r.enable('transcript')['result'] is False
    assert cleanup_delivery == [False]
    assert not r.session.features


def test_missing_device_when_adding_transcription_clears_existing_meter(rig):
    r = rig
    r.enable('energy')
    r.devices.clear()
    assert r.enable('transcript')['result'] is False
    assert not r.session.features
    assert not getattr(r.config, r.energy_flag)
    assert not getattr(r.config, r.transcript_flag)
    assert (200, '/set/disable/check_'+r.source+'_threshold', False) in r.calls
    assert (200, '/run/check_'+r.source+'_volume', 0) in r.calls


def test_runtime_cleanup_timeout_keeps_its_distinct_error(rig, monkeypatch):
    r = rig
    r.enable('transcript')
    recorder = r.session._recorder
    release = Event()
    recorder.stop.side_effect = lambda **kwargs: release.wait(2)
    monkeypatch.setattr(model_module, 'TRANSCRIPT_STOP_JOIN_TIMEOUT', 0.01)
    try:
        recorder.device_error_event.set()
        assert r.worker.queued.wait(2)
        r.worker.drain()
        failure = [value for _, endpoint, value in r.calls
                   if endpoint == '/run/transcription_recognition_error'][-1]
        assert failure['error_code'] == 'CLEANUP_TIMEOUT'
        assert failure['stage'] == 'cleanup'
        assert r.session._cleanup_workers
        assert not getattr(r.config, r.transcript_flag)
    finally:
        release.set()
        for worker in r.session._cleanup_workers:
            worker.join(2)


def test_off_invalidates_read_error_recovery(rig):
    r = rig
    r.enable('energy')
    r.session._recorder.device_error_event.set()
    assert r.worker.queued.wait(2)
    r.disable('energy')
    r.worker.drain()
    assert r.session._recorder is None
    assert len(r.opened) == 1
    r.dm.update.assert_not_called()


def test_old_read_recovery_cannot_stop_replacement(rig):
    r = rig
    r.enable('energy')
    r.enable('transcript')
    epoch = r.backend.message_delivery.snapshot(r.source)
    generation = r.c._audioGeneration(r.source)
    opened_before = len(r.opened)
    r.c._queueAudioReconciliation(r.source)
    reconcile = next(iter(r.worker.jobs.values()))
    r.worker.jobs.clear()
    r.worker.queued.clear()
    first = r.session._recorder
    first.device_error_event.set()
    assert r.worker.queued.wait(2)
    recovery = next(iter(r.worker.jobs.values()))
    r.worker.jobs.clear()
    reconcile()
    second = r.session._recorder
    assert second is not first and len(r.opened) == opened_before + 1
    recovery()
    assert r.session._recorder is second
    assert getattr(r.config, r.energy_flag) and getattr(r.config, r.transcript_flag)
    assert r.c._audioGeneration(r.source) == generation
    assert r.backend.message_delivery.current(r.source, epoch)
    second.stop.assert_not_called()
    r.dm.update.assert_not_called()


def test_late_old_error_does_not_consume_replacement_notification(rig, monkeypatch):
    r = rig
    r.enable('energy')
    first = r.session._recorder
    pending = []
    real_thread = model_module.Thread

    class PendingError:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            pending.append(self.target)

    monkeypatch.setattr(model_module, 'Thread', PendingError)
    first.device_error_event.set()
    assert len(pending) == 1
    monkeypatch.setattr(model_module, 'Thread', real_thread)
    r.devices.remove(r.a)
    r.c._queueAudioReconciliation(r.source)
    r.worker.drain()
    second = r.session._recorder
    assert second is not first and r.session._active_device == r.b
    pending.pop()()
    assert not r.session._pipeline_error_notified
    assert not r.worker.jobs
    r.worker.queued.clear()
    second.device_error_event.set()
    assert r.worker.queued.wait(2)
    r.worker.drain()
    assert r.session._recorder is None
    assert not getattr(r.config, r.energy_flag)
    second.stop.assert_called_once()
    failures = [value for _, endpoint, value in r.calls
                if endpoint == '/run/transcription_recognition_error']
    assert len(failures) == 1 and failures[0]['error_code'] == 'AUDIO_READ_ERROR'
    assert 'capture_revision' not in failures[0]


def test_read_recovery_rechecks_owner_after_enumeration(rig):
    r = rig
    r.enable('energy')
    first = r.session._recorder
    first.device_error_event.set()
    assert r.worker.queued.wait(2)
    r.dm.update.side_effect = lambda: r.c._reconcileAudio(r.source)
    r.worker.drain()
    second = r.session._recorder
    assert second is not None and second is not first
    assert getattr(r.config, r.energy_flag)
    second.stop.assert_not_called()


def test_runtime_notification_rechecks_owner_under_source_lock(rig):
    r = rig
    r.enable('energy')
    queued = []
    notify = r.session.runtime_error_fnc
    completed = Event()

    def capture(failure):
        queued.append(failure)
        completed.set()

    r.session.runtime_error_fnc = capture
    r.session._recorder.device_error_event.set()
    assert completed.wait(2)
    r.c._reconcileAudio(r.source)
    second = r.session._recorder
    notify(queued[0])
    assert not r.worker.jobs
    assert r.session._recorder is second
    assert not r.session._pipeline_error_notified
    second.stop.assert_not_called()


@pytest.mark.parametrize('session_type', [MicSession, SpeakerSession])
def test_stop_before_listener_entry_closes_retained_stream_once(session_type):
    class Source:
        def __init__(self):
            self.pa = SimpleNamespace(is_stopped=lambda: False, stop_stream=Mock())
            self.stream = SimpleNamespace(pyaudio_stream=self.pa)
            self.audio = SimpleNamespace(terminate=Mock())
            self.exits = 0

        def __exit__(self, *args):
            self.exits += 1
            self.stream = None
            self.audio.terminate()

    source = Source()
    wrapped = recorders._LockedAudioSource(source)
    release, rejected = Event(), Event()

    def listener():
        assert release.wait(2)
        try:
            with wrapped:
                raise AssertionError('cancelled listener entered')
        except OSError:
            rejected.set()

    thread = Thread(target=listener)
    thread.start()

    def raw_stop(*, wait_for_stop):
        release.set()
        thread.join(2)
        assert not thread.is_alive()

    stopper = recorders._wrapStopperWithBlockingReadUnblock(wrapped, raw_stop)
    session = session_type()
    session.features = {'energy'}
    session._recorder = SimpleNamespace(source=wrapped, stop=stopper, resume=lambda: None)
    try:
        assert session._stop() is False
        assert rejected.is_set()
        assert session._recorder is None and not session._cleanup_workers
        assert source.exits == 1 and source.stream is None
        wrapped.close()
        wrapped.close()
        assert source.exits == 1
        source.audio.terminate.assert_called_once()
    finally:
        release.set()
        thread.join(2)


@pytest.mark.parametrize('source_kind', ['mic', 'speaker'])
@pytest.mark.parametrize('native_id', ['endpoint-A', 'endpoint-B', None])
def test_open_rechecks_injected_native_identity(monkeypatch, source_kind, native_id):
    import device_manager as devices_module

    info = dict(name='USB audio' + (' [Loopback]' if source_kind == 'speaker' else ''),
                hostApi=0, index=1, maxInputChannels=2, defaultSampleRate=48000,
                isLoopbackDevice=source_kind == 'speaker')
    audio = SimpleNamespace(
        get_device_info_by_index=lambda index: dict(info),
        get_host_api_info_by_index=lambda index: {'name': 'WASAPI', 'deviceCount': 1},
        get_device_info_by_host_api_device_index=lambda host, index: dict(info),
    )

    class Source:
        stream = None
        exits = 0

        def __enter__(self):
            self.stream = object()

        def __exit__(self, *args):
            self.exits += 1
            self.stream = None

    source = Source()
    source.audio = audio
    monkeypatch.setattr(recorders, 'Microphone', lambda **kwargs: source)
    endpoints = Mock(return_value={'USB audio': [native_id]} if native_id else {})
    monkeypatch.setattr(devices_module.DeviceManager, '_windowsEndpointIds', endpoints)
    selected = dict(info, endpoint_id='endpoint-A', id=f'{source_kind}:WASAPI:endpoint-A')
    if native_id == 'endpoint-B':
        with pytest.raises(OSError, match='endpoint changed'):
            recorders._open_with_fallback({}, device_index=1, expected_device=selected)
        assert source.exits == 1 and source.stream is None
    else:
        result = recorders._open_with_fallback({}, device_index=1, expected_device=selected)
        assert result is source
        if native_id:
            assert source.opened_device['endpoint_id'] == native_id
        else:
            assert 'endpoint_id' not in source.opened_device
            assert source.opened_device['id'].startswith('pa:')
            assert source.opened_device['name'] == info['name']
        source.__exit__(None, None, None)
    endpoints.assert_called_once()


@pytest.mark.parametrize('unavailable', ['duplicate_portaudio', 'duplicate_native', 'enumeration_error', 'null_id'])
def test_unresolved_open_does_not_claim_requested_identity(monkeypatch, unavailable):
    import device_manager as devices_module

    info = dict(name='USB audio', hostApi=0, index=1, maxInputChannels=1)
    if unavailable == 'null_id':
        info['endpoint_id'] = None
    endpoints = {'USB audio': ['endpoint-A', 'endpoint-B']} if unavailable == 'duplicate_native' else {}
    if unavailable == 'duplicate_portaudio':
        endpoints = {'USB audio': ['endpoint-A']}
    monkeypatch.setattr(devices_module.DeviceManager, '_windowsEndpointIds', lambda **kwargs: endpoints)
    host = Mock(return_value={'name': 'WASAPI', 'deviceCount': 2 if unavailable == 'duplicate_portaudio' else 1})
    if unavailable == 'enumeration_error':
        host.side_effect = OSError('enumeration unavailable')
    source = SimpleNamespace(stream=object(), audio=SimpleNamespace(
        get_device_info_by_index=lambda index: dict(info),
        get_host_api_info_by_index=host,
        get_device_info_by_host_api_device_index=lambda host, index: dict(info, index=index + 1)))
    monkeypatch.setattr(recorders, 'Microphone', lambda **kwargs: source)
    monkeypatch.setattr(recorders, '_validate_audio_source', lambda value: value)
    selected = dict(info, endpoint_id='endpoint-A', id='mic:WASAPI:endpoint-A')
    assert recorders._open_with_fallback({}, device_index=1, expected_device=selected) is source
    assert not source.opened_device.get('endpoint_id')
    assert source.opened_device['id'].startswith('pa:')


def test_unverified_open_publishes_actual_device(rig):
    r = rig
    actual = dict(r.a, id='pa:opened-slot', host_name='Host')
    create = r.session._create_recorder

    def recording(device):
        recorder = create(device)
        recorder.source = SimpleNamespace(opened_device=actual)
        return recorder

    r.session._create_recorder = recording
    assert r.enable('energy')['result'] is True
    assert r.session._active_device == actual
    assert getattr(r.config, r.id_key) == actual['id']
    assert r.config.SELECTED_MIC_HOST == 'Host'
    notices = [v for _, endpoint, v in r.calls if endpoint == '/run/audio_device_switched']
    assert notices == [{'source': r.source,
                        'old_device': {'id': r.a['id'], 'name': r.a['name']},
                        'new_device': {'id': actual['id'], 'name': actual['name']}}]


def test_opened_stream_is_reused_and_cancel_prevents_later_open(opener, monkeypatch):
    class Source:
        stream = None
        enters = 0
        audio = SimpleNamespace(get_device_info_by_index=lambda index: {'name': 'A'})
        def __enter__(self):
            self.enters += 1
            self.stream = object()
        def __exit__(self, *args):
            self.stream = None
    source = Source()
    monkeypatch.setattr(recorders, 'Microphone', lambda **kwargs: source)
    wrapped = recorders._create_microphone({}, device_index=1, expected_device={'name': 'A'})
    with wrapped:
        assert source.enters == 1
    wrapped.cancel()
    with pytest.raises(OSError, match='cancelled'):
        wrapped.__enter__()
    assert source.enters == 1


def test_reused_index_cannot_be_published_as_previous_device(opener, monkeypatch):
    closed = Event()
    class Source:
        stream = None
        audio = SimpleNamespace(get_device_info_by_index=lambda index: {'name': 'B'})
        def __enter__(self):
            self.stream = object()
        def __exit__(self, *args):
            self.stream = None
            closed.set()
    monkeypatch.setattr(recorders, 'Microphone', lambda **kwargs: Source())
    with pytest.raises(OSError, match='endpoint changed'):
        recorders._create_microphone({}, device_index=1, expected_device={'name': 'A'})
    assert closed.is_set()


def test_recorder_initialization_failure_closes_preopened_source(monkeypatch):
    source = SimpleNamespace(close=Mock())
    monkeypatch.setattr(recorders, '_create_microphone', lambda *args, **kwargs: source)
    monkeypatch.setattr(recorders, 'Recognizer', Mock(side_effect=RuntimeError('init failed')))
    with pytest.raises(RuntimeError, match='init failed'):
        recorders.SelectedMicEnergyAndAudioRecorder({'index': 1}, 300, False, 3)
    source.close.assert_called_once()


def test_meter_open_failure_reports_false_and_clears_state(rig):
    r = rig
    r.session._create_recorder = Mock(side_effect=OSError('unavailable'))
    assert r.enable('energy') == {'status': 200, 'result': False}
    assert not r.session.features
    assert not getattr(r.config, r.energy_flag)
    assert (200, '/set/disable/check_'+r.source+'_threshold', False) in r.calls


def test_read_error_with_failed_refresh_reports_termination(rig):
    r = rig
    r.enable('energy')
    r.dm.update.side_effect = RuntimeError('enumeration failed')
    r.session._recorder.device_error_event.set()
    assert r.worker.queued.wait(2)
    r.worker.drain()
    assert not getattr(r.config, r.energy_flag)
    assert (200, '/run/check_'+r.source+'_volume', 0) in r.calls


def test_legacy_name_endpoint_rejects_duplicates_but_id_endpoint_selects(rig):
    r = rig
    r.b['name'] = r.a['name']
    method = getattr(r.c, 'setSelected'+r.source.capitalize()+'Device')
    assert method(r.a['name'])['status'] == 400
    method = getattr(r.c, 'setSelected'+r.source.capitalize()+'DeviceId')
    assert method('endpoint-b') == {'status': 200, 'result': 'endpoint-b'}
    assert not r.opened


def test_native_open_owner_also_blocks_realtime_handoff(opener, monkeypatch):
    release = Event()
    def microphone(**kwargs):
        assert release.wait(2)
        raise OSError('open returned late')
    monkeypatch.setattr(recorders, 'Microphone', microphone)
    try:
        with pytest.raises(recorders.AudioOpenBusy):
            recorders._create_microphone({}, device_index=1)
        assert MicSession().stop_for_handoff() is False
    finally:
        release.set()
    recorders._openers['mic'].thread.join(1)
    assert MicSession().stop_for_handoff() is True
