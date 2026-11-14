# 利用者向けドキュメントの構成の見直し 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 利用者向けサイトを「はじめに／やりたいこと／機能の詳細／設定と運用」に組み直し、アプリとサイトの機能の名前をそろえ、自分のモデルを使う方法をサイトとアプリの両方から案内する。

**Architecture:** アプリ側は文言（`locales/*.yml`）と、名前を直書きしている数か所のコンポーネントだけを変える。動作は変えない。サイト側は VitePress の設定（サイドバー、検索、トップページ）を直し、新しいページを3つ足し、既存のページを同じ型に書き直す。スクリーンショットは既存の撮影の流れで撮り直す。

**Tech Stack:** React 18、i18next、Jotai、Node の `node --test`（`src-ui/**/*.test.js`）、VitePress 1.6.4、Playwright（`tests/voice/test_docs_screenshots.py`）、yomiyasu 3.1.0。

**Spec:** `docs/superpowers/specs/2026-11-14-user-docs-structure-design.md`

## Global Constraints

- 機能の名前（日本語／英語）: テキスト読み上げ（TTS）／Text to speech (TTS)、ボイスチェンジャー（RVC）／Voice changer (RVC)、音声認識（ASR）／Speech recognition (ASR)、チャット読み取り（OCR）／Chat reading (OCR)。
- 英語のメイン画面のスイッチ: Voice2Chatbox → Mic input、Speaker2Log → Listening。日本語の「マイク入力」「聞き取り」は変えない。
- 内部の id、設定のキー、IPC と OSC の名前、ログの文は変えない。
- サイトの既存ページの URL は変えない（`guide/troubleshooting` と `guide/first-setup` はアプリが直接開く）。
- `en.yml` と `ja.yml`、`site/ja` と `site/en` は必ず両方を直す。
- 日本語の文は yomiyasu を通す。読点を減らし、段落、改行、箇条書き、見出しを増やす。
- 文言を変えても、マイクの有効化、モデルの取得、送信、音声経路の変更が勝手に起きないこと。
- 公開するスクリーンショットに、このPCのハードウェア名を写さない（既存の撮影の流れの置き換えを使う）。
- コンソールのプログラムは隠して起動する（フォアグラウンドの端末を出さない）。アプリの画面を開くのはよい。

## Review Focus

1. 長い名前が狭い幅で切れる、または不規則に折れる → 「（」の前で2行に分かれ、切れずに読める（Task 1 の `splitFeatureLabel` の試験と、Task 7 の撮影）。
2. 行き先を指す文に古い名前が残る（「設定の「TTS」で」「Settings → Transcription →」）→ 試験が古い書き方を見つけて失敗する（Task 1 の `featureNames.test.js`）。
3. 自分のモデルの案内のリンクが、表示言語でない言語や存在しない節を開く → 日本語の表示では `/ja/guide/custom-models#rvc` のように開く（Task 3 の試験、Task 5 のアンカー）。
4. 日本語の検索で、文の途中の語（「読み上げ」「仮想マイク」）が引けない → ビルドした索引で引ける（Task 4 の確認）。
5. RVC のエラーがコードのまま出る → 既知のコードには日本語と英語の文が出る（Task 2 の試験）。

---

### Task 1: アプリの機能の名前

**Files:**
- Create: `src-ui/logics/common/featureLabel.js`
- Create: `src-ui/logics/common/featureLabel.test.js`
- Create: `src-ui/logics/common/featureNames.test.js`
- Modify: `locales/ja.yml`、`locales/en.yml`
- Modify: `src-ui/views/app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch.jsx:38-46,108-111,165-167`
- Modify: `src-ui/views/app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch.module.scss`
- Modify: `src-ui/logics/configs/config_page_setter/hotkeys/useHotkeys.js:401-403`
- Modify: `src-ui/views/app/config_page/setting_section/setting_box/hotkeys/Hotkeys.jsx:29-30`
- Modify: `src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/VoiceSettings.jsx:53`
- Modify: `src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/DirectVoiceSettings.jsx:89-90`

**Interfaces:**
- Produces: `splitFeatureLabel(label: string) -> { name: string, abbr: string | null }`（`src-ui/logics/common/featureLabel.js`）。
- Produces: 新しいキー `main_page.tts`、`main_page.rvc`。Task 2 の `notify` と、Task 7 の撮影が使う。

- [ ] **Step 1: `featureLabel.test.js` を書く**

```js
test("splits a feature name before its abbreviation", () => {
    assert.deepEqual(splitFeatureLabel("テキスト読み上げ（TTS）"), { name: "テキスト読み上げ", abbr: "（TTS）" });
    assert.deepEqual(splitFeatureLabel("Text to speech (TTS)"), { name: "Text to speech", abbr: "(TTS)" });
    assert.deepEqual(splitFeatureLabel("翻訳"), { name: "翻訳", abbr: null });
    assert.deepEqual(splitFeatureLabel("Mic input"), { name: "Mic input", abbr: null });
    assert.deepEqual(splitFeatureLabel("（TTS）"), { name: "（TTS）", abbr: null });
});
```

- [ ] **Step 2: `featureNames.test.js` を書く**

`recoveryTranslations.test.js` と同じく `js-yaml` で両方の yml を読み、i18next で引く。

```js
const NAMES = {
    ja: { "main_page.tts": "テキスト読み上げ（TTS）", "main_page.rvc": "ボイスチェンジャー（RVC）",
          "main_page.ocr": "チャット読み取り（OCR）", "main_page.transcription_send": "マイク入力",
          "main_page.transcription_receive": "聞き取り",
          "config_page.side_menu_labels.tts": "テキスト読み上げ（TTS）", "config_page.side_menu_labels.rvc": "ボイスチェンジャー（RVC）",
          "config_page.side_menu_labels.transcription": "音声認識（ASR）", "config_page.side_menu_labels.ocr": "チャット読み取り（OCR）",
          "config_page.tts.tts_settings.label": "テキスト読み上げ（TTS）", "config_page.rvc.rvc_settings.label": "ボイスチェンジャー（RVC）" },
    en: { "main_page.tts": "Text to speech (TTS)", "main_page.rvc": "Voice changer (RVC)",
          "main_page.ocr": "Chat reading (OCR)", "main_page.transcription_send": "Mic input",
          "main_page.transcription_receive": "Listening",
          "config_page.side_menu_labels.tts": "Text to speech (TTS)", "config_page.side_menu_labels.rvc": "Voice changer (RVC)",
          "config_page.side_menu_labels.transcription": "Speech recognition (ASR)", "config_page.side_menu_labels.ocr": "Chat reading (OCR)",
          "config_page.tts.tts_settings.label": "Text to speech (TTS)", "config_page.rvc.rvc_settings.label": "Voice changer (RVC)" },
};
// 行き先を指す古い書き方。yml の本文（コメントを除く）に1つも残っていないこと。
const STALE = {
    ja: ["設定の「TTS」", "「TTS」で", "TTSの設定", "TTS設定", "でTTSをオン", "RVCスイッチ", "RVC設定",
         "設定 → 音声認識 →", "設定の「音声認識」", "「チャット読み取り」で", "「チャット読み取り」の設定", "「チャット読み取り」のページ"],
    en: ["Chat Transcribe", "Voice2Chatbox", "Speaker2Log", "Settings → Transcription", "Settings → TTS",
         "TTS settings", "the TTS page"],
};
```

試験は2つ: `NAMES` の各キーの値が一致すること。`STALE` の各文字列が、その言語の yml のコメント以外の行に無いこと（見つかったら行番号を出して失敗）。

- [ ] **Step 3: 試験が落ちることを確かめる**

Run: `node --test src-ui/logics/common/featureLabel.test.js src-ui/logics/common/featureNames.test.js`
Expected: FAIL（`featureLabel.js` が無い、`main_page.tts` が無い、古い書き方が残っている）

- [ ] **Step 4: `splitFeatureLabel` を書く**

末尾が「）」か「)」で、その前に「（」か「 (」があり、前に名前が残るときだけ分ける。

- [ ] **Step 5: yml を直す**

- `NAMES` のキーを足すか書き換える。
- 行き先を指す文は、新しい名前を「」で書く。例: 「先にTTSの設定で出力デバイスを選んでください。」→「先に「テキスト読み上げ（TTS）」の設定で出力デバイスを選んでください。」。「設定 → 音声認識 → リアルタイム字幕」→「設定 → 音声認識（ASR） → リアルタイム字幕」。英語は `Settings → Text to speech (TTS)`、`Settings → Speech recognition (ASR) → …`、`Settings → Chat reading (OCR)`。
- 英語の文の中の機能名としての Chat Transcribe は Chat reading にする（行き先を指す所は Chat reading (OCR)）。
- 行き先を指さない文（`headroom_alone`「TTSのみ：0.5 GiBを残す」など）は短い名前のままでよい。
- 「入力と出力」の図の名前（`io_flow.*`）:
  - `output.speech`「読み上げ」→「テキスト読み上げ」（en: Text to speech）
  - `conversion`「声の変換」→「ボイスチェンジャー」（en: Voice changer）
  - `conversion_with`「{{engine}}で変換」→「ボイスチェンジャー（{{engine}}）」（en: `Voice changer ({{engine}})`）
  - `conversion_guide`、`conversion_live` も「声の変換」を「ボイスチェンジャー」にする
  - `reason.tts_off`「TTS がオフ」→「テキスト読み上げ（TTS）がオフ」
  - `speech_path.device`「TTS の出力デバイスへ」→「テキスト読み上げ（TTS）の出力デバイスへ」
  - `output_short.speech`「読み上げ」は、デスクトップの細い表示に使うので変えない。
- 日本語の文は `yomiyasu lint` を通す（下の Step 8）。

- [ ] **Step 6: コンポーネントを直す**

- `MainFunctionSwitch.jsx`: `label: "TTS"` を `t("main_page.tts")`、`label: "RVC"` を `t("main_page.rvc")` にする。`notify(..., "TTS")` と `notify(..., "RVC")` の第2引数も同じキーにする。`SwitchContainer` は `splitFeatureLabel(switchLabel)` で分け、`abbr` があれば `<span className={styles.switch_label_abbr}>` を名前の下の行に出す。`aria-label` と `title` は分けない全体の名前のまま。
- `MainFunctionSwitch.module.scss`: `.switch_label_abbr` は `display: block`、文字は名前より一回り小さく（`1.2rem`）、色は `--vox_description_text`。小さい表示（`is_compact_mode`）では出さない。
- `useHotkeys.js` と `Hotkeys.jsx`: `name: "TTS"` → `name: t("main_page.tts")`、`name: "RVC"` → `name: t("main_page.rvc")`。
- `VoiceSettings.jsx:53`: `label="TTS"` → `label={t("config_page.tts.tts_settings.label")}`。
- `DirectVoiceSettings.jsx:89-90`: `"RVC"` → `t("config_page.rvc.rvc_settings.label")`。107 行の `<option value="rvc">RVC</option>` はエンジンの名前なので変えない。
- `voice_ui.check_settings` を「「{{page}}」の設定を確認してください。」（en: `Check the "{{page}}" settings.`）にする。

- [ ] **Step 7: 試験が通ることを確かめる**

Run: `node --test src-ui/logics/common/featureLabel.test.js src-ui/logics/common/featureNames.test.js`
Expected: PASS

Run: `python tools/dev.py check --scope ui`
Expected: すべて PASS。名前を文字で比べている既存の試験が落ちたら、その試験の期待値を新しい名前に直す（動作の期待は変えない）。

- [ ] **Step 8: 日本語を yomiyasu で確かめる**

変えた日本語の文を `build/yomi/feature-names/` に書き出し、`yomiyasu lint --state-dir build/yomi/feature-names` を通す。指摘は文を直して解く。

- [ ] **Step 9: コミット**

```bash
git add locales src-ui
git commit -m "feat(ui): name features by what they do, with the short name in brackets"
```

### Task 2: ボイスチェンジャーのエラーの文言

**Files:**
- Modify: `locales/ja.yml`、`locales/en.yml`（`voice.input_errors` と `voice_ui.errors`）
- Create: `src-ui/logics/voice/voiceChangerErrors.test.js`

**Interfaces:**
- Consumes: Task 1 の `main_page.rvc`（`notify` の第2引数）。

- [ ] **Step 1: 試験を書く**

```js
const CODES = ["vc_options_invalid", "vc_runtime_missing", "vc_model_missing", "vc_engine_format_invalid",
    "vc_index_failed", "vc_runtime_version_unsupported", "vc_checkpoint_incomplete",
    "reference_duration", "reference_local_file"];
// 両言語で voice.input_errors.<code> と voice_ui.errors.<code> があり、コードそのものではないこと。
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `node --test src-ui/logics/voice/voiceChangerErrors.test.js`
Expected: FAIL（キーが無い）

- [ ] **Step 3: コードが画面に届く道を確かめる**

`src-python/controller.py` で、`ValueError` の引数がそのまま `directError` か `directState.error` になることを確かめる。届かないコードがあれば、そのコードは `CODES` から外し、理由を計画の末尾の「残り」に書く。

- [ ] **Step 4: 文言を足す**

1文目で何が起きたか、2文目で次にすること。例:
- `vc_model_missing`: 「RVCモデル（.pth）が見つかりません。「ボイスチェンジャー（RVC）」の設定でファイルの場所を確かめてください。」
- `vc_engine_format_invalid`: 「このモデルは使えません。RVC v1 か v2 で、標本化周波数が 32k・40k・48k のモデルを選んでください。」
- `reference_duration`: 「参照のWAVは1〜30秒にしてください。」
- `vc_index_failed`: 「検索インデックス（.index）を読み込めません。別の .index を選ぶか、混合率を 0 にしてください。」

残りも同じ形で書く。`yomiyasu lint` を通す。

- [ ] **Step 5: 通ることを確かめる**

Run: `node --test src-ui/logics/voice/voiceChangerErrors.test.js`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add locales src-ui/logics/voice/voiceChangerErrors.test.js
git commit -m "fix(ui): explain voice changer errors instead of showing their codes"
```

### Task 3: 設定から自分のモデルの案内を開く

**Files:**
- Modify: `src-ui/logics/ui_configs.js:122-144`
- Create: `src-ui/views/app/config_page/setting_section/setting_box/_components/custom_model_link/CustomModelLink.jsx`
- Modify: `src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/SpeechServers.jsx`（`speech_servers.help` の近く）
- Modify: `src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/DirectVoiceSettings.jsx`（RVC と Seed-VC）
- Modify: 翻訳の「ローカルLLM・互換サーバー」と、音声認識の「カスタムWhisperサーバー」を描くコンポーネント（`Translation.jsx` と音声認識の設定。`grep -r "custom_whisper_url\|openai_compatible_url" src-ui` で探す）
- Modify: `src-ui/views/app/others/splash_component/SplashComponent.jsx:54`
- Modify: `locales/ja.yml`、`locales/en.yml`（`config_page.custom_model_link`: 「自分のモデルを使う方法」／ "How to use your own model"）
- Create: `src-ui/logics/common/customModelLink.test.js`

**Interfaces:**
- Produces: `generateLocalizedDocumentUrl(lang)` の戻り値に `vrct_document_custom_models_url: string` を足す（例 `https://kein5.github.io/VRCT-VOX/ja/guide/custom-models`）。
- Produces: `<CustomModelLink section="tts" | "asr" | "whisper-server" | "rvc" | "seed-vc" | "translation" />`。`section` は Task 5 の見出しのアンカーと同じ文字列。
- Consumes: Task 5 のアンカー（`{#tts}` など）。

- [ ] **Step 1: 試験を書く**

```js
test("custom model link opens the page in the display language", () => {
    assert.equal(generateLocalizedDocumentUrl("ja").vrct_document_custom_models_url,
        "https://kein5.github.io/VRCT-VOX/ja/guide/custom-models");
    assert.equal(generateLocalizedDocumentUrl("en").vrct_document_custom_models_url,
        "https://kein5.github.io/VRCT-VOX/en/guide/custom-models");
    assert.equal(generateLocalizedDocumentUrl("ko").vrct_document_custom_models_url,
        "https://kein5.github.io/VRCT-VOX/en/guide/custom-models");
});
test("CustomModelLink opens the section and does nothing else", async () => {
    // openUrl を差し替え、押すと `${url}#rvc` を1回だけ開くこと。ほかの store や送信を呼ばないこと。
    // openUrl が失敗したら model_downloads.link_error を出すこと。
});
test("splash opens the troubleshooting page in the display language", async () => {
    // SplashComponent が generateLocalizedDocumentUrl に i18n.language を渡すこと。
});
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `node --test src-ui/logics/common/customModelLink.test.js`
Expected: FAIL

- [ ] **Step 3: 実装する**

- `ui_configs.js`: `vrct_document_url_chunk_custom_models = "guide/custom-models"` を足し、`generateLocalizedDocumentUrl` が `vrct_document_custom_models_url` を返すようにする。
- `CustomModelLink.jsx`: `useI18n` の `i18n.language` から URL を作り、`openUrl`（`@tauri-apps/plugin-opener`）で `${url}#${section}` を開く。失敗したら `ModelDownloads.jsx:82` と同じく `model_downloads.link_error` を出す。見た目は設定の画面の既存のリンクと同じ。
- 置く所: `SpeechServers.jsx` の TTS（`section="tts"`）と ASR（`section="asr"`）、RVC（`rvc`）、Seed-VC の入力の転送（`seed-vc`）、翻訳のローカルLLM（`translation`）、カスタムWhisperサーバー（`whisper-server`）。
- `SplashComponent.jsx:54`: `generateLocalizedDocumentUrl()` を `generateLocalizedDocumentUrl(i18n.language)` にする。

- [ ] **Step 4: 通ることを確かめる**

Run: `node --test src-ui/logics/common/customModelLink.test.js` と `python tools/dev.py check --scope ui`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add locales src-ui
git commit -m "feat(ui): link each model setting to how to use your own model"
```

### Task 4: サイトの骨組み（サイドバー、検索、トップページ）

**Files:**
- Modify: `site/.vitepress/config.mts`
- Modify: `site/ja/index.md`、`site/en/index.md`
- Create: `tools/check_site_search.mjs`

**Interfaces:**
- Produces: 新しいページの URL `/ja/guide/tasks`、`/ja/guide/how-it-works`、`/ja/guide/custom-models`（英語も同じ）。Task 5 が中身を書く。

- [ ] **Step 1: サイドバーを設計の「1. サイトの構成」の並びにする**

`sidebarJa()` と `sidebarEn()` を直す。グループは「はじめに」「やりたいこと」「機能の詳細」「設定と運用」（en: Getting started / What you want to do / Features / Setup and operation）。項目の名前は Global Constraints の名前にそろえる。

- [ ] **Step 2: 検索に日本語の区切りを足す**

`search.options.miniSearch.options.tokenize` に、`Intl.Segmenter('ja', { granularity: 'word' })` で語に分け、空白と記号だけの語を捨てる関数を置く。同じ関数を `searchOptions.tokenize` にも置く（問い合わせの語も同じく分けるため）。関数は外の変数を使わずに書く（VitePress はテーマの設定の関数を文字列にして画面へ渡すため）。

- [ ] **Step 3: トップページ**

`index.md` の `actions` に「やりたいことから探す」（`/ja/guide/tasks`）を足す。`features` の名前を新しい名前にし、カードに「ボイスチェンジャー（RVC）」と「チャット読み取り（OCR）」を足す。

- [ ] **Step 4: 検索の確認の道具を書く**

`tools/check_site_search.mjs <dist>`: ビルドした `site/.vitepress/dist/assets/chunks/@localSearchIndexja.*.js` を読み、`読み上げ`、`仮想マイク`、`ボイスチェンジャー` がどれも索引の語として入っていることを確かめる。無ければ語を出して終了コード 1。

- [ ] **Step 5: ビルドして確かめる**

Run: `site/` で `npm run build`（新しいページはまだ空の見出しだけでよい。リンク切れで失敗しないよう、Task 5 の3ページを `# 題` だけで先に作る）
Expected: 成功

Run: `node tools/check_site_search.mjs site/.vitepress/dist`
Expected: 3語とも見つかる。見つからないときは、ブラウザ（`npm run preview` を隠して起動）で「読み上げ」を検索し、結果が出るかで判断する。出なければ設計の検索の節を満たせないので、止めてユーザーに報告する。

- [ ] **Step 6: コミット**

```bash
git add site/.vitepress/config.mts site/ja site/en tools/check_site_search.mjs
git commit -m "docs(site): group pages by what you want to do, and search Japanese by word"
```

### Task 5: 新しい3つのページ

**Files:**
- Create: `site/ja/guide/tasks.md`、`site/en/guide/tasks.md`
- Create: `site/ja/guide/how-it-works.md`、`site/en/guide/how-it-works.md`
- Create: `site/public/diagrams/how-it-works-ja.svg`、`site/public/diagrams/how-it-works-en.svg`
- Create: `site/ja/guide/custom-models.md`、`site/en/guide/custom-models.md`
- Modify: `site/ja/guide/models.md:3`、`site/en/guide/models.md`（自分のファイルの案内へのリンク）

**Interfaces:**
- Produces: `custom-models.md` の見出しのアンカー `{#tts}`、`{#asr}`、`{#whisper-server}`、`{#rvc}`、`{#seed-vc}`、`{#translation}`、`{#bought-models}`。日英で同じ。Task 3 が使う。

- [ ] **Step 1: 「やりたいことから探す」を書く**

設計の「2.」の10項目を見出しにする（見出しは目的の動詞で始める）。各項目に「要るもの」「手順の要点（3行ほど）」「詳しいページへのリンク」。

- [ ] **Step 2: 「声と文字の流れ」を書く**

- 図は SVG で描く。左に入力（自分の声、チャット入力、相手の声、相手のチャットボックス）、中に処理（音声認識（ASR）、翻訳、テキスト読み上げ（TTS）、ボイスチェンジャー（RVC））、右に出口（VRChat のチャットボックス、仮想マイク、字幕とログ、OBS と WebSocket）。サイトは暗い配色だけなので、暗い背景で読める色にする。文字は SVG の中に `<text>` で置き、日本語版と英語版を分ける。`alt` に図の要点を書く。
- 本文: 仮想マイクがなぜ要るか。どのスイッチがどの線をつなぐか。
- 「いまの設定でどこへ出るかを確かめる」節に `io-flow.webp` を置き、「入力と出力」へリンクする。

- [ ] **Step 3: 「自分のモデルを使う」を書く**

- 先頭に設計の「6.」の表（使えるもの、指定する所、アプリが確かめること）。
- 機能ごとの節（アンカーは上の Interfaces）。各節に「使えるファイル」「指定する手順」「うまくいかないとき（出るメッセージの文）」。
  - テキスト読み上げ: モデルの GGUF、声の GGUF と声名 `custom`、手元の外部サーバー（URL は `127.0.0.1`、`localhost`、`::1` だけ）。
  - Seed-VC: 参照の WAV は PCM で 1〜30 秒。
  - 翻訳: ローカルの翻訳モデルは一覧のものだけ。LM Studio、Ollama、OpenAI 互換サーバーに入れたモデルなら使える。
  - チャット読み取り: 自分のモデルは使えない、と書く。
- 対応するモデルの系統は speech.cpp の README（同梱の版）で確かめて書く。確かめられないことは書かない。
- 「購入したモデルと配布されているモデル」（`{#bought-models}`）: 設計の「6.」の箇条をそのまま中身にする。
- `models.md` の「手元のファイルを指定します」からこのページへリンクする。

- [ ] **Step 4: yomiyasu と、ビルド**

Run: 日本語の3ページを `yomiyasu lint --state-dir build/yomi/site-new` に通す。`site/` で `npm run build`。
Expected: 指摘を解いたあと lint が通る。ビルドが成功する。

- [ ] **Step 5: コミット**

```bash
git add site
git commit -m "docs(site): add pages for what you want to do, how voice and text flow, and your own models"
```

### Task 6: 既存のページを同じ型に書き直す

**Files:**
- Modify: `site/ja/features/*.md`（9ページ）、`site/en/features/*.md`（9ページ）
- Modify: `site/ja/guide/{introduction,install,first-setup,models,linux-audio,troubleshooting,privacy,license}.md` と英語の同じページ

- [ ] **Step 1: 機能のページを型にそろえる**

設計の「4. 機能のページの型」の順にする。

- 題を新しい名前にする: `tts.md`「テキスト読み上げ（TTS）」、`voice-conversion.md`「ボイスチェンジャー（RVC・Seed-VC）」、`transcription.md`「音声認識（ASR）とリアルタイム字幕」、`chat-reading.md`「チャット読み取り（OCR）」。
- 画像はページの先頭から、それを使う手順のすぐ下へ移す。
- 名詞の見出し（「使う声」「注意」「用意するもの」）は、何をするかの見出しにする（「声を選ぶ」「使う前に確かめること」「必要なもの」）。
- 「確かめた範囲」は最後に `::: details 確かめた範囲` で畳む（`vr.md`、`io-flow.md`、`transcription.md`）。
- 本文の「声の変換」は、機能の名前として使う所を「ボイスチェンジャー」にする。
- 自分のモデルに触れる所（`tts.md` の「すでに持っているGGUFファイル」、`voice-conversion.md` の「用意するもの」）から `../guide/custom-models#…` へリンクする。

- [ ] **Step 2: ガイドのページを直す**

- `introduction.md`: 冒頭の2文を「何ができるか」にし、「VRCTから増えたこと」は表のまま後ろに置く。「いまの状態」は「版と確かめた環境」にする。最後に「やりたいことから探す」と「声と文字の流れ」へ案内する。
- `first-setup.md`: 「次に読むページ」に「やりたいことから探す」を足す。
- `troubleshooting.md`: 症状の見出しのまま。名前を新しい名前にする。自分のモデルの症状（「自分のモデルを指定したら動かない」）を足し、`custom-models` へリンクする。
- そのほかのページは名前の置き換えと、長い段落を分けることだけ。

- [ ] **Step 3: 古い名前が残っていないか確かめる**

Run: `rg -n "読み上げ（TTS）|声の変換（RVC|Chat Transcribe|Voice2Chatbox|Speaker2Log" site/ja site/en`
Expected: 「テキスト読み上げ（TTS）」の一部として出る行のほかは0件。

- [ ] **Step 4: yomiyasu と、ビルド**

Run: 日本語の全ページを `yomiyasu lint --state-dir build/yomi/site-all` に通す。`site/` で `npm run build`。
Expected: lint が通る。ビルドが成功する。

- [ ] **Step 5: コミット**

```bash
git add site
git commit -m "docs(site): put every feature page in the same order, with the new feature names"
```

### Task 7: スクリーンショットと、狭い幅の確認

**Files:**
- Modify: `tests/voice/test_docs_screenshots.py`（新しいページの図が要れば足す）
- Modify: `site/public/screenshots/{ja,en}/*.webp`（撮り直し）

- [ ] **Step 1: 撮り直す**

Run: `python tools/docs_screenshots.py`（コンソールは隠して起動する）
Expected: 両言語の全部の画像が新しい名前で撮れる。メイン画面の「テキスト読み上げ」と「（TTS）」が2行で、切れていない。

- [ ] **Step 2: 狭い幅と VR を見る**

撮った `main.webp`、設定の各画面、`vr-io-flow.webp`、`flow-on-screen.webp` を開いて見る。左の列で名前が3行以上にならないこと、VR の設定ウィンドウの左のメニューで名前が切れないこと。切れていたら Task 1 の CSS を直して撮り直す。

- [ ] **Step 3: コミット**

```bash
git add site/public/screenshots tests/voice/test_docs_screenshots.py
git commit -m "docs(site): retake screenshots with the new feature names"
```

### Task 8: 開発者向けの文書と、最後の確認

**Files:**
- Modify: `DESIGN.md`、`PRODUCT.md`、`docs/spec/*.md` のうち、画面の名前を「」で引いている所
- Modify: 生成する一覧（`python tools/spec_catalog.py --write`）

- [ ] **Step 1: 画面の名前を引いている所を直す**

Run: `rg -n "「TTS」|「RVC」|Chat Transcribe|Voice2Chatbox|Speaker2Log" DESIGN.md PRODUCT.md docs/spec`
直したら `python tools/spec_catalog.py --write`。

- [ ] **Step 2: 全体の確認**

Run: `python tools/dev.py check`、`python tools/dev.py check --scope ui`、`site/` で `npm run build`、`node tools/check_site_search.mjs site/.vitepress/dist`、`python tools/dev.py check --scope commits --base origin/develop`
Expected: すべて成功。

- [ ] **Step 3: コミットと PR**

```bash
git add DESIGN.md PRODUCT.md docs
git commit -m "docs: use the new feature names in the design and spec documents"
```

develop へ PR を出し、CI が通ったらマージする（develop へのマージは確認なしでよい、とユーザーが決めている）。

## 残り

- 声名を間違えたときに読み上げのエラーが HTTP の番号のまま出る（`speechcpp_tts.py:272-273`）。今回は文書で案内し、別の作業として報告する。
