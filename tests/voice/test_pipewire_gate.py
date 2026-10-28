import copy

import pytest


def graph():
    return [
        {'type': 'PipeWire:Interface:Core', 'info': {'cookie': 42}},
        {'type': 'PipeWire:Interface:Node', 'info': {
            'props': {'node.name': 'vrct.managed.source', 'media.class': 'Audio/Source',
                      'object.serial': 15, 'vrct.managed.route': 'v1'},
            'params': {'Props': [{'mute': True}]} }},
        *[{'type': 'PipeWire:Interface:Node', 'info': {
            'props': {'node.name': name, 'media.class': 'Audio/Sink', 'vrct.managed.route': 'v1'}}}
          for name in ('vrct.managed.mix', 'vrct.managed.tts', 'vrct.managed.vc')],
    ]


def test_gate_identifies_epoch_and_observed_mute():
    from models.audio_routing.pipewire_gate import parse_graph
    assert parse_graph(graph()) == {'identity': (42, 15), 'muted': True}


@pytest.mark.parametrize('fault', ['duplicate', 'missing', 'props', 'class', 'marker'])
def test_bad_or_ambiguous_graph_cannot_be_treated_as_muted(fault):
    from models.audio_routing.pipewire_gate import parse_graph
    data = graph()
    if fault == 'duplicate':
        data.append(copy.deepcopy(data[1]))
    elif fault == 'missing':
        data.pop()
    elif fault == 'props':
        data[1]['info']['params']['Props'] = []
    elif fault == 'class':
        data[1]['info']['props']['media.class'] = 'Audio/Sink'
    else:
        del data[1]['info']['props']['vrct.managed.route']
    with pytest.raises(RuntimeError):
        parse_graph(data)


def test_pair_reports_direct_branch_identity_and_mute_from_one_snapshot(monkeypatch):
    import json
    from types import SimpleNamespace
    from models.audio_routing import pipewire_gate as module
    data = graph()
    direct = data[-1]['info']
    direct['props']['object.serial'] = 20
    direct['params'] = {'Props': [{'mute': False}]}
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(data))
    monkeypatch.setattr(module.subprocess, 'run', run)
    gate = module.PipeWireGate()
    assert gate.inspect_pair() == {'source': {'identity': (42, 15), 'muted': True},
                                   'direct': {'identity': (42, 20), 'muted': False}}
    assert calls == [['pw-dump']]
    direct['params']['Props'] = []
    with pytest.raises(RuntimeError):
        gate.inspect_pair()


def test_direct_control_uses_fixed_selector_and_rechecks_identity(tmp_path, monkeypatch):
    from models.audio_routing import pipewire_gate as module
    helper = tmp_path / 'gate'
    helper.touch()
    gate = module.PipeWireGate(helper)
    calls = []
    monkeypatch.setattr(module.subprocess, 'run', lambda args, **kwargs: calls.append(args))
    state = {'identity': (42, 20), 'muted': True}
    monkeypatch.setattr(gate, 'inspect_pair', lambda: {'direct': state})
    assert gate.set_direct_muted(True, (42, 20)) == state
    assert calls == [[str(helper), '42', '20', '1', 'vc']]
    state['identity'] = (42, 21)
    with pytest.raises(RuntimeError, match='managed_endpoint_changed'):
        gate.set_direct_muted(True, (42, 20))
