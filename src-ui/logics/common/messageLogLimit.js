// 画面に残す会話ログの件数。超えたら古いものからメモリーと画面から消す。
// 「会話ログを自動的に保存する」がオンなら、消えた分もファイルには残っている
export const MESSAGE_LOG_LIMIT = 1000;

export const keepRecentLogs = (rows, limit = MESSAGE_LOG_LIMIT) =>
    rows.length > limit ? rows.slice(rows.length - limit) : rows;
