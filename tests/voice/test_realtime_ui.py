"""Execute the production caption reducer in Node; no duplicated Python model."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_caption_revisions_namespace_stop_and_legacy_rows():
    script = r"""
import assert from 'node:assert/strict';
import {applyRealtimeCaption, pruneRealtimeCaptions, mergeRealtimeState}
 from './src-ui/logics/transcription/realtimeCaptionState.js';
const active = {mic: {namespace:'m', generation:1, requested:true, state:'ready'},
 speaker: {namespace:'s', generation:1, requested:true, state:'ready'}};
const event = {source:'mic', namespace:'m', generation:1, item_id:'u', revision:1,
 state:'partial', text:'one', translations:[]};
const legacy = {id:'legacy', category:'sent', messages:{original:{message:'legacy'}}};
let state = {rows:[legacy], retired:[]};
state = applyRealtimeCaption(state, event, active);
assert.equal(state.rows.length, 2);
const id = state.rows[1].id, created = state.rows[1].created_at;
state = applyRealtimeCaption(state, {...event, revision:2, text:'two'}, active);
assert.equal(state.rows.length, 2);
assert.equal(state.rows[1].messages.original.message, 'two');
assert.equal(state.rows[1].id, id);
assert.equal(state.rows[1].created_at, created);
assert.equal(applyRealtimeCaption(state,event,active), state);
state = applyRealtimeCaption(state, {...event, revision:3, state:'final', text:'final'}, active);
state = applyRealtimeCaption(state, {...event, revision:4, state:'translated', text:'final',
 original:{message:'final',transliteration:[]}, translations:[{message:'訳文'}]}, active);
assert.equal(state.rows.length, 2);
assert.equal(state.rows[1].status, 'ok');
assert.equal(state.rows[1].messages.translations[0].message, '訳文');
assert.equal(applyRealtimeCaption(state,{...event,revision:99},active), state);
assert.equal(applyRealtimeCaption(state,{...event,revision:99,state:'final'},active), state);
assert.equal(applyRealtimeCaption(state,{...event,namespace:'old'},active), state);
assert.equal(applyRealtimeCaption(state,{...event,generation:0},active), state);
state = applyRealtimeCaption(state, {...event,source:'speaker',namespace:'s'}, active);
assert.equal(state.rows.length, 3);
assert.equal(state.rows[2].category,'received');
state = applyRealtimeCaption(state, {...event,item_id:'pending'}, active);
const stopped = {...active, mic:{...active.mic,generation:2,requested:false,state:'stopping'}};
state = pruneRealtimeCaptions(state,stopped);
assert.equal(state.rows.length, 3); // legacy + final mic + live speaker
assert.equal(state.rows[0],legacy);
assert.equal(applyRealtimeCaption(state,{...event,item_id:'late'},stopped), state);
assert.deepEqual(mergeRealtimeState(stopped,active),stopped); // stale poll cannot re-enable
const failed = {...active,mic:{...active.mic,state:'failed',requested:false}};
assert.deepEqual(mergeRealtimeState(failed,active),failed); // failure without a new generation
const starting = {...active,mic:{...active.mic,state:'starting',namespace:null}};
assert.deepEqual(mergeRealtimeState(active,starting),active); // ready cannot regress to starting
const next = {...stopped,mic:{...active.mic,namespace:'new',generation:3}};
state = applyRealtimeCaption(state,{...event,item_id:'discard',generation:3,namespace:'new'},next);
state = applyRealtimeCaption(state,{...event,item_id:'discard',generation:3,namespace:'new',revision:2,state:'discarded',text:''},next);
assert.equal(state.rows.length,3);
assert.equal(applyRealtimeCaption(state,{...event,item_id:'discard',generation:3,namespace:'new',revision:99},next),state);
assert.equal(applyRealtimeCaption(state,{...event,revision:NaN},active),state);
assert.equal(applyRealtimeCaption(state,{...event,source:'invalid'},active),state);
// Bounded terminal replay memory, independent of the existing user log limit.
for(let i=0;i<300;i++) state=applyRealtimeCaption(state,{...event,item_id:String(i),state:'discarded',text:''},active);
assert.ok(state.retired.length <= 256);
console.log('caption contracts passed');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
