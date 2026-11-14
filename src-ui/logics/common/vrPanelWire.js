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

// VR画面がメイン経由でバックエンドへ頼める操作の一覧 (SEC-02)。載っていない操作は中継しない。
// 新しいエンドポイントも、ここに足すまでは VR からは頼めない。VR画面が実際に送るもの
// (ランチャー、ログの操作バー、言語、VRの設定ウィンドウ) だけを載せる。
// 認証キー・トークン、接続先 (URL・ホスト・ポート・証明書)、モデルや実行環境の取得、
// 音声の設定、テレメトリの同意、ファイルを開く操作、終了・更新は載せない。
// バックエンドも同じ一覧で、VR から来た要求を確かめる (src-python/models/vr_panel_policy.py。
// 2つの一覧が同じことはテストで確かめる)
const toggle = name => [`/set/enable/${name}`, `/set/disable/${name}`];
export const VR_PANEL_RELAY_PATHS = new Set([
    // The panel itself: its windows, the log's bar, layout and tooltips.
    "/run/vr_panel_windows", "/run/vr_panel_recall_log", "/run/vr_panel_layout_rendered", "/run/vr_panel_tooltip",
    "/set/data/overlay_vr_panel_anchor", ...toggle("overlay_vr_panel_locked"),
    "/set/data/overlay_vr_panel_opacity", "/set/data/overlay_vr_panel_font_size",
    // The launcher's switches.
    ...toggle("translation"), ...toggle("transcription_send"), ...toggle("transcription_receive"), ...toggle("ocr_capture"),
    // The language window.
    "/set/data/selected_tab_no", "/set/data/selected_your_languages", "/set/data/selected_target_languages",
    "/set/data/selected_translation_engines", "/run/swap_your_language_and_target_language",
    "/get/data/selected_tab_no", "/get/data/selected_your_languages", "/get/data/selected_target_languages",
    "/get/data/selected_translation_engines", "/get/data/selectable_translation_engines",
    // The VR settings window: devices and their meters.
    "/set/data/selected_mic_host", "/set/data/selected_mic_device_id", "/set/data/selected_speaker_device_id",
    "/set/data/mic_threshold", "/set/data/speaker_threshold",
    ...toggle("mic_automatic_threshold"), ...toggle("speaker_automatic_threshold"),
    ...toggle("auto_mic_select"), ...toggle("auto_speaker_select"),
    ...toggle("check_mic_threshold"), ...toggle("check_speaker_threshold"),
    // Translation, speech recognition and chat reading.
    "/set/data/selected_ctranslate2_weight_type", "/set/data/selected_translation_compute_device",
    "/set/data/selected_translation_compute_type",
    "/set/data/selected_transcription_engine", "/set/data/selected_whisper_weight_type",
    "/set/data/selected_transcription_compute_device", "/set/data/selected_transcription_compute_type",
    "/set/data/ocr_source_language", "/set/data/ocr_min_confidence", "/set/data/ocr_poll_interval_ms",
    "/set/data/ocr_bubble_min_text_length",
    // Messages, VR overlays and appearance.
    ...toggle("convert_message_to_hiragana"), ...toggle("convert_message_to_romaji"), ...toggle("vrc_mic_mute_sync"),
    ...toggle("overlay_small_log"), ...toggle("overlay_large_log"), ...toggle("overlay_show_only_translated_messages"),
    ...toggle("overlay_vr_launcher_auto_hide"), ...toggle("overlay_vr_tooltip"), "/set/data/overlay_vr_launcher_hand",
    "/set/data/ui_language", "/set/data/font_family",
]);
export const isRelayAllowed = (path) => typeof path === "string" && VR_PANEL_RELAY_PATHS.has(path);

// VR画面へ写さない atom。VR画面は認証キーとトークンを表示しない。写すと、VR画面からキーを
// 読めてしまう。ウィンドウ共有を確認なしで再開するトークン (RestoreToken) も、VR画面では
// 使わないので写さない
export const isSecretAtomName = (name) => /(Auth(Key|Token)|RestoreToken)$/.test(name);

// VR画面へ写してよい状態 (SEC-03)。VR画面が読む設定のカテゴリ (useVr、useDevice などで丸ごと読む)
// と、VR画面がそのほかに読む atom だけを送る。高度な設定 (WebSocket、OSC、テレメトリ)、更新、
// ホットキーなどは送らない。VR画面のコードが新しい atom を読むようになったら、ここに足すまでは
// テストが失敗する (vrPanelStateScan.js がVR画面のソースから読んでいる atom を集める)
export const VR_PANEL_STATE_CATEGORIES = Object.freeze([
    "Appearance", "Device", "Ocr", "Others", "Transcription", "Translation", "Vr",
]);
export const VR_PANEL_STATE_ATOMS = Object.freeze([
    // The log, the launcher and its switches.
    "MessageLogs", "MessageInputValue", "TranslationStatus", "TranscriptionSendStatus", "TranscriptionReceiveStatus",
    "OcrCaptureStatus", "ForegroundStatus", "IsBackendReady", "IsOpenedConfigPage", "NotificationStatus",
    "IsOscAvailable", "OscUnavailableReason", "VrPanelLauncherIntro", "VrPanelLogOutOfView",
    // The language window.
    "LanguageMutation", "SelectableLanguageList", "SelectedPresetTabNumber", "SelectedYourLanguages",
    "SelectedTargetLanguages", "SelectedTranslationEngines", "TranslationEngines",
    // The settings window: meters, threshold checks and fonts.
    "MicVolume", "SpeakerVolume", "MicThresholdCheckStatus", "SpeakerThresholdCheckStatus", "SelectableFontFamilyList",
    // The input and output view.
    "IoFlow", "IoTraces", "IsOpenedIoFlowPanel",
]);

// settingsArray は SETTINGS_ARRAY (src-ui/logics/configs/config_page_setter/ui_config_setter.js)
export const vrPanelStateNames = (settingsArray) => {
    const names = new Set(VR_PANEL_STATE_ATOMS);
    for (const setting of settingsArray) {
        if (VR_PANEL_STATE_CATEGORIES.includes(setting.Category)) names.add(setting.Base_Name);
    }
    for (const name of names) {
        if (isSecretAtomName(name)) names.delete(name);
    }
    return names;
};
