import assert from "node:assert/strict";
import { test } from "node:test";
import { setupNeeds, downloadProgress } from "./setupNeeds.js";

const weights = downloaded => [{ id: "small", is_downloaded: downloaded }, { id: "large", is_downloaded: false }];
const selection = values => ({ translationEngine: "CTranslate2", translationWeights: weights(false), translationWeight: "small",
    transcriptionEngine: "Whisper", whisperWeights: weights(false), whisperWeight: "small", ...values });

test("a selected built-in engine without its selected model is a need", () => {
    assert.deepEqual(setupNeeds(selection()).map(need => [need.id, need.weight.id]),
        [["translation", "small"], ["transcription", "small"]]);
});

test("a model that is there, or an engine that needs none, is not a need", () => {
    assert.deepEqual(setupNeeds(selection({ translationWeights: weights(true) })).map(need => need.id), ["transcription"]);
    assert.deepEqual(setupNeeds(selection({ translationEngine: "Google", transcriptionEngine: "Google" })), []);
    // Nothing has been chosen yet: the first press of the microphone asks which engine to use.
    assert.deepEqual(setupNeeds(selection({ translationEngine: "DeepL", transcriptionEngine: null })), []);
});

test("an unselected model that is missing is not a need, and unknown lists ask for nothing", () => {
    assert.deepEqual(setupNeeds(selection({ translationWeights: [{ id: "small", is_downloaded: true }, { id: "large", is_downloaded: false }],
        whisperWeights: undefined })), []);
    assert.deepEqual(setupNeeds(selection({ translationWeight: "gone", whisperWeight: undefined })), []);
});

test("progress is a whole percentage, a wait before the first report, or nothing", () => {
    assert.equal(downloadProgress({ is_pending: true, progress: null }), "pending");
    assert.equal(downloadProgress({ is_pending: true, progress: 41.7 }), 41);
    assert.equal(downloadProgress({ is_pending: true, progress: 100.4 }), 100);
    assert.equal(downloadProgress({ is_pending: false, progress: null }), null);
    assert.equal(downloadProgress(undefined), null);
});
