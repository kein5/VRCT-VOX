import assert from "node:assert/strict";
import { test } from "node:test";
import { nextLogView, rowsBetween } from "./messageLogView.js";

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

test("a row removed in the middle stays as an empty row until it reaches an end", () => {
    const shown = rows("a", "caption", "b", "c");
    const removed = nextLogView(shown, rows("a", "b", "c"));
    assert.deepEqual([removed.rows.map(row => row.gone ? `(${row.id})` : row.id), removed.shift], [["a", "(caption)", "b", "c"], false]);
    const appended = nextLogView(removed.rows, [...rows("a", "b", "c"), { id: "d" }]);
    assert.deepEqual(appended.rows.map(row => row.gone ? `(${row.id})` : row.id), ["a", "(caption)", "b", "c", "d"]);
    assert.equal(appended.rows[1], removed.rows[1]); // 同じ空の行を使い続ける
    // 先頭の行が消えると、その後ろの空の行も一緒に先頭から外れる (shift)
    const capped = nextLogView(appended.rows, rows("b", "c", "d"));
    assert.deepEqual([capped.rows.map(row => row.id), capped.shift], [["b", "c", "d"], true]);
    // 末尾の空の行は外す
    assert.deepEqual(nextLogView(rows("a", "b", "caption"), rows("a", "b")).rows.map(row => row.id), ["a", "b"]);
    assert.deepEqual(nextLogView(rows("a", "x", "b", "y"), rows("a", "b")).rows.map(row => row.gone ? `(${row.id})` : row.id), ["a", "(x)", "b"]);
});

test("while following, removed rows go at once and earlier empty rows leave too", () => {
    const shown = [{ id: "a" }, { id: "old", gone: true }, { id: "caption" }, { id: "b" }];
    const rows2 = rows("a", "b");
    assert.deepEqual(nextLogView(shown, rows2, false), { rows: rows2, shift: false });
    // 先頭が消えるときは追っていても shift のまま
    assert.equal(nextLogView(shown, rows("b"), false).shift, true);
});

test("empty rows are capped even while reading", () => {
    let shown = rows("a"), live = rows("a");
    for (let i = 0; i < 150; i++) {
        live = [live[0], { id: `c${i}` }];                // 新しい字幕が来てから、前の字幕が捨てられる
        shown = nextLogView(shown, [live[0], ...(i ? [{ id: `c${i - 1}` }] : []), live[1]]).rows;
        shown = nextLogView(shown, live).rows;
        assert.ok(shown.filter(row => row.gone).length <= 100);
    }
    assert.deepEqual(shown.filter(row => !row.gone).map(row => row.id), ["a", "c149"]);
});

test("a selection keeps the rows between its ends mounted, in either direction", () => {
    const shown = rows("a", "b", "c", "d");
    assert.deepEqual(rowsBetween(shown, { from: "d", to: "b" }), [1, 2, 3]);
    assert.deepEqual(rowsBetween(shown, { from: "a", to: "a" }), [0]);
    assert.equal(rowsBetween(shown, null), undefined);
    assert.equal(rowsBetween(shown, { from: "gone", to: "b" }), undefined); // 選択した行が上限で消えた
    assert.deepEqual(rowsBetween(rows(1, 2), { from: "2", to: "1" }), [0, 1]); // DOM の属性は文字列
});
