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


def speakers_of(rows, **values):
    r = reducer('speaker')
    r.accept(event('speech_started'))
    partial = r.accept(event('delta', delta='途中', speakers=rows))[0]
    final = r.accept(event('completed', transcript='確定', stop='complete', speakers=rows, **values))[0]
    assert partial.speakers == ()  # only a completed utterance names its speakers
    return final.speakers


def part(label, start, end):
    return {'speaker': label, 'start_ms': start, 'end_ms': end}


def test_a_final_names_who_spoke_in_the_order_they_first_speak():
    # Two voices in one utterance: the caption holds both, first speaker first.
    assert speakers_of([part('C', 24290, 28560), part('B', 26970, 28150)]) == ('C', 'B')
    # One voice in several parts is named once.
    assert speakers_of([part('A', 200, 1000), part('A', 1400, 3300)]) == ('A',)
    # A stray frame of another voice does not put a second speaker on the line...
    assert speakers_of([part('A', 0, 2000), part('B', 2000, 2100), part('B', 2200, 2300)]) == ('A',)
    # ...but when no one reaches that length, the longest still names the line.
    assert speakers_of([part('A', 0, 150), part('B', 150, 380)]) == ('B',)
    # At most four, those who spoke the most, still in order of speaking.
    crowd = [part(label, index * 1000, index * 1000 + 500 + index * 10) for index, label in enumerate('ABCDEF')]
    assert speakers_of(crowd) == ('C', 'D', 'E', 'F')
    # Labels go on past Z after a diarization restarts within a session.
    assert speakers_of([part('AB', 0.0, 900.5)]) == ('AB',)


@pytest.mark.parametrize('rows', [
    None, 'A', {'speaker': 'A'}, [], ['A'], [part('a', 0, 900)], [part('', 0, 900)], [part('ABCD', 0, 900)],
    [part('A', 900, 0)], [part('A', -1, 900)], [part('A', True, 900)], [part('A', '0', 900)],
    [{'speaker': 'A', 'start_ms': 0}], [part('A', 0, 900), 'B'], [part('A', 0, 900)] * 257,
])
def test_speakers_not_in_the_documented_form_leave_the_caption_without_speakers(rows):
    r = reducer('speaker')
    r.accept(event('speech_started'))
    values = {} if rows is None else {'speakers': rows}
    final = r.accept(event('completed', transcript='確定', stop='complete', **values))[0]
    assert final.is_final and final.text == '確定' and final.speakers == ()


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


def test_pending_ids_remain_during_partial_and_leave_after_terminal():
    r = reducer()
    r.accept(event('committed'))
    r.accept(event('delta', delta='pending'))
    assert r.pending_ids == ('u1',)
    r.accept(event('completed', transcript='done', stop='complete'))
    assert r.pending_ids == ()
