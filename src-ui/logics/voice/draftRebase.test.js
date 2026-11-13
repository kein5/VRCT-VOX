import assert from "node:assert/strict";
import { test } from "node:test";
import { rebaseDraft } from "./draftRebase.js";

const profile = { model: "", vad_model: "", voice_file: "", device: "auto", low_latency: false };
const saved = { version: 1, profiles: { japanese: { ...profile }, asr: { ...profile } } };
const applied = { version: 1, profiles: { ...saved.profiles, asr: { ...profile, model: "/downloads/haas.gguf" } } };

test("an applied model path reaches an unedited field while other edits stay unsaved", () => {
    const draft = { version: 1, profiles: { japanese: { ...profile, device: "gpu" }, asr: { ...profile, vad_model: "/vad.gguf" } } };
    assert.deepEqual(rebaseDraft(saved, draft, applied), { version: 1, profiles: {
        japanese: { ...profile, device: "gpu" }, asr: { ...profile, model: "/downloads/haas.gguf", vad_model: "/vad.gguf" } } });
});
test("a clean draft becomes the new saved value", () => {
    assert.equal(rebaseDraft(saved, structuredClone(saved), applied), applied);
});
test("an edited field keeps the user's value over a newer saved value", () => {
    const draft = { ...saved, profiles: { ...saved.profiles, asr: { ...profile, model: "/typed.gguf" } } };
    assert.equal(rebaseDraft(saved, draft, applied).profiles.asr.model, "/typed.gguf");
});
test("key order follows the saved value so dirty checks stay stable", () => {
    const rebased = rebaseDraft({ a: 1, b: 2 }, { b: 3, a: 1 }, { a: 4, b: 2 });
    assert.equal(JSON.stringify(rebased), JSON.stringify({ a: 4, b: 3 }));
});
