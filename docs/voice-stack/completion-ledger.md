# 全機能実装の継続記録

基準: [ユーザー仕様書](spec/VRCT_cpp_Codex_Implementation_Spec.md)、[開始指示](spec/VRCT_cpp_CODEX_START.md)、[原典索引](spec/VRCT_cpp_imozuru_evidence_map.md)。入力3ファイルは提供された原本の写し。
開始HEAD: `9dbd2400`。既存の`frail-walrus` worktreeを継続する。

## 継続・停止条件

2026-10-27: ユーザーは全機能完了まで閉ループで進めるよう指示。通常の実装・修正・自動試験・ローカルコミットは確認待ちを挟まない。
追加指示: 問題発生時はimozuruで原典と関連実装を調査。それでも解決策を得られなければループを終了し、作業を中断する。
未測定の性能や実機試験を成功として扱わず、仕様の各ゲートを維持する。モデルの新規取得・配布には仕様の同意条件を適用する。
upstream PR、共有branchへのpush、merge、releaseは実行しない。

## 要件と現在地

| 段階 | 実装・証拠 | 未完了の受入条件／次の成果物 |
|---|---|---|
| P0 | baseline・ADR・測定器・ライセンス台帳 | 新しい構成ごとの差分検証を継続 |
| P1 | TTS provider、scheduler、UI、OSC契約、Linux/Windows出力adapter。限定UI部品→実stdio→実TTS試験16件、VRChat試験は別群 | 実Tauri/全Model/設定永続化を含む起動、UI→VRChat一連の試験、Windows実機、仕様のUI起点性能 |
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
