# フェーズ結果 — 2026-10-27

**P0を記録し、P1のコードとfake E2Eを実装。Linux CLI→VRChatのマイクテストで発声・停止を確認。
P1全体の実機受入は未完了（Windows、VRCT UI→OSC＋音声の同時確認が残る）。**
仕様書 §6 のゲートに従い、P2～P5は未着手。VC/ASRが実装済みとは扱わない。

## P0

- コミット: `ad977081` — `feat(voice): establish baseline and measurement harness`。
- 変更: architecture/ADR/baseline/benchmarks、モデル不要テスト環境、timestamp集計CLI。
- 基準HEADは仕様書の `79419a1f2ce78d38993b0f33e273155667eb0b6a` と一致。
- 既存Nodeテスト4ファイルPASS。変更前UIビルドはロゴファイルの大小文字不一致でFAIL。
- 軽量Python依存のみでは全suiteが80件の収集エラー。詳細は[baseline](baseline.md)。
- 最初のsandbox確認後、許可された読み取りでGPU/既存speech.cpp/取得済みモデルを確認。
  後続PoCで実API→PipeWire仮想sourceの到達を確認。モデルはダウンロードしていない。

## P1の変更と手元で動く範囲

実装コミット: `55196e14` — `feat(tts): add streaming text speech and explicit virtual mic outputs`。
後続のdocsコミットに以下の実機PoC結果を追加。

### P1追試（2026-10-27）

- `tools/voice_acceptance.py`を追加。通常の音声経路から分離した実PipeWire上で
  合成信号の停止/キュー/切断/復旧と、既存speech.cppの反復測定を実行可能。
  終了時に所有プロセス・ノードを解放し、音声を保存せずJSON/CSVを出す。
- CLIの空文字/空白入力で無限待機する問題を修正。PipeWireのwrite中に切断された場合は
  `output_disconnected`を返すよう修正。
- 反復CLI追加時の自動テスト **77 PASS**（既存Controller 70 unittestケースも同suite内で再実行）。
  新規7件の測定CLIテストと1件の切断回帰テストを追加。ruff/diff check PASS。
  修正前の2ファイルを一時ディレクトリに復元し、空文字/空白のtimeoutと
  write時の未分類BrokenPipeErrorの**3 FAIL**を再現後、修正後のPASSを確認。
- 実Irodori MF / speech.cpp **0.9.0**、先行2要求＋本測定30回PASS。
  backend event→専用仮想source read: **p50 85.094 / p95 125.998 / p99 127.239 ms**。
- 合成信号による実PipeWire停止・切断・復旧 **30/30 PASS**。
  停止後最後の非無音read: **p50 39.943 / p95 41.885 / p99 42.184 ms**。
  別の既定出力への非無音漏出0件。明示再選択で復旧。
- 実speech.cpp TTSを使った停止・切断・再選択復旧の追加smokeも1回PASS。
- 測定条件・コマンド・JSON/CSVは[benchmarks](benchmarks.md)。
  UI起点の測定、Windows、HMD、30分混在負荷は未検証。
- ライセンス差分なし。重み・エンジン・生音声の追加同梱なし。

### VRChatデスクトップでの手動確認と修正

- ユーザーがVRChatの入力に`VRCT P1 Virtual Microphone`を選択。
  `pw-link`で専用source→VRChat入力、VRChat出力→イヤホンの分離を確認。
- 短文の初回は入力メーターが動いたが聞こえず、長めの再試験では初回PCM到達前に
  `transport_error`。サーバーログの処理時間4.309秒、client切断後2.306秒で停止。
  録音タイミングのずれが初回に影響した可能性はあるが、原因を断定しない。
- 初回音声待ちを10秒の共通期限（応答ヘッダ＋最初のPCM）へ分離。
  接続・後続readは2秒、scheduler全体は30秒を維持。取消は待ち中もsocketを中断する。
  初回期限超過は`first_audio_timeout`と明示する。遅い推論を低遅延達成とは扱わない。
- 修正後、長めの音声1要求が完了（errors=0）、ユーザーがVRChat録音テストで**声が聞こえた**と確認。
  backend event→PCM writeは93.598ms。VRChatの聞こえまでの時間ではない。
- 次の発声を開始約8秒で取消。待機2件を破棄、cancelled=1、queued=0、errors=0。
  worker idleまで5.152ms、ユーザーが**入力メーターは停止し、その後も再開しなかった**と確認。
  録音済みテストの再生は取消対象ではない。
- 最終自動テスト **83 PASS**。初回/後続timeout分離、共通初回期限、ヘッダ/body待ち中の取消、
  `Connection: close`を含む。ruff PASS。変更前は新しいtimeout契約の5ケースがFAIL、修正後PASS。
- [手動確認のJSON](measurements/2026-10-27-vrchat-desktop-manual.json)に失敗した試行も記録。
  VRCT UI送信、OSC Chatboxとの各1回同時動作、別ユーザーへのネットワーク送信、Windowsは未検証。

### 実装範囲

- `models/tts`: localhost専用PCM adapter、有界worker、重複抑止、取消、期限切れ破棄。
- `models/voice_events.py` とController末尾のchat専用フック。従来OSC/WebSocket/履歴の形式は維持。
- `models/audio_routing`: Windows PyAudioWPatch / Linux pw-catの明示出力。
  実rateをOSへ渡す。独自DSPリサンプラー・マイクcapture・VC混合はP1にはない。
- UI高度な設定: OFF/原文/訳文、翻訳先1つ、登録声名、日本語/多言語別サーバー、
  出力先、保存、停止、状態/エラー。声名は入力方式。英日翻訳、他UI言語は英語fallback。
- `tools/voice_cli.py`: GUI非依存のdoctor/devices/speak。モデル推論ライブラリ不要。
- PyInstaller CPU/CUDA除外、ZIP事前検査、Tauri resource検査、CI配布検査。
- Linuxの既存ビルド阻害要因だった `vrct.svg` importを実名 `VRCT.svg` に修正。

## 実行結果

| 検証 | 実結果 |
|---|---|
| `uv run --no-project python -m pytest -c tests/voice/pytest.ini tests/voice -q` | **83 PASS**（最終追試。テスト実行時間は音声遅延ではない） |
| 上記内の既存message pipeline suite | 元の70 unittestケースを無改変で再実行しPASS。モデル/OSサービスのみ注入。完全Windows実行の代わりではない |
| 既存Python選択8ファイル | **73 PASS / 4 FAIL**。4件はWindowsのAudioUtilities不在 |
| 変更前ソースから同4件を再実行 | **4 FAIL / 8 PASS**。同じAttributeErrorを基準コミットのファイルで再現 |
| 既存Node suite | **4ファイルPASS** |
| `npm run vite-build` | **PASS**（大小文字修正後） |
| 新規Pythonモジュール/テストのruff、`git diff --check` | **PASS** |
| `voice_cli.py --help` | **PASS**。Windows/torch/numpy/config/modelのimportなしを別プロセスで検証 |
| `voice_cli.py doctor` | **speech_health=unavailable**。Linux 6.18.55 CachyOS、Python 3.13.17、pw-catあり |
| 実speech.cpp 0.8.11 / 一時18080 | **health=ok、POST speech=200**。既存Irodori MF F16をVulkan0で使用 |
| CLI→PipeWire一時仮想source | **PASS（1回のsmoke）**。48 kHz mono、非無音PCMを確認、CLI終了0。録音保存なし |
| CLI→通常PipeWire→VRChat desktopマイクテスト | **声が聞こえたとユーザー確認**。途中停止後のメーター停止・再開なしも確認。UI/OSC/他ユーザー受信とは別 |
| Tauri / NSIS / PyInstaller実ビルド | **未検証**。cargo offlineはfont-kit未キャッシュで失敗 |
| 追加Windows/Linux CI | 定義追加済み、GitHub上では未実行 |

Fake HTTPで、PCMの任意分割/奇数バイト、実rate、最終チャンク前の出力、
WAV/4xx/5xx/切断/停止/タイムアウト/未起動/redirect拒否を検証。
有界キュー、重複、partial/受信/OCR除外、翻訳中の取消世代、デバイス解放、
明示device、設定保存/移行、restricted weight除外も検証。
テストのsocket作成はsandboxで拒否されたため、localhost fake serverだけを使う権限で実行。

既存Python選択suiteの再現:

```sh
uv run --no-project python -m pytest -q src-python/test/test_config_release_channel_self_heal.py src-python/test/test_config_validated_property.py src-python/test/test_config_validation_error.py src-python/test/test_utils_compute_device.py src-python/test/test_utils_log_masking.py src-python/test/test_utils_stdout_writer.py src-python/test/test_active_endpoint_tracker.py src-python/test/test_toolchain_file_encoding.py
node --test src-ui/logics/main/languageMutationCoordinator.test.js src-ui/logics/main/languageMutations.test.js src-ui/logics/common/vrPanelWire.test.js src-ui/logics/common/vrPanelTooltip.test.js
```

## 測定値・リスク・次のゲート

- 単発Linux PoC: event→PCM write **191.372 ms**、CLI起動→仮想sourceの非無音read **304.746 ms**。
  server自身のTTFAログは182 ms。環境・hash・境界は[測定JSON](measurements/2026-10-27-linux-irodori-smoke.json)。
- backend TTFA/専用仮想source到達のp50/p95/p99: 上記P1追試で記録。
  UI→通常仮想マイク/VRChat聞こえのp50/p95/p99: **未測定**。
  `last_first_write_ms` はbackend開始からPCM writeまで。仕様のE2E達成値に代用しない。
- Windows WASAPIの実音、停止残留時間、hotplug、WiVRn/HMD、
  GPU競合、30分安定性は未検証。OS/driverが停止しない場合の確実な解放はプロセス終了に依存する。
  Linux実グラフ→VRChatマイクテストの入力と聞こえは確認。別ユーザーでの受信は未確認。
- 既存翻訳ONでは原文TTSも既存pipeline末尾で始まる。翻訳待ち時間を含む。
- 読み上げ言語はVRCTの選択言語。本文の言語自動判定はしていない。
- 配布ゲート: 公式用publisher/識別子/更新先のfork向け整理、実インストーラー検査はP5で必要。
- P1次ステップ: [Windows](local-setup-windows.md)でVRCT UI→OSC＋音声各1回とOFF互換、
  仮想ケーブル・取消・復旧を実機確認。Linux GUIはP5。UI起点の遅延測定も残る。
- P2入口: 実機でVCClient/Seedの比較、ライセンスとOSの採用判断、独立adapter/fail-closedの実装。
  P3専用REST→Realtime、P4マイク翻訳発声、P5 Linux GUI/配布はその後。

外部モデル・エンジン・録音の同梱なし。upstream PR、push、releaseは実施していない。
