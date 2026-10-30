# 仮想マイクの維持と全体ミュート

依頼者はB検証後の手順1（仮想マイクをTTS/VCから独立させ、全体muteを明示解除まで保持）を実装するよう指定した。既存worktreeで実行し、Pythonはuv、モデル不要。手順2のVRChat GUI試験は今回の実装と分ける。computer-useスキル／操作ツールは現在のセッションで見つからなかった。

## 構成

LinuxはPipeWire daemon設定に3個のloopbackを置く。最終sink/source、TTS用sink→最終sink、VC用sink→最終sink。Pythonや推論プロセスの終了でノードを削除しない。daemon自体の終了では消えるので、VRChat consumerのfallback問題を解決済みとはしない。

最終sourceは `node.param.Props={mute=true}` と `state.restore-props=false` で生成し、再生成でもmuteを初期値とする。独立graphで既に起動時Props.mute=trueとpw-cliによる名前指定変更を確認した。音声処理processは追加しない。制御専用の小さなC helperを既存のsystem libpipewire-0.3でビルドし、同一接続内でcookie/serial/属性を検証したbound proxyにのみmuteを設定する。子process所有では終了時消失し、常駐する独自audio processは今回不要なので採らない。

名前は `vrct.managed.mix` / `vrct.managed.source` / `vrct.managed.tts` / `vrct.managed.vc`。通常defaultを指定せず、経路はexplicit target＋dont-fallback/reconnect。config artifactと導入手順を提供し、実機検証は独立PipeWireで行う。稼働中desktopのPipeWire再起動は今回の自動試験に含めない。

## 制御

VoiceSettingsに `routing=external|managed`（default external）を追加。既存の任意outputはexternalのまま互換維持。managedはLinuxのみ、outputは固定TTS sink。選択時はmute状態から開始する。

VoiceEventBusに独立したmute latchを追加。muteは世代を失効、active取消、queue破棄、新規publish拒否。configure/stop_voiceはlatchを解除しない。明示resumeだけが解除する。Controllerは専用 `voice_mute_state.json` をatomic replace＋fsyncで保存し、アプリ再起動でも保持。managed経路はアプリ起動ごとにmuteから開始する。

小さなVoiceRoute制御workerがOS I/Oを所有する。既存receiverの優先経路ではmute要求とソフトウェア取消だけを行い、OS確認前の応答はpending。statusはdesired muteと観測済みmuteを区別し、制御失敗を成功表示しない。resumeは明示要求・現在の正常なidentityが必要。cookie/serial変更や欠落・I/O失敗はmuteへ戻し、新しいresumeが必要。stale resumeの完了でbusを解除しない。OS操作は固定node.nameを列挙後、cookie/serialを検証したproxyを使い、変更時に名前や数値IDを引き直さない。

managed解除は先にOS muteを確認し、latchは残す。外部経路のTTSは明示再開で解除可能。shutdownではmuteするがdaemon所有のendpointを削除しない。外部アプリがgateを直接変更することやdaemon停止中のVRChatの選択までは制御できない。

## UI/API

`/get/data/voice_route`、`/run/mute_voice`、`/run/resume_voice`。後2つは優先受付し、返却status内のpendingを表示。既存stop_voiceはTTS単独取消のまま。UIはmanaged経路の選択、全体mute/明示再開、準備待ち・エラー・確認済みmuteを表示する。external時はTTSのmute保持として表示し、他アプリの音声まで止めたと表示しない。日本語/英語を追加し既存fallbackを使う。

## 試験と限界

TDDでmute保持・設定変更・再起動初期値・cancel後新規発話・古い世代・古いresume・欠測/command失敗を検証。fake backendと実bus/Controllerを使い、独立PipeWireでは配布configを読み込ませて初期mute、engine終了後のidentity維持、制御worker再作成、global mute中の新TTS、明示再開、daemon再起動初期muteを合成音で確認する。30反復の停止時間と2秒無音を報告する。

実VC、Windows OS gate、VRChat GUI、HMD、実音声品質は未検証。既存一般Python suiteの依存不足による80 collection errorsは既知で、モデル不要suiteと区別する。外部モデル・pip依存追加なし。Linux helperのビルドにはC compiler・pkg-config・PipeWire開発headersが必要。ライセンス条件をprocess境界から推定しない。

## 根拠

- docs/voice-stack/b-validation-report.md、ADR004
- https://docs.pipewire.org/page_module_loopback.html
- https://docs.pipewire.org/page_man_pipewire_conf_5.html
- https://docs.pipewire.org/page_man_pw-cli_1.html （pw-cliのload-moduleはCLI自身のlocal instanceであり、daemon常駐化には使わない）
- https://raw.githubusercontent.com/PipeWire/pipewire/master/src/tools/pw-cli.c （名前で検索・proxyにset-param、実機1.6.10でも確認）
