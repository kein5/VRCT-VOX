# 計測手順とP0設備

性能目標は仕様書 §8。Linuxの専用PipeWireグラフでは反復測定済み。
UI→VRChatの性能ゲートは未判定。
fakeサーバーのテスト所要時間はTTS推論速度・VRChat遅延とは異なる。

## Linux反復測定（speech.cpp 0.9.0、n=30）

後続の[managed経路＋VRChat実TTS試験](live-tts-vrchat-report.md)では、通常3回の
event→仮想マイク初音と実cancel/muteを測定した。以下の独立グラフ30回とは統合しない。
同試験でserver強制終了時の検出遅れも再現しており、停止操作の値を故障時停止へ外挿しない。
[接続受付監視の修正レポート](tts-listener-failure-report.md)には、監視間隔ごとの実server故障・復旧の
独立グラフ試験を記録する。これは下記の通常発声30回やVRChatの受入れとは別群である。
[修正後ホスト・VRChat再試験](tts-fixed-vrchat-report.md)では、通常3回・復旧3回の各1回再生と、
故障3回の79〜84msでの仮想マイク無音化を確認した。UI起点の性能ゲートやp95の判定には使わない。

[実測JSON](measurements/2026-10-27-linux-irodori-090-repeat.json) /
[timestamp CSV](measurements/2026-10-27-linux-irodori-090-repeat.csv)。
同じ既存Irodori MF F16、RTX 4080 SUPER / Vulkan0、voice `none`。
起動時warmup 20.60秒と先行2要求を除外し、同じ日本語のテスト文を30回発声した。
speech.cppはこの測定前にホスト側で0.9.0へ更新済みだった。0.8.11の単発値とは集約しない。

| 計測境界 | p50 | p95 | p99 |
|---|---:|---:|---:|
| backend event生成→最初の非無音PCM write | 60.419 ms | 62.493 ms | 63.526 ms |
| backend event生成→専用仮想sourceの最初の非無音read | 85.094 ms | 125.998 ms | 127.239 ms |

48 kHz mono s16le、playback指定20ms、capture指定10ms。
PipeWire 1.6.10、専用daemon＋WirePlumber `policy` profile（物理デバイスmonitorなし）。
通常デスクトップの音声設定を変えず、測定後に専用プロセスとノードを削除。
VRChatはdesktop `--no-vr`、WiVRn serverも起動中だったが、HMD音声は未接続。
GPU競合条件は制御しておらずFPSは未測定。観測したGPU使用メモリは開始後6606 MiB、終了後9961 MiB。
UI IPC、通常デスクトップ音声経路、VRChat内部・ネットワーク・聞こえは含まない。
仕様§8のUI開始条件と異なるため、この数値でP1性能ゲートを達成扱いにしない。
n=30のnearest-rank p99は最大値であり、安定したtail推定ではない。

## 停止・切断・復旧の反復（合成PCM、n=30）

[実測JSON](measurements/2026-10-27-linux-routing-repeat.json)。
推論時間から切り離した持続信号を実PipeWireへ出力。
各回、待機キュー4件/overflow破棄16件、停止後キュー0件、デバイス削除時のエラー、
削除中の新規要求拒否、再作成・明示再選択後の再発声を確認。
別の仮想sinkを専用環境の既定に指定し、そのsourceを常時監視したところ非無音チャンク0件。

| 計測境界 | p50 | p95 | p99 |
|---|---:|---:|---:|
| cancel呼出→worker idle | 10.100 ms | 15.230 ms | 15.258 ms |
| cancel呼出→最後の非無音read | 39.943 ms | 41.885 ms | 42.184 ms |
| 仮想デバイス削除→worker idle | 6.208 ms | 8.418 ms | 11.388 ms |

停止後はreaderが稼働したまま150ms以上の無音も確認。read時刻はcapture bufferを含む上界で、
Windows、物理USB/Bluetooth抜き差し、VRChatの停止残留時間の代わりではない。

別途、合成PCMを実speech.cpp TTSへ置き換えた[障害smoke](measurements/2026-10-27-linux-tts-fault-smoke.json)
も1回PASS。HTTPを含む取消、発声中のデバイス削除、デバイス不在の要求拒否、
再作成・明示再選択後の発声を確認し、その後の通常発声も成功。
CLIに`--server`を渡すとこの実API障害smokeも反復測定の前に実行する。

## 反復CLI

`pipewire`、`wireplumber`（policy profile対応）、`pw-loopback`、`pw-cat`、`pw-dump`、
`pw-metadata`が必要。GUI、外部モデル、録音保存は不要。出力先は新しいディレクトリを指定する。

```sh
# 合成信号による停止・切断・復旧。モデル不要。
uv run --no-project python tools/voice_acceptance.py --route-runs 30 --output /tmp/vrct-routing-run
# ユーザーが用意した既存ローカルTTSも測定。サーバー起動・モデル取得はしない。
uv run --no-project python tools/voice_acceptance.py --server http://127.0.0.1:18080 --samples 30 --warmup 2 --output /tmp/vrct-tts-run
uv run --no-project python tools/voice_latency.py /tmp/vrct-tts-run/latency.csv
```

専用ソケット・一時stateを使用し、通常の既定デバイスや物理マイクには接続しない。
失敗時も部分的なJSON/CSVと失敗コードを残し、所有プロセスを終了する。
PCMはカウンターと時刻に変換して破棄。本文・生音声はレポートに保存しない。
初回開発試験ではWirePlumberの表示名一致で起動判定がタイムアウトしたため、
実際のPIDで判定するよう修正して再試験した。
分離方法は[PipeWire公式のruntime/socket変数](https://docs.pipewire.org/page_man_pipewire_1.html)と
インストール済みWirePlumber設定の`policy` profileに基づく。

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
音声60秒分で上限、HTTP connect/後続read各2秒。応答ヘッダと最初のPCMには共通10秒の期限を使う。
PipeWire pipeは4096 bytesまで。

## VRChatデスクトップ手動試験

[実機記録](measurements/2026-10-27-vrchat-desktop-manual.json)。ユーザーが専用仮想マイクを
VRChatの入力に選び、内蔵の録音・再生テストで声が聞こえたと確認した。
次の要求を約8秒で取消し、待機2件破棄・入力メーター停止・再開なしも確認。
成功した発声のbackend first writeは93.598ms、取消からworker idleまでは5.152ms。
これはVRChat内の遅延計測でも、他ユーザーへの送信確認でもない。

初回短文はメーター反応のみ、2回目の長文は初回PCM前の2秒timeoutで失敗した。
応答ヘッダ＋初回PCMの待ち上限を10秒へ分離した後、同じ長文で発声・ユーザー確認が成功。
長い初回待ちを許しても毎回その秒数を待つわけではなく、届いたPCMはすぐに出力する。
短文30回の既存percentileは修正前の観測として保持し、今回の単発測定とは混合しない。

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
