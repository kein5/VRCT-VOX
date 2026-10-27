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
