import test from "node:test";
import assert from "node:assert/strict";
import { splitDescription } from "./descriptionSplit.js";

test("the first sentence stays visible and a long rest folds", () => {
    assert.deepEqual(splitDescription("読み上げます。保存してから、メイン画面でTTSをオンにします。サーバーも起動します。"),
        ["読み上げます。", "保存してから、メイン画面でTTSをオンにします。サーバーも起動します。"]);
    assert.deepEqual(splitDescription("Reads messages aloud. Turn TTS on from the main screen after saving it."),
        ["Reads messages aloud.", "Turn TTS on from the main screen after saving it."]);
});

test("short or single-sentence text is shown whole", () => {
    assert.deepEqual(splitDescription("一文だけの説明です。"), ["一文だけの説明です。", ""]);
    assert.deepEqual(splitDescription("Short. Tail."), ["Short. Tail.", ""]);
    assert.deepEqual(splitDescription("Version 1.2 is out"), ["Version 1.2 is out", ""]);
    assert.deepEqual(splitDescription(undefined), ["", ""]);
});
