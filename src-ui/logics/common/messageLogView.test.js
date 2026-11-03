import assert from "node:assert/strict";
import { test } from "node:test";
import { nextLogView } from "./messageLogView.js";

const rows = (...ids) => ids.map(id => ({ id }));
const ids = view => view.rows.map(row => row.id);

test("at the cap the dropped rows are shown first, then the rest", () => {
    const shown = rows(1, 2, 3);
    const next = rows(2, 3, 4); // 最古の 1 が消えて 4 が足された (件数は同じ)
    const first = nextLogView(shown, next);
    assert.deepEqual([ids(first), first.shift], [[2, 3], true]);
    assert.equal(first.rows[0], shown[1]); // まだ表示中の行のまま
    const second = nextLogView(first.rows, next);
    assert.deepEqual([second.rows, second.shift], [next, false]);
});

test("changes that keep the first row go straight through", () => {
    const shown = rows(1, 2);
    for (const next of [rows(1, 2, 3), [shown[0], { id: 2, status: "ok" }], rows(1), shown]) {
        const view = nextLogView(shown, next);
        assert.equal(view.rows, next);
        assert.equal(view.shift, false);
    }
});

test("clearing the log or replacing every row is not a shift", () => {
    assert.deepEqual(nextLogView(rows(1, 2), []), { rows: [], shift: false });
    const replaced = rows(8, 9);
    assert.deepEqual(nextLogView(rows(1, 2), replaced), { rows: replaced, shift: false });
    assert.deepEqual(nextLogView([], rows(1)), { rows: rows(1), shift: false });
});

test("a retired caption at the top counts as a drop from the start", () => {
    const view = nextLogView(rows("caption", 1, 2), rows(1, 2));
    assert.deepEqual([ids(view), view.shift], [[1, 2], true]);
});
