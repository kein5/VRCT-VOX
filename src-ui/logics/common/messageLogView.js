// 会話ログの仮想スクロール (virtua) に渡す行。
// virtua は「先頭の行が消えた」ことを件数の差で知り (shift)、読んでいる位置を保つ。
// 上限 (MESSAGE_LOG_LIMIT) では 1 回の更新で最古の行が消えて最新の行が足されるので、件数が変わらず
// 位置がずれる。先頭が消えた分だけを先に見せ、残りの変更は次の描画で見せる
export const nextLogView = (shown, rows) => {
    const dropped = rows.length ? shown.findIndex(row => row.id === rows[0].id) : -1;
    return dropped > 0
        ? { rows: shown.slice(dropped), shift: true }
        : { rows, shift: false };
};
