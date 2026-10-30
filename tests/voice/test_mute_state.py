import json

import pytest

from models.tts.tts_scheduler import VoiceEventBus


def test_saved_intent_survives_new_store_and_bad_state_fails_closed(tmp_path):
    from models.audio_routing.mute_state import MuteState
    from models.audio_routing.managed_route import VoiceRoute
    path = tmp_path / 'mute.json'
    assert MuteState(path).read() is False
    MuteState(path).write(True)
    assert MuteState(path).read() is True
    MuteState(path).write(False)
    assert MuteState(path).read() is False
    path.write_text('{broken')
    bus = VoiceEventBus()
    route = VoiceRoute(bus, gate=None, store=MuteState(path))
    try:
        assert bus.status()['muted']
        assert route.status()['error'] == 'mute_state_unavailable'
    finally:
        route.close()
        bus.close()


def test_failed_atomic_replace_preserves_previous_mute(tmp_path, monkeypatch):
    from models.audio_routing import mute_state
    path = tmp_path / 'mute.json'
    state = mute_state.MuteState(path)
    state.write(True)
    def fail(*args):
        raise OSError('disk fault')
    monkeypatch.setattr(mute_state.os, 'replace', fail)
    with pytest.raises(OSError):
        state.write(False)
    assert json.loads(path.read_text()) == {'version': 1, 'muted': True}
    assert list(tmp_path.iterdir()) == [path]
