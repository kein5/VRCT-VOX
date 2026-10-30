"""A repaired final snapshot must not erase an unsafe intermediate route."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.voice_route_watch import RouteHistory, JSONArrays
import json
import subprocess
import io
from threading import Event, Lock
from types import SimpleNamespace
from tools.voice_route_watch import RouteWatch

MONITORS = []


@pytest.fixture(autouse=True)
def cleanup_monitors():
    yield
    while MONITORS:
        MONITORS.pop().close()


def node(id, name, kind, pid=None):
    props = {'node.name': name, 'media.class': kind, 'object.serial': id + 100}
    if pid is not None:
        props.update({'application.name': 'VRChat.exe', 'application.process.id': pid})
    return {'id': id, 'type': 'PipeWire:Interface:Node', 'info': {'props': props}}


def link(id, source, target):
    return {'id': id, 'type': 'PipeWire:Interface:Link', 'info': {
        'output-node-id': source, 'input-node-id': target, 'state': 'active'}}


def baseline():
    return [
        {'id': 0, 'type': 'PipeWire:Interface:Core', 'info': {'cookie': 1000}},
        node(1, 'managed', 'Audio/Source'), node(2, 'replay', 'Audio/Sink'),
        node(3, 'physical', 'Audio/Source'),
        node(4, 'VRChat.exe', 'Stream/Input/Audio', 77),
        node(5, 'VRChat.exe', 'Stream/Output/Audio', 77),
        link(10, 1, 4), link(11, 5, 2),
    ]


def history():
    h = RouteHistory('managed', 'replay', 77)
    h.observe(baseline())
    assert h.check()['valid']
    return h


def test_temporary_physical_fallback_stays_failed_after_restoration():
    h = history()
    h.observe([{'id': 10, 'info': {'output-node-id': 3}}])
    h.observe([{'id': 10, 'info': {'output-node-id': 1}}])
    with pytest.raises(RuntimeError, match='microphone_route'):
        h.check()


def test_same_batch_restoration_cannot_clear_a_bad_event():
    h = history()
    h.observe([{'id': 10, 'info': {'output-node-id': 3}},
               {'id': 10, 'info': {'output-node-id': 1}}])
    with pytest.raises(RuntimeError, match='microphone_route'):
        h.check()


@pytest.mark.parametrize('events', [
    [{'id': 10, 'info': None}],
    [{'id': 10, 'info': {'state': 'paused'}}],
    [node(1, 'managed', 'Audio/Source') | {'info': {'props': {'node.name': 'managed', 'media.class': 'Audio/Source', 'object.serial': 999}}}],
    [{'id': 0, 'info': {'cookie': 1001}}],
    [node(4, 'VRChat.exe', 'Stream/Input/Audio', 88)],
    [node(6, 'physical-leak', 'Stream/Output/Audio'), link(12, 6, 2)],
])
def test_missing_replaced_foreign_or_inactive_routes_fail(events):
    h = history()
    h.observe(events)
    with pytest.raises(RuntimeError):
        h.check()


def test_unrelated_updates_do_not_replace_the_known_graph():
    h = history()
    h.observe([node(99, 'other', 'Audio/Sink')])
    h.observe([{'id': 4, 'info': {'state': 'running'}}])
    assert h.check()['batches'] == 3


def test_idle_game_playback_can_pause_and_close_without_losing_microphone():
    h = history()
    h.observe([{'id': 5, 'info': {'state': 'idle'}},
               {'id': 11, 'info': {'state': 'paused'}}])
    h.observe([{'id': 11, 'info': None}])
    h.observe([{'id': 5, 'info': None}])
    assert h.check()['valid']


def test_idle_output_still_cannot_connect_to_a_wrong_sink():
    h = history()
    h.observe([{'id': 5, 'info': {'state': 'idle'}},
               {'id': 11, 'info': {'state': 'paused', 'input-node-id': 99}}])
    with pytest.raises(RuntimeError, match='playback_route'):
        h.check()


def test_running_output_cannot_lose_its_link():
    h = history()
    h.observe([{'id': 5, 'info': {'state': 'running'}}, {'id': 11, 'info': None}])
    with pytest.raises(RuntimeError, match='playback_route'):
        h.check()


def test_new_playback_link_can_negotiate_with_the_correct_sink():
    h = history()
    for state in ('init', 'negotiating', 'allocating', 'paused', 'active'):
        h.observe([{'id': 11, 'info': {'state': state}}])
    assert h.check()['valid']


@pytest.mark.parametrize('reverse', [False, True])
def test_one_batch_can_create_a_running_output_and_its_link_in_either_order(reverse):
    h = history()
    output = node(6, 'VRChat.exe', 'Stream/Output/Audio', 77)
    output['info']['state'] = 'running'
    changes = [output, link(12, 6, 2)]
    h.observe(list(reversed(changes)) if reverse else changes)
    assert h.check()['valid']


def test_new_output_wrong_target_then_restoration_in_same_batch_stays_failed():
    h = history()
    h.observe([node(6, 'VRChat.exe', 'Stream/Output/Audio', 77),
               link(12, 6, 3), {'id': 12, 'info': {'input-node-id': 2}}])
    with pytest.raises(RuntimeError, match='playback_route'):
        h.check()


@pytest.mark.parametrize('state', ['error', 'unknown'])
def test_broken_playback_links_are_not_normal_lifecycle(state):
    h = history()
    h.observe([{'id': 11, 'info': {'state': state}}])
    with pytest.raises(RuntimeError, match='playback_route'):
        h.check()


def test_monitor_eof_is_failure_even_with_a_valid_last_graph():
    h = history()
    h.fail('monitor_ended')
    with pytest.raises(RuntimeError, match='monitor_ended'):
        h.check()


def test_stream_parser_preserves_partial_and_consecutive_arrays():
    parser = JSONArrays()
    assert parser.feed('[{"id":') == []
    assert parser.feed('1}]\n[{"id":2}]\n') == [[{'id': 1}], [{'id': 2}]]
    parser.finish()


def test_incomplete_or_non_array_monitor_stream_is_rejected():
    parser = JSONArrays()
    parser.feed('[{"id":')
    with pytest.raises(ValueError):
        parser.finish()
    with pytest.raises(ValueError):
        JSONArrays().feed('{}')


def monitor_process(monkeypatch, tmp_path, final=b'', exit_code=0):
    """Real pipe/thread/EOF behavior without touching PipeWire or audio."""
    popen = subprocess.Popen
    code = f'''
import os, signal, time
def stop(*args):
    os.write(1, {final!r})
    raise SystemExit({exit_code})
signal.signal(signal.SIGTERM, stop)
print({json.dumps(baseline())!r}, flush=True)
while True: time.sleep(.05)
'''
    monkeypatch.setattr(subprocess, 'Popen', lambda command, **kwargs:
                        popen([sys.executable, '-u', '-c', code], **kwargs))
    watch = RouteWatch('managed', 'replay', 77, tmp_path / 'events.jsonl')
    MONITORS.append(watch)
    return watch


@pytest.mark.skipif(sys.platform == 'win32', reason='Final monitor output is emitted by a POSIX SIGTERM handler')
def test_finish_drains_normal_monitor_and_returns_final_evidence(monkeypatch, tmp_path):
    watch = monitor_process(monkeypatch, tmp_path)
    assert watch.check()['valid']
    result = watch.finish()
    assert result['valid'] and result['scope'] == 'received_pipewire_changes'
    assert watch.process.poll() is not None and not watch.thread.is_alive()


@pytest.mark.parametrize('final, reason', [
    (b'[{"id":10,"info":{"output-node-id":3}}]', 'microphone_route'),
    (b'[{"id":', 'incomplete_document'),
    (b'\xff', 'decode'),
])
@pytest.mark.skipif(sys.platform == 'win32', reason='Final monitor output is emitted by a POSIX SIGTERM handler')
def test_finish_rejects_bad_output_arriving_after_last_check(monkeypatch, tmp_path, final, reason):
    watch = monitor_process(monkeypatch, tmp_path, final)
    assert watch.check()['valid']
    with pytest.raises(RuntimeError, match=reason):
        watch.finish()
    assert watch.process.poll() is not None and not watch.thread.is_alive()


def test_finish_rejects_process_failure_racing_with_stop(monkeypatch, tmp_path):
    watch = monitor_process(monkeypatch, tmp_path, exit_code=1)
    assert watch.check()['valid']
    with pytest.raises(RuntimeError, match='monitor_exit'):
        watch.finish()


def test_real_unexpected_eof_is_not_silence_or_normal_cleanup(monkeypatch, tmp_path):
    watch = monitor_process(monkeypatch, tmp_path)
    watch.process.kill()
    watch.process.wait(timeout=3)
    watch.thread.join(3)
    with pytest.raises(RuntimeError, match='monitor_ended'):
        watch.finish()


def test_natural_zero_exit_between_checks_is_not_requested_shutdown():
    watch = RouteWatch.__new__(RouteWatch)
    watch.history = history()
    watch.lock, watch.ready, watch.stopping = Lock(), Event(), Event()
    watch.log, watch.stderr = io.StringIO(), io.StringIO()
    polls = iter([None, None, 0])
    calls = []
    watch.process = SimpleNamespace(poll=lambda:next(polls,0), returncode=0,
                                    stdout=io.BytesIO(), terminate=lambda:calls.append('terminate'),
                                    wait=lambda **kwargs:0)
    alive = [True]
    def join(timeout):
        watch._read()
        alive[0] = False
    watch.thread = SimpleNamespace(is_alive=lambda:alive[0], join=join)
    with pytest.raises(RuntimeError, match='monitor_ended'):
        watch.finish()
    assert calls == []
