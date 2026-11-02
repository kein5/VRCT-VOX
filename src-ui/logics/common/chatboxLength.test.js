import assert from "node:assert/strict";
import { test } from "node:test";
import { CHATBOX_MAX_LENGTH, chatboxOverflowLength } from "./chatboxLength.js";

test("only text longer than the chatbox limit is reported", () => {
    assert.equal(CHATBOX_MAX_LENGTH, 144);
    assert.equal(chatboxOverflowLength("あ".repeat(144)), null);
    assert.equal(chatboxOverflowLength("あ".repeat(145)), 145);
    assert.equal(chatboxOverflowLength(""), null);
    assert.equal(chatboxOverflowLength(undefined), null);
    assert.equal(chatboxOverflowLength("😀".repeat(73)), 146); // UTF-16 で数える
});
