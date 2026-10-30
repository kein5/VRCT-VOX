# 仮想マイク自動作成 / AppImage RVC 実機試験（2026-10-30）

## 実装

RVCページから「仮想マイクを準備して使用」で管理対象経路へ切り替えられる。
PipeWire + systemd user環境では未導入の経路を3つのpw-loopbackサービスで作成する。
既存の正常な手動経路はそのまま再利用。作成はミュート状態で、明示再開が必要。
音声サービスの再起動・物理入力の自動選択・モデル取得はしない。GUI終了時もendpointを残す。
Deviceページの音声経路を先頭へ移動し、RVCページにも準備状態/エラー/ミュート解除を表示。

実機でvc_worker_eofを再現し、AppImageの外部worker用protocol/settings同梱漏れを修正。
RVC/Seed双方の外部Pythonが、ソースcheckoutなしで起動できる回帰試験を追加。

## 確認結果

- 標準pytest: 1222 PASS / 6 SKIP（隔離ネットワーク）。
- 音声testファイル一式: 1093 PASS / 41 SKIP（同梱修正前の全体回帰）。同梱修正後の関連試験31 PASS / 1 SKIP。
- 自動準備/route/controller/gate: 58 PASS。
- ブラウザー: 6 PASS。RVCから準備・設定保持・未準備時の再開無効・ローカライズしたエラー。
- 私有PipeWire: 生成した3コマンドによる初期mute、合成PCM通過、制御終了後2秒無音、endpoint identity保持: 1 PASS。
- 実systemd: 一時ユーザーサービス3件の構文検証、起動、再start時identity維持、全cleanup成功。
- 最終AppImage: 実GUI→実Mia2026→私有仮想マイク、global mute、Stop、再起動時設定保持/入力停止: 1 PASS（27.68秒）。
- 最終AppImage通常起動/描画: FUSE・展開起動を含む4 PASS（28.67秒）。

旧AppImageのRVC試験はvc_worker_eofでFAILとして保持。修正版は別フォルダ/別実行。
初回sandbox試験のソケット制限による失敗と、古いscratch複製の再帰collection errorもログを保持し、適切な隔離環境/明示ファイル指定で再実行した。

## 測定境界

実モデル試験の入力は既存の合成日本語音声。physical_capture=false、vrchat=false、perceptual_quality=false。
最初の実入力試験ではAirPodsが切断され、production enumerate_sourcesは空配列となったため、録音開始前に停止。
その後ATH-CKS50TW2で実入力試験を実施した（下記）。聴感・VRChatへの到達・長時間は未確認。
停止81.64msは1回のUI操作→私有source読取りの値で、HMD/ネットワーク遅延ではない。
旧ASRのNoHost/NoDevice対応は別項目。RVC入力ではフィードバック防止のため自分の仮想マイクを除外する。
既存AITレビュアーへの接続はDesktop daemon credential unavailableで失敗し、独立レビューは未実施。新規agentなし。

## 成果物

- 最新AppImage: `build/bluetooth-rvc-fix-2026-10-30-artifacts/VRCT-TTS-3.6.0-beta.1-linux-x64-vulkan-release.AppImage`
- SHA256: `ec302690efae030671bd957cb90d6f56168965435507ba9feba9327bb754306c`
- 前回の設定で起動: 同フォルダ `run-with-test-settings.sh`
- 旧同梱修正版は `build/auto-microphone-rvc-fix-2026-10-30-artifacts/` に保持。Bluetooth開始修正を含まない。
- 実GUIの結果: `tmp/auto-virtual-microphone/native-rvc-fixed/test_native_rvc_selection_real0/report.json`
- 実systemd結果: `tmp/auto-virtual-microphone/service-native/report.json`
- 最終コードhash: `tmp/auto-virtual-microphone/source-hashes.json`
- imozuru一次資料: `/tmp/vrct-auto-mic-research/sources/`（PipeWire 1.6.10、systemd v259原文）

設計根拠: https://docs.pipewire.org/page_module_loopback.html および https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html 。
設定/停止の契約は既存ADR-005を継承。今回commit/push/公開は行っていない。

## ATH-CKS50TW2実入力とBluetooth開始修正（2026-10-30追試）

実GUIで入力選択には成功したが、旧同梱修正版は `asr_capture_clock_changed` で停止。
`physical-ath-1/report.json` はfailedとして保持し、cleanup後のgate一致・録音停止を確認した。
診断用captureで初期dummy driverからBluetooth側clockへのposition再束縛、続くlatency更新を記録した。
imozuruでPipeWire 1.6.10の `impl-node.c` / `stream.c` / `module-loopback.c` / `spa/node/io.h` を原文保存。
調査記録は `/tmp/vrct-bluetooth-capture-research/`。公式ソースではdriver更新時にPositionを再設定する。

`native/asr-capture/main.c` は最初のPCM送出前にclockとlatencyが1秒安定するのを待つ。
待機中のPCMは破棄し、稼働中の音声を1秒バッファしない。Linuxの共有録音処理に適用される。
3秒の起動watchdogと、開始後のclock/latency/endpoint変更時停止、破損・古い時刻の拒否は維持。
1秒はPipeWireの保証値ではなく、今回の実機を含めた保守的な起動条件。遅い・不安定な初期化では失敗になり得る。
250ms案は実機で再失敗。クロック変更を許容する診断版はlatency更新時の時刻後退をdecoderが拒否し、製品には採用していない。

- C回帰はdriver/latencyの遅い更新をRED→GREEN確認。最終の起動不安定watchdogを含む3件PASS。
- capture関連54件PASS、標準1222 PASS / 6 SKIP、音声1097 PASS / 41 SKIP。末尾に追加したwatchdogケースは後者の数には含めない。
- 初回の標準2件失敗と音声5件失敗・中断は隔離networkのlo無効によるもの。元ログを保持し、隔離内だけloを有効化して上記を再実行。
- 実capture単体: 起動約1.813秒、続く5秒で251フレーム、全フレーム非ゼロ、errorなし。音声保存なし。
- 最新AppImageの実GUI: ATH-CKS50TW2→Mia2026の変換状態を新しいbackend観測6回、約6.024秒確認。入力linkは各観測で選択した同一serialへactive、errorなし。
- Stop後はrequested/active/pending=false、capture nodeなし。owned appを回収し、gate identity/muteとユーザー設定ファイルの前後一致を確認。
- 公開sourceは全期間mute。観測PCMは20.6秒・1030フレーム、閾値64を超えるフレーム0、readerエラー/EOFなし、read gap最大44.16ms・100ms超0。PCMはファイル保存していない。

実入力試験は、選択・実workerの変換状態・停止のsmokeである。実音声の聴感、物理発話との内容照合、VRChat/他プレイヤー到達、遅延上限、長時間安定性を証明しない。
input linkの証拠は各時点のsnapshotであり、すべての短時間経路変更の監視ではない。
記録: `tmp/auto-virtual-microphone/physical-ath-fixed-2/report.json`、同 `ui/rendered.png`。
最終hash: `tmp/auto-virtual-microphone/bluetooth-final-hashes.json`。

最新AppImageの合成音回帰も1 PASS（28.25秒）。私有PipeWireでMia2026出力、global mute/明示再開、Stop後2秒無音、再起動後の設定保持/入力OFFを確認。停止84.63msはn=1のUI操作→source読取り境界で物理マイクの遅延ではない。記録: `tmp/auto-virtual-microphone/native-rvc-bluetooth/test_native_rvc_selection_real0/report.json`。
