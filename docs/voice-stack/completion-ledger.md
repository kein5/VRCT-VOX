# 全機能実装の継続記録

基準: [ユーザー仕様書](spec/VRCT_cpp_Codex_Implementation_Spec.md)、[開始指示](spec/VRCT_cpp_CODEX_START.md)、[原典索引](spec/VRCT_cpp_imozuru_evidence_map.md)。入力3ファイルは提供された原本の写し。
開始HEAD: `9dbd2400`。既存の`frail-walrus` worktreeを継続する。

## 継続・停止条件

2026-10-27: ユーザーは全機能完了まで閉ループで進めるよう指示。通常の実装・修正・自動試験・ローカルコミットは確認待ちを挟まない。
追加指示: 問題発生時はimozuruで原典と関連実装を調査。それでも解決策を得られなければループを終了し、作業を中断する。
未測定の性能や実機試験を成功として扱わず、仕様の各ゲートを維持する。モデルの新規取得・配布には仕様の同意条件を適用する。
upstream PR、共有branchへのpush、merge、releaseは実行しない。

**現在: 再開（2026-10-28）。** ユーザー提供のDPMS再現調査と消灯防止ガードを照合し、
通常configの実Tauriで描画・設定保存復元・終了と再起動後のミュートを確認した。
10/27の原因はDPMS未記録のため推定と区別する。[追記報告・試験手順](native-ui-report.md)。
本番UI→実speech.cpp→独立仮想マイクの9ケースも通過した。[本番音声試験](native-voice-report.md)。
P1/Native Task 3はUI→VRChat一連の受入れと性能ゲートが残る。全機能完了として扱わない。

## 要件と現在地

| 段階 | 実装・証拠 | 未完了の受入条件／次の成果物 |
|---|---|---|
| P0 | baseline・ADR・測定器・ライセンス台帳 | 新しい構成ごとの差分検証を継続 |
| P1 | TTS provider、scheduler、UI、OSC契約、Linux/Windows出力adapter。部品UI試験16件、実Tauri/全Modelの描画・保存復元・安全な再起動、本番UI→実TTS→独立仮想マイク9件 | UI→VRChat一連の試験、Windows実機、仕様のUI起点性能 |
| P2 | OS音声経路BのPoCとmanaged endpoint | 外部VC契約・health・明示passthrough/converted/mute、source選択、切断fail-closed、UI、fake process試験、実VC比較 |
| P3 | 既存legacy ASRを維持 | speech.cpp専用REST→Realtime、mic/speaker別session、VAD、partial/final置換、capture/resample、有界queue、UI字幕・既存翻訳へのfinal接続 |
| P4 | テキストの原文/訳文TTSのみ | mic final訳文発声、VCとの排他/ducking、優先度・期限、remote受信の再送防止、多言語振分け |
| P5 | Linux専用graphと一部host試験、禁止OCR重み除外検査 | ネイティブUI/配布・fork識別、両OS障害復旧、30分混在負荷、回帰、実artifact台帳 |

## 判断

- Ruling: P1の実アプリ検証に必要なLinux起動作業をP5から前倒しする — Windows実機を前提にしたままP1を完了扱いにせず、利用者のCachyOSで実経路を検証するため — Windows・HMDを代替した証拠にはならない。
- Ruling: 調査原文とraw試験はworktreeの`tmp/voice-completion/`、共有する結論・計画・測定要約はdocsへ — 書込み可能範囲と既存成果物方針に合わせる — tmpを削除すると原文/raw再取得が必要。
- Ruling: 既存設計Bを条件付きで継続し、全機能を一度に作り直さない — 既に停止・故障の証拠があり、追加抽象化の利益は未測定 — Bの判断を覆す条件はADR004/005のまま。

## 現在の作業

Linux本番起動: Python依存不足、Windows固定sidecar path、起動時のモデル自動取得を調査。
imozuruの2検索役は完了。原文を保存し、Tauri prerequisites→sidecar契約、PyAudioWPatch→固定SpeechRecognition実装、uv環境→Python削除APIへたどった。
既存GTK/WebKitGTKとPortAudio開発環境は検出済み。Python3.11.17専用venvをuvでtmpへ用意し、Windows限定依存・任意OCR/buildを除いた既存依存111packageを導入。既存venvは未変更。

### Native Task 1: Linux開発sidecar

Windowsのinterpreter pathを固定参照する問題を再現（6 FAIL / 4 PASS）。OS別pathとUnix execによる同一PIDへの置換を追加し、10 PASS。
音声180件と併せて190 PASS。Ruff/diff check PASS。元の軽量環境で全体pytestは引き続き80 collection error。
実Tauri・全Model・Windows実機はこの試験の範囲外。根拠: [Tauri sidecar契約](https://v2.tauri.app/develop/sidecar/)、[Rust CommandExt::exec](https://doc.rust-lang.org/std/os/unix/process/trait.CommandExt.html#tymethod.exec)。
テストは`tests/platform/test_dev_sidecar.py`、rawは`tmp/voice-completion/sidecar-{red,green}.log`と`task1-tests.xml`。

### Native Task 2進行中: Python import互換

実依存で再現した2点を原典と照合して修正: s16 WAV処理がPyAudioWPatchを必要としていた箇所を固定16bit幅に変更、
Windows専用WINFUNCTYPEの宣言を既存OS判定へ合わせた。実PCM・画像helper試験は各RED→GREEN、既存transcriberと合わせて60 PASS（依存警告7件）。
本番Modelのimportが成功。TauriのLinux cargo check/buildも成功したが、GUI起動・Controller.initはまだ未検証。
Rust依存取得と正しいtarget tripleのsidecar配置で、従来font-kit未キャッシュ/sidecar不在によるbuild停止は解消。
Windows captureはLinux未対応のまま。これをGUI全体・ASR入力の完成とは扱わない。

### Native Task 2: 本番初期化・設定の保存復元

`AUTO_DOWNLOAD_MODELS`を既定OFFで永続化し、起動時の初回取得と再試行の両方へ適用。
その他設定にON/OFF操作を追加。旧configにキーがない場合もOFF。既存モデルの利用と明示取得APIは維持する。
`VRCT_CONFIG_DIR`で設定・logsだけを分離し、既存利用者の設定を変更せず実起動を試験できるようにした。
Linuxの`.venv_linux`選択、Windows専用3依存のmarker、任意OCR除外profileを追加。
既存venvは未変更。Windowsで評価したmarkerは既存3依存を選択するが、Windows実機試験の代替ではない。

検証: 関連suite **201 PASS**、実Main/Controller/Modelを2回起動するstdio試験 **1 PASS**、Vite build PASS。
最終選択回帰（実stdio、UI endpoint契約、既存transcriberを含む）は **266 PASS / 5 warnings**。
保存した日本語voice名が再起動後も復元され、音声OFF・モデル自動取得OFFを確認。Tauriや音声経路はこのstdio試験に含めない。
全体suiteは **1173 PASS / 16 FAIL / 6 SKIP**。修正前の実依存環境と同じ16失敗で、
内訳はWindows endpoint tracker 4、Windows専用sample-player 3、Windows clipboard 7、VR panel capture 2。
軽量環境の80 collection errorと区別する。これらをLinux対応済みとしてskipで隠さず、P5の未対応項目として残す。
変更範囲のRuffで新規違反は解消。既存config unused import 1とtranscriber import-order 5は未変更。

raw: `tmp/voice-completion/{settings-red,settings-green,task2-selected,task2-general,native-startup,task2-ui-build}.log`。
実起動stdout/stderr・保存設定は同`native-startup-run/`内（テスト用生成tokenを含むため公開対象外）。
imozuru原典10本、ローカル実装snapshot、hash一覧と引用照合済みreport/digestは同`research/linux-native/`。
Python検索役の追加queryは未回収と記録し、回収できた7 queryのhitsを保存。原文の再配布はしない。
起動障害の解決策は得られたためユーザー指定の中断条件には該当せず、実Tauri受入れへ進む。

- Ruling: Linux環境では任意OCRだけをuv excludeで導入対象から外す — Windowsのrequirements選択を変えず、未対応captureとcv2競合を起動経路から外す — Linux OCR対応時は依存契約を再評価する。
- Ruling: 言語復元テストの入力を`Japanese`から既存の保存形式`ja`へ修正 — config原典の許容値に合わせるテスト修正であり、製品の言語形式は変更しない。

### Native Task 3途中: DOM接続と描画を分離して中断

内蔵モデル不足でUI全体がSplashに留まる条件と、Python warningの続きがfatalになる処理を修正。
実Tauri DOM試験はRED→GREEN。診断ログも`VRCT_CONFIG_DIR`へ分離した。
完成部分の選択回帰280 PASS / 1 SKIP / 5 warnings、Node 2 PASS、Vite/Tauri build PASS。
ただし描画を確認するrAF試験は1 FAIL、PID照合した実ウィンドウ画像は黒。
imozuruで調べた回避候補は試験プロセス内でのみ比較し、いずれも有効な解決策にならなかった。
実Tauri→音声経路への受入れは開始せず、ユーザー指示に従いここで実装ループを中断。
詳細・再開条件・証拠の限界は[native-ui-report.md](native-ui-report.md)を参照。
