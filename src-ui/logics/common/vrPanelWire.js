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

// VR画面がメイン経由でバックエンドへ頼める操作の範囲。VR画面はローカルの資産だけを読むが、
// アプリの終了・更新・ファイルを開く・モデルのダウンロード・認証キーの変更は VR からは頼めない。
// 接続先 (URL、ホスト、ポート) と、実行するプログラムを含む音声の設定も頼めない。接続先の変更では、
// 保存したキーを新しい接続先へ送って確かめるため、VR画面を乗っ取ればキーを外へ送らせられる
const BLOCKED_RELAY_PATHS = ["/run/shutdown", "/run/update_software", "/run/open_filepath_logs", "/run/open_filepath_config_file",
    "/set/data/websocket_host", "/set/data/websocket_port", "/set/data/obs_browser_source_port",
    "/set/data/osc_ip_address", "/set/data/osc_port",
    "/set/data/voice_settings", "/set/data/direct_voice_settings", "/set/data/speech_server_settings", "/set/data/realtime_asr_settings"];
export const isRelayAllowed = (path) => typeof path === "string"
    && /^\/(get|set|run)\//.test(path)
    && !BLOCKED_RELAY_PATHS.includes(path)
    && !path.startsWith("/run/download_")
    && !path.includes("model_download")
    && !/auth_key|auth_token/.test(path)
    && !/^\/set\/data\/[a-z_]*_url$/.test(path);

// VR画面へ写さない atom。VR画面は認証キーとトークンを表示しない。写すと、VR画面や、
// 同じイベントを聞けるほかのウィンドウからキーを読めてしまう
export const isSecretAtomName = (name) => /Auth(Key|Token)$/.test(name);
