# P1 Linux / CachyOS / WiVRn

このページはソースcheckoutでの開発・CLI試験の手順。配布版のLinuxアプリは
[AppImageガイド](appimage.md)と[Linuxビルド手順](linux-build-pipeline.md)を参照。

ヘッドレスCLIはWindowsのPyAudioWPatch/pycaw/windows-captureをimportしない。
Pythonは標準ライブラリだけで発声でき、`pw-cat` / `pw-dump` が必要。
検証の記載は、2026-10-27以降の各作業時点のもの。以下のCLI→仮想マイク→VRChat desktopの経路は、
ユーザーが内蔵マイクテストの再生で声を確認済み。途中停止後のメーター停止も確認。
実VRCTアプリからVRChatの音声・OSCへ同時配信する一連の動作、他ユーザーでの受信、HMDは未検証。
取得済みIrodori MF / speech.cpp 0.8.11の単発PoCと、0.9.0の専用PipeWireグラフでの
[30回測定](benchmarks.md)は確認済み。新規モデル取得は行っていない。

## ネイティブ起動の作業状況

開発用Rust sidecarはLinuxで選択したvenvの`bin/python`を使い、UnixのexecでPythonへ置き換わる。
Tauriが所有するPIDとPythonのPIDが同じなので、wrapper終了後にPythonだけが残る状態を防ぐ。
Windowsの`Scripts/python.exe`選択とJob Objectは維持する。
実ラッパー＋小さなPythonプログラムによる11件の試験で、stdio、日本語、引数、空白path、終了コード、
終了時のprocess消失、不正venv拒否、interpreter不在・実行失敗を確認した。
別の実stdio試験で本番Main/Controller/Modelの初期化と設定保存・再起動を確認した。
Tauri画面・音声入出力はこの試験の範囲外。[継続記録](completion-ledger.md)を参照。

### 本番バックエンド用の開発環境

固定SpeechRecognition forkが使う`aifc`/`audioop`、既存NumPy/Pillowの版に合わせてPython 3.11を使う。
既存の`.venv`と`.venv_cuda`を変更せず、Linux用環境を明示選択する。確認したuvは0.13.5。

```sh
uv venv --python 3.11 .venv_linux
UV_PROJECT_ENVIRONMENT=.venv_linux uv sync --frozen --python 3.11
python tools/dev.py setup --scope sidecar
```

sidecarは `src-tauri/bin/vrct-vox-sidecar-x86_64-unknown-linux-gnu` に作られる。詳しくは[開発ガイド](../development.md#tauri開発用sidecarを準備する)を参照。

### 同梱サーバーと音声ヘルパーを用意する

開発起動のバックエンドは、同梱speech.cppサーバーと音声経路のヘルパーをソースツリーの`build/`から読む。
新しいcheckoutやworktreeには`build/`がないので、用意しないと設定の「TTS」や「音声認識」で「サーバーを起動」を押しても失敗する。

```sh
python tools/build_voice_gate.py
python tools/speechcpp_bundle.py --variant linux-x64-vulkan --archive /path/to/speech-0.10.0-linux-x64-vulkan.zip --output build/speechcpp
```

`build_voice_gate.py`は、`build/vrct-voice-gate`、`vrct-source-bridge`、`vrct-vc-worker`、`vrct-asr-capture`をビルドする。`libpipewire-0.3-dev`が必要。
`vrct-vc-worker`がないと、同梱サーバーの起動は`speech_server_launch_failed`で止まる。
`vrct-vc-worker`は推論デバイスとして、`auto`、`cpu`、`gpu`と、`speech devices`が表示するGPUの名前（`Vulkan0`など）を受け付ける。設定でGPUを名前で選ぶ機能より前にビルドしたヘルパーは名前を拒否するので、作り直す。

`speechcpp_bundle.py`は、版とSHA-256を固定した書庫から、`speech`本体と同梱のライセンス文書を`build/speechcpp`に置く。
書庫が手元になければ、`--archive`の代わりに`--download`を指定すると取得する。通信するのは`--download`を指定したときだけ。
GPUを使わない場合は`--variant linux-x64-cpu`を選ぶ。出力先がすでにあると、上書きせずに止まる。
Linux候補をビルド済みなら、`build/linux/resources/build/speechcpp`を`cp -a`でコピーしてもよい。
アプリは起動のたびに版とハッシュを検査し、シンボリックリンクは受け付けないので、リンクではなくコピーにする。
`build/speechcpp`がないか検査に合わないと、同梱サーバーの起動は`speech_bundle_missing_or_invalid`で止まる。

開発起動で取得したモデルは`src-python/downloaded_models/`に保存される。このディレクトリはgitの対象外にしてある。

Windows専用の3依存（PyAudioWPatch、windows-capture、pycaw）は`pyproject.toml`のOS markerで選択する。チャット読み取りのRapidOCRはLinuxにも入る。
`opencv-python`は`tool.uv.exclude-dependencies`で除き、同じ`cv2`を提供する2種類のOpenCVの同時導入を避ける。
Linuxのチャット読み取りは、VRChatのウィンドウをX11/XWayland経由で取り込む。Waylandネイティブのウィンドウ、VRヘッドセットの画面、従来ASRの録音、VRパネルのcaptureは未対応。
この手順はPython依存のみを取得し、ASR/TTS/VC重みの取得スクリプトは実行しない。
Pythonの取得・package通信にはネットワークが必要。システムのGTK/WebKitGTK依存は
[Tauri公式の準備手順](https://v2.tauri.app/start/prerequisites/)を参照。

起動時の`VRCT_DEV_VENV=.venv_linux`でこの環境を選択できる。
`VRCT_CONFIG_DIR=/absolute/path/to/state`はconfigとlogsだけの保存先を変える。指定しなければ従来の保存先を使う。
モデル・UI資源の場所は変えない。既存設定を試験用ディレクトリへコピーする必要はない。
「その他」のモデル自動取得は既定OFF。ONにすると次回起動時に内蔵翻訳・Whisperモデルの取得を許可する。
既存モデルはOFFでも検査・再利用され、ユーザーが明示的に使うモデル取得操作も維持する。

本番バックエンドの自動試験:

```sh
VRCT_TEST_NATIVE=1 uv run --no-project --python .venv_linux/bin/python -m pytest -q tests/platform/test_native_backend.py
```

試験は新規設定でテレメトリ、録音、自動デバイス選択、OSC送信をOFFにする。実サービスを差し替えず初期化し、
日本語の音声設定を保存、shutdown後に再起動して復元と音声OFFを確認する。
HTTPモデル取得の条件自体はネットワーク状態を注入した別の単体試験で検証する。

## RVCとSeed-VCの実行環境

Linux（x86-64）でも、RVCとSeed-VCの実行環境をアプリから取得できます。画面と流れはWindowsと同じです。「設定」→「RVC」、または「高度な設定」の「入力音声の転送」に、「RVCの実行環境」「Seed-VCの実行環境」の欄があります。「取得内容を確認」を押し、ライセンス、サイズ、保存先を確認して同意すると始まります。同意するまで、何も取得しません。

必要なものは次のとおりです。

- NVIDIAのGPUと、NVIDIAのドライバー。アプリは`/proc/driver/nvidia/version`があるかどうかで、ドライバーが動いているかを確かめます。nouveauなど、このファイルがない環境では「取得内容を確認」を押せません。Torchはアプリに読み込みません。
- x86-64のPC。それ以外では、取得の欄を表示しません。

同意すると、次を順に行います。Gitも開発環境もいりません。

1. 固定版の`uv`を取得します。公式リリースの`uv-x86_64-unknown-linux-gnu.tar.gz`で、サイズとSHA-256を照合します。
2. Pythonと、ハッシュを固定した依存を入れます。RVCは`integrations/rvc/requirements-cuda.lock`と`requirements.lock`、Seed-VCは`integrations/seed_vc/requirements.lock`を使います。
3. エンジン本体を取得して、内容を検証します。Seed-VCには同梱のパッチを当てます。
4. 基礎モデルを取得して、ハッシュを検証します。
5. 実行環境のPythonで`torch.cuda.is_available()`を確かめます。

| | RVC | Seed-VC |
|---|---|---|
| 通信量の目安 | 約4.9 GB | 約6.4 GB |
| 必要な空き容量 | 約16 GB | 約18 GB |
| 完了後の大きさ | 約8.0 GB | 約9.5 GB |
| 依存のPython | 3.12 | 3.11 |

この表は、2026-11-11に1台のPCで1回ずつ取得して測った値です（CachyOS、RTX 4080 SUPER、NVIDIAドライバー620.70.06、btrfs、有線の回線）。通信量は、取得中にネットワーク機器が受信したバイト数です（RVCは4.83 GB、Seed-VCは6.28 GB）。必要な空き容量は、取得中のフォルダーの大きさ（`du -sb`）の最大値を切り上げた値で、RVCは15.6 GB、Seed-VCは17.5 GBでした。`uv`のキャッシュと導入先を別々に数えています。`uv`は、ファイルシステムが対応していれば両者でデータを共有するので（reflinkまたはハードリンク）、その場合に実際に使う容量はこれより小さくなります。かかった時間はRVCが62秒、Seed-VCが139秒ですが、回線の速さで大きく変わります。

保存先は、`config.json`と同じフォルダーの`vc_runtimes`です。配布版では`~/.config/vrct-vox/vc_runtimes`、ソースからの開発起動では`src-python/vc_runtimes`になります（gitの対象外です）。途中で失敗したり中止したりしても、終わった手順は次回に飛ばします。中止すると、`uv`と、`uv`が起動したプロセスをまとめて止めます。アプリが異常終了したときも、`uv`は一緒に終わります。終わったら「この実行環境を使う」を押して保存します。消したいときは、このフォルダーを削除します。

声のモデルは別です。RVCの設定画面の取得欄から取得するか、権利を確認したものを指定します。Seed-VCには、利用が許可された参照音声（1〜30秒のWAV）を指定します。

確認できたのは、上のPCでの取得と、取得した実行環境でRVCとSeed-VCのワーカーを起動して、合成した音声を変換するところまでです。音質、ほかのディストリビューション、配布版（AppImage）からの取得は確かめていません。

手動で用意する場合は、[RVCのREADME](../../integrations/rvc/README.md)と[Seed-VCのREADME](../../integrations/seed_vc/README.md)の手順を使います。

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
