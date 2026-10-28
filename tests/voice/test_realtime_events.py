"""Subtitle replacement and one final per known utterance, without a model."""
import importlib
from itertools import count

import pytest

IDS = count()
PREFIX = 'conversation.item.input_audio_transcription.'


def reducer(source='mic', namespace='session-a'):
    return importlib.import_module('models.transcription.realtime_events').TranscriptEvents(source, namespace)


def event(kind, item='u1', **values):
    name = PREFIX + kind if kind in ('delta', 'completed', 'failed') else 'input_audio_buffer.' + kind
    return {'type': name, 'event_id': f'e{next(IDS)}', 'item_id': item, **values}


def test_final_replaces_partial_and_never_reverts_or_repeats():
    r = reducer()
    r.accept(event('speech_started'))
    one = r.accept(event('delta', delta='仮の'))[0]
    two = r.accept(event('delta', delta='文'))[0]
    final = r.accept(event('completed', transcript='確定した文', stop='complete'))[0]
    assert [(u.text, u.revision, u.is_final) for u in (one, two, final)] == [
        ('仮の', 1, False), ('仮の文', 2, False), ('確定した文', 3, True)]
    assert final.state == 'final'
    assert r.accept(event('delta', delta='古い追記')) == ()
    assert r.accept(event('completed', transcript='重複', stop='complete')) == ()
    assert r.accept(event('committed')) == ()
    assert r.accept(event('completed', transcript='さらに重複', stop='complete')) == ()


def test_duplicate_event_id_does_not_append_partial_twice():
    r = reducer()
    r.accept(event('committed'))
    delta = event('delta', delta='一度')
    assert r.accept(delta)[0].text == '一度'
    assert r.accept(delta) == ()
    assert r.accept(event('completed', transcript='一度', stop='complete'))[0].revision == 2


@pytest.mark.parametrize('kind,values', [('failed', {'error': {'message':'private'}}),
    ('completed', {'transcript':'unfinished', 'stop':'model_limit'}),
    ('completed', {'transcript':'unfinished'})])
def test_failure_and_incomplete_result_discard_partial_without_final(kind, values):
    r = reducer()
    r.accept(event('committed'))
    r.accept(event('delta', delta='途中'))
    result = r.accept(event(kind, **values))
    assert len(result) == 1 and result[0].state == 'discarded'
    assert result[0].text == '' and not result[0].is_final
    assert r.accept(event('completed', transcript='late', stop='complete')) == ()


def test_clear_drops_inflight_and_waits_for_ack_before_new_items():
    r = reducer()
    r.accept(event('speech_started'))
    r.accept(event('delta', delta='消す'))
    assert r.begin_clear()[0].state == 'discarded'
    assert r.accept(event('completed', transcript='late', stop='complete')) == ()
    assert r.accept(event('committed', 'u2')) == ()
    assert r.accept(event('delta', 'u2', delta='古い')) == ()
    assert r.accept(event('cleared')) == ()
    assert r.accept(event('completed', 'u2', transcript='late', stop='complete')) == ()
    r.accept(event('speech_started', 'u3'))
    assert r.accept(event('completed', 'u3', transcript='新しい', stop='complete'))[0].text == '新しい'


def test_close_is_terminal_and_discards_visible_partial():
    r = reducer()
    r.accept(event('committed'))
    assert r.close()[0].state == 'discarded'
    assert r.closed
    assert r.accept(event('committed', 'later')) == ()
    assert r.accept(event('completed', transcript='late', stop='complete')) == ()
    assert r.close() == ()


def test_two_sources_and_reconnect_have_distinct_identity_for_same_item():
    results = []
    for source, ns in [('mic','a'), ('speaker','a'), ('mic','b')]:
        r = reducer(source, ns)
        r.accept(event('committed'))
        results.append(r.accept(event('completed', transcript='same', stop='complete'))[0])
    assert len({(u.source,u.namespace,u.item_id) for u in results}) == 3


@pytest.mark.parametrize('kind,values', [('delta',{'delta':'unknown'}),('completed',{'transcript':'unknown','stop':'complete'})])
def test_unknown_or_out_of_order_item_does_not_invent_a_final(kind, values):
    assert reducer().accept(event(kind, **values)) == ()


def test_pending_limit_closes_instead_of_growing_forever():
    r = reducer()
    for i in range(8):
        r.accept(event('committed', str(i)))
    with pytest.raises(ValueError, match='pending_limit'):
        r.accept(event('committed', 'ninth'))
    assert r.closed


@pytest.mark.parametrize('kind,values', [('delta',{'delta':'x'*4001}),('completed',{'transcript':'x'*4001,'stop':'complete'})])
def test_text_limit_closes_before_emitting_unbounded_update(kind, values):
    r = reducer()
    r.accept(event('committed'))
    with pytest.raises(ValueError, match='text_limit'):
        r.accept(event(kind, **values))
    assert r.closed


def test_evicted_terminal_id_cannot_be_completed_again_without_new_item():
    r = reducer()
    for i in range(600):
        r.accept(event('committed', str(i)))
        assert len(r.accept(event('completed', str(i), transcript='final', stop='complete'))) == 1
    assert r.accept(event('completed', '0', transcript='replay', stop='complete')) == ()


def test_empty_final_clears_partial_without_inventing_text():
    r = reducer()
    r.accept(event('committed'))
    r.accept(event('delta', delta='mistake'))
    result = r.accept(event('completed', transcript='', stop='complete'))[0]
    assert result.is_final and result.text == ''
