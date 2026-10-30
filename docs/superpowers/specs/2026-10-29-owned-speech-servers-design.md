# P5-B: 同梱speech.cppサーバーの所有とGUI接続

基準はユーザー仕様§§5,7–10と、承認済みのspeech.cpp同梱・GUI起動停止要件。
[P5-A](../../voice-stack/speechcpp-bundle-report.md)の固定部品を使い、外部HTTP連携の設計Bを維持する。
既存の閉ループ作業指示に従い、通常の実装・試験・ローカル保存は確認待ちを追加しない。

## 採用案

既存Python Controllerが必要なspeech.cpp子プロセスだけを所有し、既存HTTP/WS adapterへ接続する。
日本語TTS、多言語TTS、ASR+VADの3枠を独立して起動できる。全部を常駐させない。
単一サーバーに全モデルを詰める案は同一taskのTTSを2個ロードできず、故障/負荷も結合する。
Tauri側に別の管理RPCを作る案は既存Python制御経路と二重になるため採用しない。

以下の実装上の選択は担当者の判断。Windowsのネイティブ寿命管理は別PCで後日実施する。

## 永続設定と起動

- `SPEECH_SERVER_SETTINGS`: schema version1、3枠のモデルGGUFパス、ASRのVAD GGUFパス、
  任意のTTS参照voice GGUFパス、device `auto|cpu|gpu`。起動中フラグ、PID、portは保存しない。
- モデルはユーザーが指定した既存の通常ファイルだけ。絶対パスへ解決し、GGUF magicを確認する。
  名前解決による自動モデル取得を呼ばない。設定保存だけではモデルをロードしない。
- 同梱実行ファイルはP5-AのCPU/Vulkan SHA256と版に一致するものだけ。任意command/PATH探索は不可。
- Startは非同期。待ち受けは必ず127.0.0.1、port0でOSに空きportを割り当てさせる。
  モデルロード中にStopでき、起動完了までの上限120秒。起動/ロード失敗は固定error codeで表示する。
- 標準エラーはサイズを制限して読む。Ready API URLを取り出すだけで、本文やローカルパスをログへ保存しない。
  `/health`と`/v1/models`を確かめ、必要なtaskがロードされてからreadyとする。
- ASRにはrecognition+detection、TTSにはsynthesisを要求。異なるtaskなら起動失敗として終了する。
  声ファイルがある場合は`--add-voice custom=ABSOLUTE_PATH`で登録し、既存voice選択から`custom`を使える。

固定sourceの`server.cpp`、実物`serve --help`、既存専用ASR adapterを照合済み。
port0、task別モデル、モデルロード後のReady行は0.9.0の実装に基づく。
原典は`tmp/voice-resume/research/speech-bundle/sources/`。

## 寿命と停止境界

既存`native/vc-worker`のcreator-thread pidfd監視/PDEATHSIG chainに、固定speech serve起動の分岐を追加する。
一般的な任意コマンド実行APIにはせず、許す引数を上記に限定する。
各枠のowner threadが生存している間だけ子が生存し、親アプリ/owner thread/supervisorの終了で子も終了する。
Stopは即座に新しい利用を拒否し、終了確認には最大3秒。未終了のownerを捨てず、次のStartをbusyとして拒否する。
ユーザーが外で起動したspeechサーバーをPID名検索等で終了しない。

状態は`stopped/preparing/ready/stopping/failed`と世代番号で表す。
古いStart要求や遅れて届いた状態で停止が取り消されないようにする。
アプリ起動時は全枠stopped。保存済みモデルパスだけで自動起動・録音・発声を始めない。
外部/同梱の選択は設定として保持し、同梱が停止中の場合は外部URLへ暗黙にfallbackしない。

## 既存音声経路との接続

`VoiceSettings`に`japanese_server`と`multilingual_server`（`external|bundled`、既定external）を追加。
元のURLとvoice欄は保持する。同梱選択時は実行時のready endpointだけを解決し、portを永続URLへ書き戻さない。
TTS要求を処理するworkerでendpointを解決する。HTTP/モデルロードは音声callbackで行わない。
同梱TTS枠の停止/故障は共有TTS queueを取消すが、直接VCと字幕セッションは停止しない。
共有queueのため、停止時に他のTTS枠の待機発声も取消される。この小さな制限を保持し、複数schedulerは作らない。

Realtime設定に`server`（`external|bundled`、既定external）を追加。
外部URLとmodel選択は保持し、同梱ASR選択時は現在のendpointからモデル一覧を更新する。
ASRサーバー停止/故障で接続中のmic/speaker字幕セッションと未確定配送を停止し、直接VCは維持する。
選択変更時の既存generation破棄を拡張し、古いfinal/TTSが復活しないようにする。

## GUI

音声設定へ3枠のローカルサーバー設定とStart/Stop/状態を追加する。
各枠にはモデルパス、必要なVAD/任意voiceパス、device選択を置く。saveとStartを分ける。
パス入力と案内は既存設定UIに合わせる。モデル取得ボタン・アップロード・自動ダウンロードは追加しない。
TTS各言語枠とRealtimeに外部/同梱の選択を置き、外部選択のときだけ既存URL欄を使う。
設定が未保存/起動中/停止未確認なら該当Startを無効化する。停止中は状態と固定error codeを表示する。
日本語/英語など既存5言語の翻訳資源を更新し、実装内のportやプロセス引数を通常の選択手順に持ち込まない。

## 受入れ

モデル不要: 固定引数、file/型validation、正しいtaskのhealth、起動失敗、起動中Stop、child crash、
親/owner thread/supervisor kill、古いStartの拒否、停止中の外部fallbackなし、保存復元OFF、既存external互換。
既存RVC supervisor契約とTTS/Realtime回帰も再実行する。

実モデル: 承認済みQwen/Reazon/Sileroと合成入力だけを用い、同梱版でTTS/Realtimeを確認する。
GUIでモデル設定→Start→発声/字幕→Stop→アプリ再起動OFFを確認し、外部サーバーは生存を保持する。
全GUI試験はdisplay power guard経由。物理録音・新モデル・音声の外部送信は行わない。
Linux完全インストール・fork表示/更新先・Windows・全体セキュリティ監査は後続P5のまま。
