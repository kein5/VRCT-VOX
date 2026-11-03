// 会話ログの仮想スクロール (virtua) に渡す行。virtua は行の高さを並びの番号で覚えるので、
// 番号がずれる変更をそのまま渡すと、読んでいる位置がずれる。
// - 先頭の行が消えたこと (上限 MESSAGE_LOG_LIMIT) は件数の差で知る (shift)。1 回の更新で最古の行が
//   消えて最新の行が足されると件数が変わらないので、先頭が消えた分だけを先に見せ、残りは次の描画で見せる
// - 途中の行が消えたとき (捨てられた字幕) は、高さのない行 ({id, gone: true}) としてその場に残し、
//   先頭か末尾に来たら外す。virtua には、その行の高さが変わったようにしか見えない
export const nextLogView = (shown, rows) => {
    if (!rows.length) return { rows, shift: false };
    const dropped = shown.findIndex(row => row.id === rows[0].id);
    if (dropped > 0) return { rows: shown.slice(dropped), shift: true };
    const order = new Map(rows.map((row, index) => [row.id, index]));
    if (!shown.some(row => order.has(row.id))) return { rows, shift: false }; // 全部入れ替わった
    const next = [];
    let taken = 0;
    for (const row of shown) {
        const index = order.get(row.id);
        if (index === undefined) next.push(row.gone ? row : { id: row.id, gone: true });
        else if (index >= taken) {
            while (taken <= index) next.push(rows[taken++]);
        }
    }
    while (taken < rows.length) next.push(rows[taken++]);
    while (next.at(-1)?.gone) next.pop();
    return { rows: next.length === rows.length ? rows : next, shift: false };
};

// 選択の両端の行 ({from, to} は id) のあいだにある行の番号。virtua の keepMounted に渡す
export const rowsBetween = (rows, ends) => {
    if (!ends) return undefined;
    const indexOf = id => rows.findIndex(row => String(row.id) === id);
    const a = indexOf(ends.from), b = indexOf(ends.to);
    if (a < 0 || b < 0) return undefined;
    const start = Math.min(a, b);
    return Array.from({ length: Math.abs(a - b) + 1 }, (_, i) => start + i);
};
