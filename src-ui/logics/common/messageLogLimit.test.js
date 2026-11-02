import assert from "node:assert/strict";
import { test } from "node:test";
import { MESSAGE_LOG_LIMIT, keepRecentLogs } from "./messageLogLimit.js";

test("the log keeps only the most recent rows", () => {
    const rows = Array.from({ length: MESSAGE_LOG_LIMIT + 5 }, (_, index) => ({ id: index }));
    const kept = keepRecentLogs(rows);
    assert.equal(kept.length, MESSAGE_LOG_LIMIT);
    assert.equal(kept[0].id, 5);
    assert.equal(kept.at(-1).id, MESSAGE_LOG_LIMIT + 4);
    const short = rows.slice(0, 3);
    assert.equal(keepRecentLogs(short), short); // 上限より少なければ同じ配列のまま (VRパネルへの差分が空になる)
});
