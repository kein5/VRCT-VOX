import assert from "node:assert/strict";
import { test } from "node:test";
import { splitFeatureLabel } from "./featureLabel.js";

test("splits a feature name before its abbreviation", () => {
    assert.deepEqual(splitFeatureLabel("テキスト読み上げ（TTS）"), { name: "テキスト読み上げ", abbr: "（TTS）" });
    assert.deepEqual(splitFeatureLabel("ボイスチェンジャー（RVC）"), { name: "ボイスチェンジャー", abbr: "（RVC）" });
    assert.deepEqual(splitFeatureLabel("Text to speech (TTS)"), { name: "Text to speech", abbr: "(TTS)" });
    assert.deepEqual(splitFeatureLabel("Chat reading (OCR)"), { name: "Chat reading", abbr: "(OCR)" });
});

test("leaves a name without an abbreviation whole", () => {
    assert.deepEqual(splitFeatureLabel("翻訳"), { name: "翻訳", abbr: null });
    assert.deepEqual(splitFeatureLabel("Mic input"), { name: "Mic input", abbr: null });
    assert.deepEqual(splitFeatureLabel("（TTS）"), { name: "（TTS）", abbr: null });
    assert.deepEqual(splitFeatureLabel("(TTS)"), { name: "(TTS)", abbr: null });
    assert.deepEqual(splitFeatureLabel("A (b) c"), { name: "A (b) c", abbr: null });
    assert.deepEqual(splitFeatureLabel(""), { name: "", abbr: null });
});
