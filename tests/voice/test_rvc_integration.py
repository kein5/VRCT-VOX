"""RVC control and pipe boundaries without any model or audio device."""
import sys
import time

import pytest

from models.voice_conversion import direct_voice, protocol as p
from models.voice_conversion.settings import DirectSettings, normalize_settings, start_options
from tools.voice_acceptance import wait_for

OPTIONS = dict(engine='rvc', runtime='/allowed/rvc', model='/allowed/voice.pth',
               index='', pitch=0, index_rate=0.0)


def test_legacy_settings_gain_seed_default_without_losing_intent():
    saved = DirectSettings.from_dict(dict(mode='converted', runtime='/seed', reference='/ref.wav'))
    assert getattr(saved, 'engine', None) == 'seed-vc'
    assert saved.runtime == '/seed' and saved.reference == '/ref.wav'
    assert start_options('converted', dict(runtime='/seed', reference='/ref.wav')) == dict(
        runtime='/seed', reference='/ref.wav')


def test_rvc_settings_and_options_round_trip_without_installed_models():
    data = dict(mode='converted', engine='rvc', rvc_runtime='/not-installed',
                rvc_model='/permitted.pth', rvc_index='', rvc_pitch=-12, rvc_index_rate=0.0)
    saved = normalize_settings(data)
    assert saved is not None and saved['engine'] == 'rvc'
    assert DirectSettings.from_dict(saved).to_dict() == saved
    assert start_options('converted', OPTIONS) == OPTIONS


@pytest.mark.parametrize('change', [dict(engine='unknown'), dict(pitch=True), dict(pitch=25),
    dict(pitch=1.5), dict(index_rate=float('nan')), dict(index_rate=True), dict(index_rate=1.1),
    dict(index_rate=.5), dict(model='/x.wav'), dict(index='/x.txt'), dict(runtime=''),
    dict(download=True)])
def test_invalid_rvc_options_rejected(change):
    with pytest.raises(ValueError):
        start_options('converted', dict(OPTIONS, **change))


def test_ready_handshake_binds_engine_to_session():
    ready = dict(p.ready_info('a'*32, engine='rvc'), pcm_bytes=0)
    p.require_ready(ready, b'', 'a'*32, engine='rvc')
    with pytest.raises(p.ProtocolError, match='vc_ready_invalid'):
        p.require_ready(ready, b'', 'a'*32)
    with pytest.raises(p.ProtocolError):
        p.ready_info('a'*32, engine='arbitrary-module')


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux worker')
def test_factory_selects_rvc_without_loading_seed(monkeypatch):
    from models.voice_conversion import rvc_process
    from models.voice_conversion.isolated import IsolatedVCProcess
    received = []
    marker = object()
    monkeypatch.setattr(rvc_process, 'RVCProcess', lambda options: received.append(options) or marker)
    assert isinstance(direct_voice.create_converted_process(OPTIONS), IsolatedVCProcess)
    assert received == [OPTIONS]
    assert direct_voice.create_worker_process(OPTIONS) is marker


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux worker')
def test_missing_rvc_runtime_fails_before_capture():
    with pytest.raises(ValueError, match='vc_runtime_missing'):
        direct_voice.create_converted_process(OPTIONS)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux worker')
@pytest.mark.parametrize('fault, expected', [
    ('converted', None), ('late', 'vc_block_expired'), ('bypass', 'vc_passthrough_forbidden'),
    ('wrong_session', 'vc_output_invalid'), ('eof', 'vc_worker_eof'),
    ('wrong_engine', 'vc_ready_invalid'), ('load_stall', None),
])
def test_rvc_uses_same_bounded_stop_and_output_contract(tmp_path, monkeypatch, fault, expected):
    from test_seedvc_live import fixture, send, ready
    with fixture(tmp_path, monkeypatch, mode=fault, engine='rvc') as (vc, captures, children, sent, closed, _):
        if fault == 'load_stall':
            wait_for(lambda: children, timeout=3)
        elif fault == 'wrong_engine':
            wait_for(lambda: vc.health()['error'], timeout=3)
            assert captures == []
        else:
            ready(vc, captures)
            assert not vc.health()['conversion_verified']
            send(captures[-1])
            wait_for(lambda: vc.health()['conversion_verified'] or vc.health()['error'], timeout=3)
        if expected:
            assert vc.health()['error'] == expected
            assert sent == []
        elif fault == 'converted':
            assert vc.health()['conversion_verified'] and len(sent) == 1
        vc.stop()
        before = list(sent)
        if captures:
            send(captures[-1])
        assert vc.close(3)
        assert sent == before and not vc.health()['active']
