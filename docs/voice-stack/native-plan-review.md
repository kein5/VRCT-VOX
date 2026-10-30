# Linux native起動計画の最終レビュー（2026-10-28）

対象: `9dbd2400..a246beb0`、[native起動計画](../superpowers/plans/2026-10-27-native-voice-entry.md)。
独立したreviewerがread-onlyで5コミットを確認した。Critical 0、Important 2、Minor 0。
全低遅延機能の完成や配布承認を判定したレビューではない。

## 指摘と修正

1. `locales/en.yml` / `ja.yml`のモデル取得同意と既存テレメトリー項目が、UIの参照する
   `config_page.others`の外へ出ていた。実i18nextで英語・日本語・英語fallbackを使う韓国語が3件失敗。
   YAML階層を修正して3件通過。新規モデル取得の説明に加え、既存の説明とprivacy linkも検証する。
2. WebDriverの後片付けがdriver自身の終了だけを待ち、先にdriverが終了するとSIGTERMに応答しない
   子processが残った。実disposable processの試験は修正前2 FAIL / 1 PASS。
   groupと所有descendantsを追跡し、5秒の猶予後に残存processを終了、さらに3秒以内の停止を確認する。
   別sessionへ移った子も対象とし、PID再利用の検査はpsutilを通す。修正後3 PASS。
   zombieは実行も音声endpoint保持もしない終了済みprocessとして区別し、Popenの直系childはreapする。

再現テスト:
[翻訳の実lookup](../../src-ui/logics/common/modelConsentTranslations.test.js)、
[所有processの終了](../../tests/platform/test_native_driver_teardown.py)。
初回REDを含むログは`tmp/voice-resume/review-*.log`。
レビュー修正で音声モデル、既存メッセージ形式、推論APIは変更していない。

## 修正後の検証

選択回帰は **280 PASS / 1 SKIP / 5 warnings (95.68s)**。
実Tauriの描画・保存復元・再起動、モデル不要の音声9シナリオ、新規process終了試験を含む。
skipは別実行済みの実VRChat試験。実IrodoriとVRChatの結果は今回のhelper修正前の別実行であり、
修正後に再実行したとは扱わない。Nodeの関連7ファイル、Vite/native build、Ruff/diff checkも通過。
全体Python suiteの既存16失敗は継続して別扱いとする。

途中の選択回帰では、再起動直後の設定画面への移動が1回失敗した。
その時点の画像は描画され、DPMSはOnだった。imozuruでW3C Element Click、
Tauri window APIとローカルの非同期geometry復元を照合した。
テキスト入力が450×220のsplash寸法で先にmountする場合を観測したが、
追加32回の操作では失敗を再現できず、これを確定原因とはしない。
WebInspectorにfocusがあっても操作成功したため、focusだけでは説明できない。

試験は最初の設定操作前に通常寸法と実描画を確認し、操作後に設定画面の可視状態を待つようにした。
成功扱いのclickの再送は行わない。この条件でnative UI 2件、上記280件が通過した。
原因と再発率は未確定。原典・32回の結果・18検索の照合済みreport/digestは
`tmp/voice-resume/research/click/`、回帰ログは`tmp/voice-resume/review-all-with-native-fixture.log`。

## レビューで判定を保留した範囲への判断

| 保留事項 | 判断と、未検証のまま扱う費用 |
|---|---|
| Windows/HMD/別プレイヤー | 今回のnative Linux計画と別の実機ゲートに残す。実機固有の障害は未排除 |
| OSC表示と実VRChat音声の同時1回 | 今回はOSCを無効化しているためP1の未完了項目を維持。音声試験だけでは表示を保証できない |
| UIイベント→PCM write性能とpercentile | click-call→source readの各n=1を代用しない。仕様目標の合否は引き続き未判定 |
| VC / speech.cpp ASR / 翻訳発声 / 30分混在 | 後続フェーズへ残す。このレビューで全機能完成にはしない |
| legacy Linux capture/OCRと既存16失敗 | baselineとして明示し、P5で解消する。旧機能全体のLinux互換を保証できない |
| 10/27のDPMS状態とWebDriver内部RST機序 | 同一hostの再現・回避結果と原因推定を分ける。別原因の再発可能性は残る |
| release packageの完全性 | debug binary検査だけで配布物の検査済みとしない。配布時には全artifactを別途検査する |

## 作業中に行った判断

- 連続実装の指示に従い、通常のローカル修正・試験・コミットを逐次確認待ちにしなかった。
  設計の補完は作業記録へ残し、共有branchへのpush・merge・公開は行わない。変更はレビューで修正可能。
- Linuxの本番起動をP1実証に必要な範囲で前倒しした。Windows/HMDの代替証拠にはならない。
- Task 2/3は起動障害を実測してから具体化した。未確認APIを事前に固定しないためで、範囲の追加確認が必要になり得る。
- 既存Windows専用16失敗は、今回変更の前後で一致することを記録して別ゲートに残した。全suite合格ではない。
- Linux環境では任意RapidOCRのみuv excludeで外し、Windows依存の選択は維持した。Linux OCR対応時は再評価が必要。
- 永続化試験の言語値は既存の`ja`へ合わせた。製品schemaは変更していない。
- GUIのDOM応答と実描画を分離し、DPMSガードは実績のあるGio desktop inhibitorを必須とした。
  Gio/inhibitがない環境は明示失敗となり、未検証のidle inhibitorでは代替しない。
- 調査agentのstoreが共有されないため、既報の検索JSONだけを指定tmpへserializeして回収した。
  原文の取得・証拠判断は親側で行い、55検索の記録と引用照合を保持した。
- Native計画の完了と、P1全体・後続機能の完了を分ける。残る受入れで製品修正が必要になる可能性を維持する。
- 通常寸法・描画を設定操作の前提にする。追加の移動失敗の原因は未確定であり、回避条件での成功だけを記録する。

作業branchは`frail-walrus`のまま保持する。統合・リリース作業は今回の対象外。
