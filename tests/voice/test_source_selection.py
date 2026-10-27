"""Input identities survive JSON and cannot silently rebind or reopen after stop."""
import copy
import json
from threading import Thread

import pytest

from test_source_bridge import graph, module, system, until  # noqa: F401


ID = {'cookie': '42', 'serial': '110', 'name': 'external.source', 'media_class': 'Audio/Source'}


def test_enumeration_preserves_full_identity_and_label(monkeypatch):
    m = module()
    data = graph()
    data[1]['info']['props'].update({'object.serial': 2**64 - 1, 'node.description': 'External voice'})
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(m, '_read_graph', lambda: data)
    selected = m.enumerate_sources()
    assert selected == [{'id': {**ID, 'serial': '18446744073709551615'}, 'label': 'External voice'}]
    assert m.parse_source(json.loads(json.dumps(selected[0]['id']))) == m.Endpoint(
        42, 2**64 - 1, 'external.source', 'Audio/Source')


@pytest.mark.parametrize('fault', ['duplicate', 'wrong_class', 'managed_name', 'managed_marker',
                                  'bridge_marker', 'missing_serial', 'bad_serial', 'bad_cookie'])
def test_enumeration_excludes_ambiguous_or_feedback_sources(monkeypatch, fault):
    m, data = module(), graph()
    props = data[1]['info']['props']
    if fault == 'duplicate':
        data.append(copy.deepcopy(data[1]))
    elif fault == 'wrong_class':
        props['media.class'] = 'Audio/Sink'
    elif fault == 'managed_name':
        props['node.name'] = 'vrct.managed.source'
    elif fault.endswith('marker'):
        props['vrct.managed.route' if fault == 'managed_marker' else 'vrct.source.bridge'] = 'v1'
    elif fault == 'missing_serial':
        del props['object.serial']
    elif fault == 'bad_serial':
        props['object.serial'] = True
    else:
        data[0]['info']['cookie'] = False
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(m, '_read_graph', lambda: data)
    assert m.enumerate_sources() == []


@pytest.mark.parametrize('value', [None, [], {}, {**ID, 'unknown': True}, {**ID, 'cookie': 42},
    {**ID, 'serial': 110}, {**ID, 'serial': '18446744073709551616'}, {**ID, 'cookie': '4294967296'},
    {**ID, 'serial': '-1'}, {**ID, 'serial': '01'}, {**ID, 'serial': '١'},
    {**ID, 'serial': '9' * 5000}, {**ID, 'name': ''}, {**ID, 'name': None},
    {**ID, 'name': 'bad\x00name'}, {**ID, 'name': 'vrct.managed.source'},
    {**ID, 'media_class': 'Audio/Sink'}])
def test_invalid_ipc_source_never_becomes_endpoint(value):
    with pytest.raises(ValueError, match='source_bridge_source_invalid'):
        module().parse_source(value)


def test_enumeration_errors_are_distinct_from_no_inputs(monkeypatch):
    m = module()
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    def unavailable():
        raise RuntimeError('source_bridge_graph_unavailable')
    monkeypatch.setattr(m, '_read_graph', unavailable)
    with pytest.raises(RuntimeError, match='graph_unavailable'):
        m.enumerate_sources()
    monkeypatch.setattr(m.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='linux_only'):
        m.enumerate_sources()


def test_stopped_generation_cannot_adopt_selection_or_start(system):  # noqa: F811
    m, b, bridge = system
    generation = bridge.health()['generation']
    bridge.stop()
    with pytest.raises(RuntimeError, match='stale_start'):
        bridge.start(source=m.Endpoint(42, 110, 'external.source', 'Audio/Source'),
                     expected_generation=generation)
    assert bridge.health()['source'] is None
    assert not bridge.health()['requested'] and not b.children


def test_explicit_selection_starts_and_active_selection_cannot_change(system):  # noqa: F811
    m, b, bridge = system
    bridge.start(source=m.Endpoint(42, 110, 'external.source', 'Audio/Source'), expected_generation=0)
    until(lambda: bridge.health()['active'])
    with pytest.raises(RuntimeError, match='already_running'):
        bridge.start(source=m.Endpoint(42, 120, 'another.source', 'Audio/Source'))
    assert bridge.health()['source'] == ID
    assert len(b.children) == 1


def test_stop_wins_while_selected_launch_is_pending(system):  # noqa: F811
    m, b, bridge = system
    b.block_at = 'launch'
    bridge.start(source=m.Endpoint(42, 110, 'external.source', 'Audio/Source'), expected_generation=0)
    assert b.enter.wait(1)
    generation = bridge.health()['generation']
    bridge.stop()
    with pytest.raises(RuntimeError, match='stale_start'):
        bridge.start(source=m.Endpoint(42, 120, 'another.source', 'Audio/Source'),
                     expected_generation=generation)
    assert bridge.health()['source'] == ID
    b.release.set()
    assert bridge.close()
    assert not bridge.health()['active'] and not b.unmutes
    assert all(child.poll() is not None for child in b.children)


def test_observations_order_concurrent_snapshots(system):  # noqa: F811
    m, b, bridge = system
    before = bridge.health()
    bridge.start(source=m.Endpoint(42, 110, 'external.source', 'Audio/Source'))
    until(lambda: bridge.health()['active'])
    active = bridge.health()
    bridge.stop()
    stopped = bridge.health()
    assert int(before['observation_id']) < int(active['observation_id']) < int(stopped['observation_id'])
    assert active['active'] and not stopped['active']
    samples = []
    threads = [Thread(target=lambda: samples.append(bridge.health())) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({v['observation_id'] for v in samples}) == 20
    assert all(int(v['observation_id']) > int(stopped['observation_id']) for v in samples)
