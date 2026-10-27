# ADR-005: 仮想マイクの寿命と保持ミュート

Status: ソースcheckout向けLinux実装を採用。host導入・VRChat再接続受入は保留。
Date: 2026-10-27
Related: [ADR-004](adr-004-audio-integration-boundaries.md)

## 問題と決定

Bの外部推論＋OS経路では、音声engineと仮想マイクの寿命を結び付けるとengine終了時に
入力endpointが消える。consumerによっては別入力へfallbackすることを前回の合成音試験で確認した。
またTTS単独cancelは後続発話や外部VCを継続的には抑止しない。

PipeWire daemon設定で最終sink/sourceとTTS/VC入力を所有する。sourceは常にmuteで生成する。
VoiceEventBusはmute/再開の両方で世代を進め、mute中に受け付けた古い発話も再開後に通さない。
VoiceRouteは保持状態をatomic replace＋fsyncで保存し、OS gateの観測値と要求値を区別する。
managed選択・アプリ再起動・endpoint変更・制御失敗は新たな明示再開を必要とする。

OS gate変更は短命のC helperがsystem libpipewireを使って行う。cookie/serialに一致するproxyを
同一接続でbindし、node.infoのmarker/classを確認してからset-paramする。
制御workerは既定0.1秒周期＋実行時間で状態を確認する。音声PCMを取り込む独自daemonは作らない。
通常の外部ケーブル設定は既定のまま。Windowsでmanagedの新規選択を拒否する。

## 他案と判断を覆す条件

- `pw-loopback`をTTSの子processとして保持: 簡単だが親/子終了でendpointが消えるため不採用。
- `pw-dump`で確認後に`pw-cli set-param name`: 確認と変更の間で同名nodeが置換され得るため不採用。
  CLIが同一接続でidentityを条件に操作できるようになればnative helperを除去できる。
- 全PCMを独自audio daemonで扱う: 今回の要件には不要。Linux/Windows共通DSPや、制御process
  の強制終了でも自動muteするlease/watchdogが製品要件になれば、追加processの費用とともに再評価する。

## 制限と検証

daemon自体の終了ではendpointが消える。SIGKILLされたVRCTはmute処理を実行できず、直前の
gate状態が残る。外部VCの自動停止を保証しない。次の起動時にmuteへ戻る。
外部アプリが直接gateを変更する場合の検出は即時ではなく、OS制御不能時は無音を保証できない。
このためstatus200は要求受付であり、pending=false/ready=trueと観測値の確認が必要。

CLIはVRCT停止中の一回の診断操作専用で、常駐監視は提供しない。
追加SDKはLinuxのsystem PipeWire headers/compilerのみ。モデルとpip依存は追加しない。
実測境界・30回試験・未検証事項は [managed-route-report.md](managed-route-report.md) に記録する。
