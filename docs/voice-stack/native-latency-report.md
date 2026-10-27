# 実TauriのOSC併走とUI起点遅延（2026-10-28）

**温まった短い日本語文30回で、UI送信イベント→最初の非無音PCM writeの目標を満たした。**
時計対応の誤差を含む上限値でp50 **208.296ms**、p95 **367.064ms**。
目標はp50 <350ms / p95 <800ms。モデル単体の推論時間でも、音が耳に届くまでの時間でもない。

実Tauri、実stdio/Main/Controller/Model、既存speech.cpp 0.9.0、独立PipeWireを通した。
同じ各送信で、実UDPの`/chatbox/input`を1件、連続録音の参照発話を1回確認。
TTS OFFでもOSCは1件、音声は無音、first-write traceは追加されなかった。
VRChatはこの測定では起動しておらず、UDP受信をVRChat上のChatbox表示成功とは扱わない。

## 条件と標本

- CachyOS / Linux6.18.55-2-cachyos-lts、Python3.11.17、GTK3.24.52 / WebKitGTK2.54.2。
- RTX4080SUPER、Vulkan0、導入済みIrodori MF F16、seed42、voice none、48kHz mono s16。
- 固定文「こんにちは。音声の接続テストです。」。別生成2回のPCMがバイト一致することを確認。
- server warmup後、UI warmup1回を別記録し、その後の30回を全件採用。遅い標本の除外なし。
- 各発話の終了と連続無音を待ってから次を送信。待ち行列負荷や複数文・言語の代表値ではない。
- DPMS inhibitorを全期間保持。ホストの音声デバイス・既定入出力・物理マイクは変更していない。

| 指標 | 下限 | 上限 |
|---|---:|---:|
| p50（nearest-rank） | 205.012ms | 208.296ms |
| p95（nearest-rank） | 363.772ms | 367.064ms |
| 最大標本の上限 | — | 368.920ms |

時刻対応区間の最大幅は3.417ms（許容5ms）。source readerの最大間隔45.974ms、100ms超の欠測0件。
機能試験はwarmup1 + warm30 + OFF1の32ケース、pytest **1 PASS / 340.57s**。
モデル不要fixtureでもwarmup1 + warm2 + OFF1を通過、pytest **1 PASS / 37.61s**。
fixtureの遅延はモデル性能として集計しない。

## 計測境界と実装

始点はWebDriverのclick呼出ではなく、実DOMのtrusted clickをcapture listenerが受けた時の
`performance.now()`。既存React handler、IPC、Controllerを差し替えていない。
終点はAudioRouterが最初の非ゼロPCMを出力adapterへwriteし終えた直後のPython `monotonic_ns()`。
Linuxでは選択したmanaged TTS sinkに接続するpw-catへの書込みであり、以降のOSバッファ、
仮想source read、VRChat・ネットワーク・イヤホン再生の遅延はこの値に含めない。
source録音は経路と発話回数を別途検証する。

ブラウザとPythonの時計の原点は同一と仮定しない。送信前後に25回ずつ、
Pythonの時刻読み取りでブラウザの`performance.now()`読取りを挟む。
往復時間の対称性を仮定せず、得たoffset区間の共通部分を用いる。
timer量子化の余裕を各読取りとUIイベントに1msずつ付与する。
これは試験期間中の単調時計の速度安定・suspendなしという条件付きの対応付けであり、時計同期の保証ではない。
区間が不整合、幅が5ms超、無音のみ、未完了/error、標本数不足なら達成判定しない。

ブラウザ時刻の性質と精度制限は[W3C High Resolution Time](https://www.w3.org/TR/hr-time-3/)、
Pythonのプロセス間単調時計は[Python3.11 time](https://docs.python.org/3.11/library/time.html#time.monotonic)を参照。
OSCの本文・即時送信・通知boolの契約は[VRChat公式仕様](https://docs.vrchat.com/docs/osc-as-input-controller)と照合した。

診断は`VRCT_VOICE_TRACE=/path/to/local.jsonl`を明示した場合だけ有効。
記録はschema、UUID形式のevent ID、バックエンド開始時刻、first-write時刻、rate、結果のみ。
本文・PCM・URL・任意例外文字列は記録しない。再生とstream teardownの終了後に書き、
first-write callback内では時刻をメモリに保持するだけ。8MiB上限、特殊file/書込み失敗時は音声を継続する。
欠けたログを速い成功標本へ読み替えることは試験が拒否する。

## 再実行と証拠

```sh
UV_CACHE_DIR=/tmp/vrct-uv-cache \
VRCT_TEST_NATIVE_MEASUREMENT=1 VRCT_TEST_MEASUREMENT_TRIALS=30 \
VRCT_TEST_SPEECH_BINARY=/path/to/existing/speech \
VRCT_TEST_SPEECH_MODEL=/path/to/existing/model.gguf \
uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py -- \
  uv run --no-project --python .venv_linux/bin/python python -m pytest -q \
  tests/platform/test_native_voice_measurement.py
```

モデル変数を省略するとfixtureを使う。Tauri native buildとtauri-driverの準備は[native UI報告](native-ui-report.md)を参照。
[計測器](../../tests/platform/native_voice_measurement.py)、[実Tauri試験](../../tests/platform/test_native_voice_measurement.py)、
[共有測定JSON](measurements/2026-10-28-native-ui-latency.json)。
rawは`tmp/voice-resume/native-measurement-{fixture,irodori}/`、各試験dirの`report.json`に全時計読取り、
送信ごとのOSC・PCM照合・outcomeを保存。本文を含む試験PCMや画像はgitignore対象。

単体ではtraceをRED5 FAIL / 5 PASSから修正し、音声194件が通過。時計計算はRED14→GREEN14。
既存Python全体は1173 PASS / 16 FAIL / 6 SKIP（15.07s）で従来のWindows依存16失敗と同じ。
全機能・全OSの合格ではない。正確な既存失敗名は`tmp/voice-resume/trace-full-regression.log`に保持。

## 残るゲート

本番UI→VRChatの実Chatbox表示と音声の同時確認、VRChat併用時のGPU負荷、Windows実機、
HMD/別プレイヤー/物理出力、実翻訳・VC・speech.cpp ASR・30分混在は未検証。
同一文30回のp95はこの標本の記述統計であり、他環境のp95や統計的信頼区間を保証しない。
