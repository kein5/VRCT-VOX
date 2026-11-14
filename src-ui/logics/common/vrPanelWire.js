// VRパネルとメインの間の emit は、Rust (serde_json::Value) を通るときにオブジェクトのキーを辞書順に並び替える。
// 一覧の並び ({名前: 名前} のフォント・デバイスなど、挿入順に意味があるもの) を保つため、
// オブジェクトを [キー, 値] の組の並びに包んで送り、受け取る側で挿入順どおりに戻す。
const MARK = "__vr_entries__";

export const encodeOrdered = (value) => {
    if (Array.isArray(value)) return value.map(encodeOrdered);
    if (value && typeof value === "object") {
        return { [MARK]: Object.entries(value).map(([key, v]) => [key, encodeOrdered(v)]) };
    }
    return value;
};

export const decodeOrdered = (value) => {
    if (Array.isArray(value)) return value.map(decodeOrdered);
    if (value && typeof value === "object") {
        const entries = value[MARK];
        if (!Array.isArray(entries)) return value;
        return Object.fromEntries(entries.map(([key, v]) => [key, decodeOrdered(v)]));
    }
    return value;
};

// 会話ログは千件まで育ち、文字起こしの途中経過が届くたびに変わる。毎回全件を送ると重いので、前に送った行との差分だけを送る。
// 行は変えるときに作り直すので、同じオブジェクトなら変わっていない。前の行の先頭から drop 行を捨て、続く keep 行を
// そのまま使い、残りを rows にする。前の行から続かないときは null (全件を送る)
export const diffLogRows = (previous, next) => {
    const drop = next.length > 0 ? previous.indexOf(next[0]) : previous.length;
    if (drop < 0) return null;
    let keep = 0;
    while (keep < next.length && drop + keep < previous.length && previous[drop + keep] === next[keep]) keep += 1;
    return { drop, keep, rows: next.slice(keep) };
};

const LOG_MARK = "__vr_log__";

// sent は前に送った {seq, rows}。full のとき、または差分が取れないときは base を null にして全件を送る
export const encodeLogUpdate = (sent, value, full = false) => {
    const patch = !full && sent?.rows ? diffLogRows(sent.rows, value.data) : null;
    const seq = (sent?.seq ?? 0) + 1;
    const message = { [LOG_MARK]: { seq, base: patch ? sent.seq : null, state: value.state,
        drop: patch?.drop ?? 0, keep: patch?.keep ?? 0, rows: encodeOrdered(patch ? patch.rows : value.data) } };
    return { sent: { seq, rows: value.data }, message };
};

export const isLogUpdate = (encoded) => Boolean(encoded && typeof encoded === "object" && encoded[LOG_MARK]);

// received は前に受け取った {seq, rows, state}。差分の元が受け取ったものと違えば null (全件を頼み直す)
export const decodeLogUpdate = (received, encoded) => {
    const { seq, base, state, drop, keep, rows } = encoded[LOG_MARK];
    const decoded = decodeOrdered(rows);
    if (base === null) return { seq, rows: decoded, state };
    if (received?.seq !== base) return null;
    return { seq, rows: received.rows.slice(drop, drop + keep).concat(decoded), state };
};

// VR画面がメイン経由でバックエンドへ頼める操作の範囲。VR画面はローカルの資産だけを読むが、
// アプリの終了・更新・ファイルを開く・モデルのダウンロード・認証キーの変更は VR からは頼めない。
// 接続先 (URL、ホスト、ポート) と、実行するプログラムを含む音声の設定も頼めない。接続先の変更では、
// 保存したキーを新しい接続先へ送って確かめるため、VR画面を乗っ取ればキーを外へ送らせられる
const BLOCKED_RELAY_PATHS = ["/run/shutdown", "/run/update_software", "/run/open_filepath_logs", "/run/open_filepath_config_file",
    "/set/data/websocket_host", "/set/data/websocket_port", "/set/data/websocket_tls", "/set/data/obs_browser_source_port",
    "/set/data/osc_ip_address", "/set/data/osc_port",
    "/set/data/voice_settings", "/set/data/direct_voice_settings", "/set/data/speech_server_settings", "/set/data/realtime_asr_settings"];
export const isRelayAllowed = (path) => typeof path === "string"
    && /^\/(get|set|run)\//.test(path)
    && !BLOCKED_RELAY_PATHS.includes(path)
    && !path.startsWith("/run/download_")
    && !path.startsWith("/run/update_") // update_software と update_cuda_software (インストーラーを起動して終了する)
    && !path.includes("model_download")
    && !path.includes("vc_runtime")
    && !/auth_key|auth_token|restore_token/.test(path)
    && !/^\/set\/data\/[a-z_]*_url$/.test(path);

// VR画面へ写さない atom。VR画面は認証キーとトークンを表示しない。写すと、VR画面や、
// 同じイベントを聞けるほかのウィンドウからキーを読めてしまう。ウィンドウ共有を確認なしで
// 再開するトークン (RestoreToken) も、VR画面では使わないので写さない
export const isSecretAtomName = (name) => /(Auth(Key|Token)|RestoreToken)$/.test(name);
