"""Real Controller/stdio keep explicit input intent independent of TTS and mute."""
from queue import Queue

import pytest

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


def test_tts_settings_continue_input_but_external_routing_stops_it(app):
    c, b, gate, _ = app
    managed(c)
    start(c)
    assert c.setVoiceSettings({'routing': 'managed', 'mode': 'translated', 'target_slot': '2'})['status'] == 200
    assert c.getDirectVoiceState()['result']['active'] and b.children[0].poll() is None
    assert c.setVoiceSettings({'routing': 'external', 'mode': 'off'})['status'] == 200
    assert not c.getDirectVoiceState()['result']['requested']
    assert b.children[0].poll() is not None


def test_leaving_managed_routing_cancels_inflight_launch(app):
    c, b, gate, _ = app
    managed(c)
    b.block_at = 'launch'
    assert c.startDirectVoice(request(c))['status'] == 200
    assert b.enter.wait(1)
    assert c.setVoiceSettings({'routing': 'external'})['status'] == 200
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
    assert c.getDirectVoiceSources()['result'] == {'sources': [], 'error': 'source_bridge_graph_unavailable'}
    monkeypatch.setattr(module().sys, 'platform', 'win32')
    assert c.getDirectVoiceSources()['result'] == {'sources': [], 'error': 'source_bridge_linux_only'}
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
