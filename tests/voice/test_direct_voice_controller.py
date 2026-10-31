"""Real Controller/stdio keep explicit input intent independent of TTS and mute."""
from queue import Queue

import pytest
from models.voice_conversion.settings import DirectSettings

from test_controller_integration import controller_module  # noqa: F401
from test_priority_cancel import mainloop_module, wire_message  # noqa: F401
from test_source_bridge import Backend, module, until
from test_managed_route import Gate, ready
from test_source_selection import ID


@pytest.fixture
def app(controller_module, monkeypatch):  # noqa: F811
    m, backend, gate = module(), Backend(), Gate()
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(m, '_read_graph', backend.read)
    monkeypatch.setattr(m, '_launch', backend.launch)
    monkeypatch.setattr(m, '_unmute', backend.unmute)
    monkeypatch.setattr(m, 'MONITOR_INTERVAL', .005)
    monkeypatch.setattr(controller_module, 'PipeWireGate', lambda: gate)
    controller = controller_module.Controller()
    yield controller, backend, gate, controller_module
    backend.release.set()
    if hasattr(controller, 'direct_voice'):
        assert controller.direct_voice.close()
    controller.voice_route.close()
    controller.voice_events.close()


def request(controller, source=ID):
    return {'source': source, '_direct_generation': controller.direct_voice.health()['generation']}


def managed(controller):
    assert controller.setVoiceSettings({'routing': 'managed'})['status'] == 200
    ready(controller.voice_route)


def start(controller):
    response = controller.startDirectVoice(request(controller))
    assert response['status'] == 200, response
    until(lambda: controller.getDirectVoiceState()['result']['active'])


def test_default_off_explicit_start_and_tts_stop_are_independent(app):
    c, b, gate, _ = app
    assert c.getDirectVoiceState()['result']['source'] is None
    assert c.getDirectVoiceSources()['result']['sources'] == [{'id': ID, 'label': 'external.source'}]
    assert not b.children
    assert c.startDirectVoice(request(c))['status'] == 409  # external routing
    managed(c)
    start(c)
    assert gate.muted  # selecting/starting never resumes the final gate
    assert not c.getDirectVoiceState()['result']['conversion_verified']
    c.stopVoice()
    assert c.getDirectVoiceState()['result']['active']
    tts_generation = c.voice_events.generation()
    c.stopDirectVoice()
    assert not c.getDirectVoiceState()['result']['requested']
    assert c.voice_events.generation() == tts_generation
    assert b.children[0].poll() is not None


def test_tts_settings_continue_input_but_route_change_requires_explicit_stop(app):
    c, b, gate, _ = app
    managed(c)
    start(c)
    assert c.setVoiceSettings({'routing': 'managed', 'mode': 'translated', 'target_slot': '2'})['status'] == 200
    assert c.getDirectVoiceState()['result']['active'] and b.children[0].poll() is None
    response = c.setVoiceSettings({'routing': 'external', 'mode': 'off'})
    assert response == {'status': 409, 'result': {'error_code': 'direct_voice_stop_required'}}
    assert c.getDirectVoiceState()['result']['requested']
    assert c.voice_events.settings.routing == 'managed'
    assert b.children[0].poll() is None
    c.stopDirectVoice()
    until(lambda: not c.direct_voice.health()['stopping'])
    assert c.setVoiceSettings({'routing': 'external', 'mode': 'off'})['status'] == 200
    assert not c.getDirectVoiceState()['result']['requested']
    assert b.children[0].poll() is not None


def test_route_change_rejected_during_inflight_launch_until_explicit_stop(app):
    c, b, gate, _ = app
    managed(c)
    b.block_at = 'launch'
    assert c.startDirectVoice(request(c))['status'] == 200
    assert b.enter.wait(1)
    assert c.setVoiceSettings({'routing': 'external'})['status'] == 409
    assert c.voice_events.settings.routing == 'managed'
    c.stopDirectVoice()
    b.release.set()
    assert c.direct_voice.close()
    assert not b.unmutes
    assert all(child.poll() is not None for child in b.children)


def test_restart_never_restores_input_and_shutdown_rejects_late_start(app):
    c, b, gate, mod = app
    managed(c)
    start(c)
    old = request(c)
    assert c.shutdown()['status'] == 200
    assert c.startDirectVoice(old)['status'] == 409
    assert not c.direct_voice.health()['requested']
    other = mod.Controller()
    try:
        assert other.direct_voice.health()['source'] is None
        assert not other.direct_voice.health()['requested']
        assert len(b.children) == 1 and b.children[0].poll() is not None
    finally:
        other.direct_voice.close()
        other.voice_route.close()
        other.voice_events.close()


@pytest.mark.parametrize('bad', [None, {}, {'source': ID}, {'source': ID, '_direct_generation': True},
                               {'source': {**ID, 'serial': 110}, '_direct_generation': 0}])
def test_bad_input_request_does_not_open_audio(app, bad):
    c, b, *_ = app
    managed(c)
    assert c.startDirectVoice(bad)['status'] == 400
    assert not b.children and not c.direct_voice.health()['requested']


def test_windows_and_enumeration_failure_are_explicit(app, monkeypatch):
    c, b, *_ = app
    b.query_error = True
    assert c.getDirectVoiceSources()['result'] == {'sources': [], 'error': 'source_bridge_graph_unavailable', 'preferred': None}
    monkeypatch.setattr(module().sys, 'platform', 'win32')
    assert c.getDirectVoiceSources()['result'] == {'sources': [], 'error': 'source_bridge_linux_only', 'preferred': None}
    assert c.startDirectVoice(request(c))['result']['error_code'] == 'source_bridge_linux_only'
    assert not b.children


def test_receiver_input_stop_bypasses_queue_and_invalidates_delayed_start(mainloop_module, monkeypatch):  # noqa: F811
    mod, pending, responses = mainloop_module, Queue(), Queue()
    c = mod.controller
    monkeypatch.setattr(module().sys, 'platform', 'linux')
    c.voice_route.gate = Gate()  # inactive OS dependency; routing state remains real
    managed(c)
    generation = c.direct_voice.health()['generation']
    main = mod.Main(c, mod.main_instance.mapping)
    monkeypatch.setattr(mod.sys, 'stdin', type('Input', (), {'readline': lambda self: pending.get()})())
    monkeypatch.setattr(mod, 'printResponse', lambda status, endpoint, result: responses.put((status, endpoint, result)))
    main.startReceiver()  # no handlers: ordinary work stays queued
    try:
        pending.put(wire_message('/run/start_direct_voice', {'source': ID, '_direct_generation': generation + 999}))
        pending.put(wire_message('/run/stop_direct_voice'))
        status, endpoint, result = responses.get(timeout=1)
        assert endpoint == '/run/stop_direct_voice' and status == 200
        assert not result['requested'] and result['generation'] > generation
        queued_endpoint, data, _ = main.queue.get(timeout=1)
        assert data['_direct_generation'] == generation  # forged frontend value overwritten
        result, status = main._call_handler(queued_endpoint, data)
        assert status == 409 and result['error_code'] == 'source_bridge_stale_start'
        assert not c.direct_voice.health()['requested']
    finally:
        main._stop_event.set()
        pending.put('')
        for thread in main._threads:
            thread.join(2)
        c.direct_voice.close()


class ConvertedBackend:
    def __init__(self):
        self.state = dict(requested=False, active=False, pending=False, stopping=False,
                          conversion_verified=False, error=None, state='off')
    def start(self, *, source):
        self.state.update(requested=True, active=True, state='ready')
    def stop(self):
        self.state.update(requested=False, active=False, state='stopped')
    def close(self, timeout=3):
        self.stop()
        return True
    def health(self):
        return dict(self.state)


@pytest.mark.parametrize("engine", ["seed-vc", "rvc"])
def test_converted_choice_is_independent_and_failure_has_no_raw_fallback(app, monkeypatch, engine):
    from models.voice_conversion import isolated
    c, raw, gate, _ = app
    converted, options = ConvertedBackend(), []
    monkeypatch.setattr(isolated, 'IsolatedVCProcess',
                        lambda value: options.append(value) or converted)
    managed(c)
    choice = ({'runtime': '/permitted/runtime', 'reference': '/permitted/reference.wav'}
              if engine == 'seed-vc' else dict(engine='rvc', runtime='/rvc', model='/voice.pth',
                                              index='', pitch=0, index_rate=0.0))
    response = c.startDirectVoice({**request(c), 'mode': 'converted', 'options': choice})
    assert response['status'] == 200
    state = c.getDirectVoiceState()['result']
    assert state['mode'] == 'converted' and state['conversion_state'] == 'ready'
    assert state['active'] and not state['conversion_verified']
    assert options == [choice] and not raw.children and gate.muted
    converted.state.update(conversion_verified=True, state='converted')
    assert c.getDirectVoiceState()['result']['conversion_verified']
    c.stopVoice()
    assert c.getDirectVoiceState()['result']['active']
    assert c.startDirectVoice(request(c))['result']['error_code'] == 'vc_stop_required'
    converted.state.update(error='vc_worker_eof', requested=False, active=False)
    state = c.getDirectVoiceState()['result']
    assert not state['requested'] and state['error'] == 'vc_worker_eof'
    assert not raw.children


@pytest.mark.parametrize('extra', [{'mode': 'other'}, {'mode': None}, {'options': {'runtime': '/x'}},
    {'mode': 'converted', 'options': None}, {'mode': 'converted', 'options': {}},
    {'mode': 'converted', 'options': {'runtime': '/x', 'reference': '/y', 'download': True}}])
def test_invalid_conversion_payload_never_opens_original(app, extra):
    c, raw, *_ = app
    managed(c)
    assert c.startDirectVoice({**request(c), **extra})['status'] == 400
    assert not raw.children and not c.direct_voice.health()['requested']


def test_saved_vc_choices_survive_restart_but_do_not_start_or_change_old_payload(app):
    c, raw, gate, mod = app
    managed(c)
    old = request(c)
    choices = {'mode': 'converted', 'runtime': '/allowed/runtime', 'reference': '/allowed/ref.wav'}
    assert c.setDirectVoiceSettings(choices)['status'] == 200
    assert c.getDirectVoiceState()['result']['settings'] == DirectSettings.from_dict(choices).to_dict()
    assert not raw.children
    assert c.startDirectVoice(old)['result']['error_code'] == 'source_bridge_stale_start'
    # A legacy client omits mode: still means passthrough even with saved VC choices.
    start(c)
    assert c.getDirectVoiceState()['result']['mode'] == 'passthrough'
    assert c.setDirectVoiceSettings(choices)['status'] == 409  # explicit Stop first
    c.stopDirectVoice()
    assert c.direct_voice.close()
    replacement = mod.Controller()
    try:
        state = replacement.getDirectVoiceState()['result']
        assert state['settings'] == DirectSettings.from_dict(choices).to_dict()
        assert not state['requested'] and state['mode'] == 'off'
        assert len(raw.children) == 1
    finally:
        replacement.direct_voice.close()
        replacement.voice_route.close()
        replacement.voice_events.close()
