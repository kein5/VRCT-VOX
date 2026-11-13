import { test } from "node:test";
import assert from "node:assert/strict";
import { FADE_MS, MAX_CAPTION_LINES, captionLines, nextChange, stampLines, visibleLines } from "./lines.js";

const row = (id, category, message, translations = [], status = "ok") => ({
    id, category, status, messages: { original: { message, transliteration: [] },
        translations: translations.map(text => ({ message: text, transliteration: [] })) },
});

test("captions are the last sent and received rows, oldest first", () => {
    const rows = [
        row(1, "sent", "一つ目"), row(2, "system", "設定を保存しました"), row(3, "received", "Hello", ["こんにちは"]),
        row("realtime:mic:1:s:a", "sent", "いま話して", [], "pending"),
    ];
    assert.deepEqual(captionLines(rows), [
        { id: "1", kind: "sent", text: "一つ目", translations: [], pending: false },
        { id: "3", kind: "received", text: "Hello", translations: ["こんにちは"], pending: false },
        { id: "realtime:mic:1:s:a", kind: "sent", text: "いま話して", translations: [], pending: true },
    ]);
    const many = Array.from({ length: 10 }, (_, index) => row(index, "received", `line ${index}`));
    assert.deepEqual(captionLines(many).map(line => line.id), ["6", "7", "8", "9"]);
    assert.equal(captionLines(many).length, MAX_CAPTION_LINES);
    assert.deepEqual(captionLines([]), []);
});

test("only the translation is shown when asked, and the original until one exists", () => {
    const rows = [row(1, "sent", "こんにちは", ["Hello", "안녕하세요"]), row(2, "sent", "まだ訳がない")];
    assert.deepEqual(captionLines(rows, { onlyTranslated: true }).map(line => [line.text, line.translations]),
        [["", ["Hello", "안녕하세요"]], ["まだ訳がない", []]]);
    // A row with no words at all is not a caption.
    assert.deepEqual(captionLines([row(3, "received", "")]), []);
});

test("a heard line names its speakers; the user's own line and malformed labels name none", () => {
    const heard = { ...row("realtime:speaker:1:s:a", "received", "こんばんは。こんばんは。"), speakers: ["A", "B"] };
    const own = { ...row(2, "sent", "やあ"), speakers: ["A"] };
    const odd = { ...row(3, "received", "Hello"), speakers: ["a", "B"] };
    assert.deepEqual(captionLines([heard, own, odd]), [
        { id: "realtime:speaker:1:s:a", kind: "received", text: "こんばんは。こんばんは。", translations: [], pending: false, speakers: ["A", "B"] },
        { id: "2", kind: "sent", text: "やあ", translations: [], pending: false },
        { id: "3", kind: "received", text: "Hello", translations: [], pending: false },
    ]);
});

test("long text is cut by characters, and at most three translations are kept", () => {
    const [line] = captionLines([row(1, "sent", "あ".repeat(2500), ["a", "b", "c", "d"])]);
    assert.equal([...line.text].length, 2000);
    assert.deepEqual(line.translations, ["a", "b", "c"]);
});

test("the log's history is not shown when the overlay is turned on; new and changed lines get their time", () => {
    const first = captionLines([row(1, "sent", "前からあった行")]);
    const baseline = stampLines(null, first, 1000, 6000);
    assert.equal(baseline.get("1").until, 0);

    const second = captionLines([row(1, "sent", "前からあった行"), row(2, "received", "新しい行")]);
    const stamped = stampLines(baseline, second, 5000, 6000);
    assert.equal(stamped.get("1").until, 0);
    assert.equal(stamped.get("2").until, 11000);

    // The same words keep their time; rewritten words (a caption still being recognized) start again.
    const unchanged = stampLines(stamped, second, 8000, 6000);
    assert.equal(unchanged.get("2").until, 11000);
    const rewritten = captionLines([row(2, "received", "新しい行が伸びた")]);
    const again = stampLines(unchanged, rewritten, 9000, 6000);
    assert.equal(again.get("2").until, 15000);
    assert.equal(again.has("1"), false);
});

test("a line fades just before its time and is gone after it", () => {
    const lines = [{ id: "a", until: 10000 }, { id: "b", until: 0 }, { id: "c", until: 20000 }];
    assert.deepEqual(visibleLines(lines, 5000).map(line => [line.id, line.fading]), [["a", false], ["c", false]]);
    assert.deepEqual(visibleLines(lines, 10000 - FADE_MS).map(line => [line.id, line.fading]), [["a", true], ["c", false]]);
    assert.deepEqual(visibleLines(lines, 10000).map(line => line.id), ["c"]);
    assert.equal(nextChange(lines, 5000), 10000 - FADE_MS);
    assert.equal(nextChange(lines, 10000 - FADE_MS), 10000);
    assert.equal(nextChange(lines, 10000), 20000 - FADE_MS);
    assert.equal(nextChange(lines, 20000), null);
});
