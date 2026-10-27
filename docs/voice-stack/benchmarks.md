# 計測手順とP0設備

性能目標は仕様書 §8。現時点で性能ゲートの達成を判定できる反復測定はない。
fakeサーバーのテスト所要時間はTTS推論速度・VRChat遅延とは異なる。

## Linux実APIスモーク（n=1）

[測定JSON](measurements/2026-10-27-linux-irodori-smoke.json): CachyOS、RTX 4080 SUPER、
speech.cpp 0.8.11、取得済みIrodori MF F16、Vulkan0、声`none`、48 kHz mono。
load/warmup 15.67秒の終了後、CLIのテスト文を一時PipeWire sink/sourceへ送った。

| 境界 | 1回の観測値 |
|---|---|
| CLI内event→最初の非無音PCM write完了 | 191.372 ms |
| CLIプロセス起動→仮想sourceで非無音PCMをread | 304.746 ms |
| speech.cpp自身のログTTFA | 182 ms |

仮想sourceで非無音データを確認しCLIは終了コード0。生音声・参照音声・PCMファイルの
保存なし。試験用プロセス/ノードは停止・削除済み。
この1回からp50/p95/p99やVRChat E2E性能は判断しない。Windows、VRChat、HMD、
GPU競合、品質、長時間稼働は未検証。サーバーbinary/モデルhashをJSONに記録した。

`tools/voice_latency.py` は以下のCSVを集計する（音声・本文を含めない）。

```csv
metric,environment,warm,start_ns,end_ns
```

同じmonotonic clockで測った開始・終了を記録する。
`uv run --no-project python tools/voice_latency.py measurements.csv` はmetric /
environment / warm別にnearest-rank p50/p95/p99と件数を出す。空データから数値は作らない。
環境IDに対応する別JSONへOS、CPU/GPU、driver、VRAM、VRChat FPS、speech.cppの
commit/binary hash、モデルID/hash、voice ID（音声自体は保存しない）、rate、device、
backend、server設定、warmup回数、サンプル数を記録する。

## P1の計測境界

`last_first_write_ms` は **backend pipeline開始→最初の非無音PCMの出力write完了**。
UI IPC手前、OSバッファ、仮想マイクの到達、VRChatのネットワークは含まない。
完成したPCM全体を待たずに最初のwriteが行われることはfakeで検証する。
原文モードも既存翻訳処理の末尾で投入するため、翻訳ON時はその時間を含む。
キュー4件、最古待機を破棄、5秒超過メッセージを破棄、要求30秒で取消、
音声60秒分で上限、HTTP read/connect各2秒。PipeWire pipeは4096 bytesまで。

## 実機ハーネス

1. ウォームアップ前後を分け、短文30件以上でUI送信時刻と出力write時刻を取得。
2. 許可した計測音だけを仮想録音端から取得し、立ち上がり/相互相関で到達を測る。
3. VCは物理入力と仮想出力を同一clockで測る。ASR/翻訳の完了時刻をVC遅延に代用しない。
4. VRChat + WiVRn + HMD有/無、GPU負荷別にFPS/VRAM/音切れ/バッファを比較。
5. 本文や録音を保存する場合は別途明示的に有効化し、測定後に削除する。

| VC候補 | 実機結果 | 採用 |
|---|---|---|
| VCClient Windows CUDA/ONNX RVC | 未測定 | 保留 |
| Seed-VC Realtime Windows/Linux | 未測定 | 保留 |
| VCClient Linux標準Beatrice | モデル個別条件・実機未確認 | 保留 |

P2の選定記録はp50/p95、品質、ドロップ、VRAM、対応OS、ライセンスを必須とする。
