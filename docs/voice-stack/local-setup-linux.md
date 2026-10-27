# P1 Linux / CachyOS / WiVRn

ヘッドレスCLIはWindowsのPyAudioWPatch/pycaw/windows-captureをimportしない。
Pythonは標準ライブラリだけで発声でき、`pw-cat` / `pw-dump` が必要。
VRCT全GUIのLinux互換化はP5。以下のCLI→仮想マイク→VRChat desktopの経路は、
ユーザーが内蔵マイクテストの再生で声を確認済み。途中停止後のメーター停止も確認。
実VRCTアプリからVRChatの音声・OSCへ同時配信する一連の動作、他ユーザーでの受信、HMDは未検証。
取得済みIrodori MF / speech.cpp 0.8.11の単発PoCと、0.9.0の専用PipeWireグラフでの
[30回測定](benchmarks.md)は確認済み。新規モデル取得は行っていない。

## 一時的な仮想マイク

最初にイヤホンまたはWiVRnの音声デバイスを接続し、`wpctl status`で
VRChat出力がそのデバイスへ流れていることを確認する。
`Dummy Output`しかない場合は、通常セッションにloopbackを作る前に音声出力を接続する。
今回、出力未接続で作った仮想sinkへゲーム出力が移動したため、発声せず削除した。
`priority.session=-100`やsmart filterの指定だけでは、他の出力がない状態の混線を防げなかった。

準備後、既存の音声設定を置換せず、端末で一時loopbackを起動する。
[PipeWire loopback原典](https://docs.pipewire.org/page_module_loopback.html)のsink/source構成を使う。

```sh
pw-loopback --capture-props='media.class=Audio/Sink node.name=vrct.voice.sink node.description="VRCT Voice Input" audio.position=[MONO]' --playback-props='media.class=Audio/Source node.name=vrct.voice.source node.description="VRCT Virtual Microphone" audio.position=[MONO] node.passive=true'
```

`pw-dump` / `pw-link -l` / `wpctl status` でsink/sourceが作られたことを確認。
**VRChat出力→イヤホン、VRCT出力→専用sink、専用source→VRChat入力**に分離する。
ゲーム出力が専用sinkにつながった場合は発声せずloopbackを終了し、出力先を修正する。
物理音声デバイスが切断中だと、WirePlumberがこの仮想ノードを有効な既定出力/入力に
選ぶ場合がある（今回も観測）。他アプリの出力とASR入力は明示指定し、作成前後の
`wpctl status`を確認する。VRCT自身は既定デバイスへのfallbackを行わない。
VRChatのマイクを **VRCT Virtual Microphone** に指定する。
物理マイク、ゲーム出力、WiVRn音声をこのsinkへ直接リンクしない。
終了時はloopback端末でCtrl-C。一時ノードだけが消える。
自動試験だけなら[専用PipeWire環境のCLI](benchmarks.md#反復cli)を使用する。

## speech.cpp→仮想マイク

ユーザーが許諾確認して用意済みのローカルモデルで起動（以下はパス例）。
参照音声を使わない場合は `none`。使う場合は本人同意済みのvoice.ggufを登録。

```sh
speech serve /path/to/Irodori-TTS-866M-MF-v4.1-F16.gguf --host 127.0.0.1 --port 8080
uv run --no-project python tools/voice_cli.py doctor
uv run --no-project python tools/voice_cli.py devices
uv run --no-project python tools/voice_cli.py speak --device vrct.voice.sink --language ja --text 'こんにちは'
```

CLIは`X-Sample-Rate`の実rateを[pw-cat](https://docs.pipewire.org/page_man_pw-cat_1.html)へ渡し、
必要なrate変換はPipeWireが行う。OS既定出力は使わない。
`measurement_boundary=event_to_first_pcm_write` は仮想マイク到達の測定ではない。
終了コード0はPCM出力処理の完了であり、VRChatの聞こえを保証しない。

## 手動受入とP2入口

- VRChatの[マイクテスト](https://wiki.vrchat.com/wiki/Settings#Microphone)は短い録音の後に再生する。
  テスト開始してから送信を長く待つと、録音区間から音声が外れる可能性がある。
  入力メーターが動いている間に`New Test`を押すなどしてタイミングを合わせる。
  音声送信は各要求1回。録音の`Play Again`による再生回数とは区別する。
- 停止/Ctrl-C後に入力メーターが止まるか。VRChatがすでに録音したclipの再生はVRCTの停止対象外。
- loopbackを削除→エラー、物理スピーカーへのfallbackなし。復元→明示再選択後に新しい文で再試行。
- WiVRn入力/出力を図示し、ゲーム音声・TTS monitorを将来のASR入力から除外する。
- P2外部VC: 別ソフトの入力を物理マイク、出力を**変換専用sink**へ設定して単体確認。
  生マイクの自動fallbackがない設定を確認するまでVRChatへつながない。
  VC停止時の無音、モデル/OS/版、遅延、VRAM、利用条件を記録して採用判断する。
  P1のTTS sinkへ直接混ぜる操作はP2 routerの検証後に行う。

## 常駐する管理対象の仮想マイク（B検証後の追加）

これはソースcheckout向けの任意機能。上の一時マイクとは名前が異なる。
実装・独立グラフの結果は [managed-route-report.md](managed-route-report.md) を参照。
後続の[ホスト・VRChat自動受入](managed-vrchat-report.md)で一時配置と再起動を実施し、
試験後に元の設定へ戻した。初期画面の準備と復元はエージェントが確認し、受入シーケンスを自動実行した。
VRCT全GUIのLinux対応完了を意味しない。後続の[UI部品・stdio統合試験](ui-entry-report.md)では本番入力欄・
音声設定UIと本番Main/Controllerを実TTS・独立PipeWireへ接続した。Tauri接続と周辺サービスは差し替えており、
アプリ全体の起動・設定永続化・実Model初期化は未検証。

1. systemのC compiler、pkg-config、PipeWire開発headersを用意し、repo rootでビルドする。
   CachyOSの今回の環境には既に揃っていた。Pythonパッケージや音声モデルは追加しない。

   ```sh
   uv run --no-project python tools/build_voice_gate.py
   ```

2. 実音声が中断してよいタイミングで、設定をユーザーのPipeWire設定へ配置する。
   この再起動はVRChat/WiVRnを含む音声接続を中断する。
   他の設定は置換しない。既に同名ファイルがある場合は内容を確認してから置換する。

   ```sh
   mkdir -p ~/.config/pipewire/pipewire.conf.d
   cp config/pipewire/90-vrct-managed.conf ~/.config/pipewire/pipewire.conf.d/90-vrct-managed.conf
   systemctl --user restart pipewire pipewire-pulse wireplumber
   ```

3. イヤホンなどの実出力を接続した状態で `wpctl status` / `pw-link -l` を確認する。
   ゲーム音声はイヤホンへ、TTS出力は `vrct.managed.tts`、VC出力は `vrct.managed.vc` へ、
   VRChatの入力は **VRCT Managed Virtual Microphone** (`vrct.managed.source`) へ明示指定する。
   `priority.session=-100` はOS全体のdefault選択を禁止する設定ではない。実出力が消えた場合などの
   自動選択は別途確認が必要で、既定出力にこのsinkを選ばない。
4. VRCTの読み上げ設定で「管理対象の仮想マイク（Linux）」を保存する。
   初期状態はミュート。「音声を再開」で確認済みになるまで出力しない。
   「再開するまでミュート」はこの経路に入ったTTS/VCを止める。
   既存の「停止」はTTSだけを取り消す。外部ケーブルモードの保持ミュートもTTSだけに適用する。
   外部ケーブルの選択値はmanagedへ切り替えても保存される。
5. `voice_mute_state.json` はアプリの `config.json` と同じディレクトリに作られる。
   破損や書込み失敗はエラーとミュート要求として扱い、成功表示しない。
   書込み可能な状態へ修復後にミュートを要求し、確認されてから再開する。

VRCT停止中の診断だけなら、同じstate fileを明示してCLIを使える。
CLIは一回の操作だけで、切断監視を継続しない。起動中のVRCTは外部からの状態変更を検出すると
ミュートへ戻すため、通常操作にはUIを使う。

```sh
uv run --no-project python tools/voice_route.py status --state-file /path/to/voice_mute_state.json
uv run --no-project python tools/voice_route.py mute --state-file /path/to/voice_mute_state.json
uv run --no-project python tools/voice_route.py resume --state-file /path/to/voice_mute_state.json
```

戻すには、まずミュート確認後にVRCTを外部ケーブル設定へ戻し、VRChatで安全な入力を選び直す。
配置した `~/.config/pipewire/pipewire.conf.d/90-vrct-managed.conf` **だけ**を削除し、
音声を中断してよいタイミングで上記userサービスを再起動する。アプリ側の保持ミュートは
残るため、必要なら明示再開する。任意のPipeWire設定ディレクトリ全体は削除しない。

通常のVRCT終了ではgateをミュートしてendpointを残す。SIGKILLや電源断で終了処理が走らない
場合はgateの直前の状態が残る。解除中のVRCT強制終了だけでは外部VCの音は止まらない。
VRCT再起動時は再度ミュートする。PipeWire daemon停止では仮想マイクも消えるため、
その際のVRChat入力fallbackは引き続き実機確認が必要。
