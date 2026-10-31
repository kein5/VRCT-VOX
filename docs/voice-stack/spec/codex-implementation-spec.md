# VRCT-VOX — 低遅延音声統合 実装仕様書

作成日: 2026-10-27 / 対象リポジトリ: https://github.com/kein5/VRCT-VOX
基準: `develop` / commit `79419a1f2ce78d38993b0f33e273155667eb0b6a`（調査時点で upstream `misyaguziya/VRCT` の `develop` と同一）
関連実装: [speech.cpp](https://github.com/nyosegawa/speech.cpp)、[VRCT-TTS](https://github.com/misyaguziya/VRCT-TTS)
調査方法: [imozuru](https://github.com/MaryCache/imozuru) の「問い→2方向の探索→一次資料と関連実装をたどる→各論点の根拠確認→判断」を適用。根拠の所在と残課題は別紙 `imozuru-evidence-map.md` を参照。

> この文書は **Codexに渡して実装させる仕様書**。既存コードに確認できた事実と、これから作る設計・目標値を分けて記す。機能やAPIの存在を仮定しない。以下のパスは原則フォークの`develop`相対パス。

## 0. ゴール・前提・非目標

### ゴール

**VRCTを壊さずに、VRChatで次の体験を実現する。**

1. **テキスト発声**: VRCTのテキスト欄に入力して送信すると、OSC Chatbox表示と並行して選択した声でTTS発声し、VRChatのボイスチャットへ流れる。原文／翻訳文／無音送信を選べる。
2. **直接ボイスチェンジ**: マイクから喋った声をSTT/翻訳/TTSの完了を待たずに別の声へ変換し、VRChatに出せる。普通の直接音声チャットで利用可能。
3. **逐次文字起こし＋字幕翻訳**: 自分のマイク、VRChat音声の受信経路をそれぞれASRし、暫定字幕と確定字幕、翻訳文をVRCTオーバーレイに表示する。
4. **音声翻訳・再発声**: 自分の発話をASR→既存VRCT翻訳→TTSして相手に音声として伝えられる。文字起こし結果・翻訳をOSC Chatboxにも出すか選べる。
5. **併用**: 直接ボイチェン、字幕、TTSを同時に使っても競合・二重発声・エコー・誤投稿が起きない。マイク経路は翻訳経路の遅延に影響されない。
6. **ローカル優先・複数OS**: 完全ローカル動作を基本に、まず現行VRCTが最も安定するWindowsでE2E完成させ、その後Linux/PipeWire対応を独立した段階として進める。クラウド翻訳は既存設定を維持し、ユーザー選択なしに音声を外部送信しない。

### 非目標（今回のスコープ外）

- VRCT本体を全面的にC++へ書き換えない。
- `speech.cpp`に存在しない生音声→生音声Voice Conversionを実装済みとして扱わない。
- 既存VRCT翻訳器を独自LLMへ置き換えない。既存のクラウド/ローカルプロバイダを使う。
- VRChat純正Chatboxが送信した任意の文字列をOSC経由で読み戻せると仮定しない。自分のVRCT入力欄の送信文は取得できる。
- 配布物へ学習済みVCモデルや他人の声データ、VRCT制限付きOCRモデルを無断同梱しない。
- macOS版、Quest単体版、フル自動エンドユーザーインストーラーは初回MVP対象外。

## 1. 調査で確定した既存構造

- **VRCT**: Tauri 2/React（`src-ui/`, `src-tauri/`）＋Pythonサイドカー（`src-python/`）。現行の`package.json`は`3.6.0-beta.1`。パッケージングはWindows NSIS、PythonはPyAudioWPatchやWindowsキャプチャ系を使用。Linuxは別の互換作業が必要。
- **統合ポイント**: `src-python/models/message_pipeline.py`に `MIC_MESSAGE_SPEC` / `SPEAKER_MESSAGE_SPEC` / `CHAT_MESSAGE_SPEC` / `OCR_MESSAGE_SPEC`があり、`src-python/controller.py`の`_processMessage`が翻訳、OSC、UI、WebSocket、履歴へ配信する。**この共通処理を壊さず、非同期音声イベントのフックを追加する**。
- **WebSocket**: `src-python/models/websocket/websocket_server.py`に外部連携用配信とトークン検証がある。既存のVRCT-TTSはこのプロトコルで`SENT`/`CHAT`/`RECEIVED`の原文・訳文を読み上げる。後方互換を保つ。
- **既存ASR**: `src-python/models/transcription/transcription_transcriber.py`は確定フレーズ/累積バッファの認識に基づく。新しいOpenAI互換STTは`transcription_providers.py`のRESTクライアント。`temperature=0.0`等を付けるため、speech.cppへの単純な`base_url`置換では拒否され得る。**speech.cpp専用adapterを用意する**。
- **speech.cpp**: OpenAI互換 `POST /v1/audio/speech` （`pcm`ストリーム、`X-Sample-Rate`を返す）と `POST /v1/audio/transcriptions`、WebSocket `ws://127.0.0.1:8080/v1/realtime`（文字起こしセッション）。TTSはIrodori-TTS / Qwen3-TTS、ASRはQwen3-ASR / Parakeet / ReazonSpeech、VADはSileroに対応。**翻訳・VCは行わない**。
- **VCエンジン**: w-okada VCClientの現行版はOS・エディション別の対応モデルが異なる。Linux x86-64標準はBeatriceが中心、Windows CUDA/ONNXはRVC対応。Seed-VC RealtimeはWindows/Linux対応だが、測定例は430～690msで超低遅延確約はできず、コードはGPL-3.0。後述の選定ゲートを必須とする。

## 2. システム境界・データフロー

```text
                          ┌─────────────────────────┐
   VRCTテキスト入力 ───────→│  VRCT Message Pipeline │ ──→ VRChat OSC Chatbox
                          │  既存翻訳/字幕/配信維持  │
                          └────────────┬────────────┘
                                       │ 確定メッセージ
                                       ▼
                              TTS Request Scheduler
                                       │
                              speech.cpp (TTS)
                                       │ PCM stream
                                       ▼
                               Audio Output Router ─────────┐
                                                             │
  物理マイク ──→ Capture/Fan-out ──→ VC adapter/engine ───────┤
                       │                                     │
                       └──→ speech.cpp ASR (VAD, realtime)   │
                                  │ partial/final             │
                                  ▼                           │
                            VRCT翻訳/字幕                       │
                                  │ final translated text      │
                                  └──→ TTS scheduler ─────────┤
                                                             │
                                ┌────────────────────────────┘
                                ▼
                      Virtual Microphone / OS audio
                                ▼
                       VRChat Voice Chat

  VRChat受信音声 ──→ OS別の隔離されたcapture ──→ speech.cpp ASR
                                             └──→ VRCT翻訳/字幕のみ
                                  （デフォルトで再送信・再発声しない）
```

**重要な2つの境界**

- リアルタイム音声callbackは「録音→有界バッファへのpush／再生用バッファからpull」だけ。HTTP通信、翻訳、JSON処理、モデル推論、ファイルI/O、UI更新を直接行わない。
- 入力マイクの**直接VC経路**と、**ASR→翻訳→TTS経路**を非同期で独立させる。片方が落ちても、もう片方をUI/デバイスごと停止させない。

## 3. 採用する拡張インターフェース（新規）

既存の`MessageDirectionSpec`を全面改変せず、パイプライン終端で新規 `VoiceEventBus` に変換済みイベントを渡す。実際の命名はコード規約に合わせてよい。

```python
# 擬似型。既存ファイルに実在するクラスではない。
@dataclass(frozen=True)
class SpeechMessageEvent:
    event_id: str             # 二重発声防止
    source: str               # chat | mic | speaker | ocr
    original_text: str
    translated_text: str | None
    source_language: str | None
    target_language: str | None
    utterance_id: str | None  # ASRの発話ID
    revision: int             # 暫定字幕の更新番号
    is_final: bool            # TTS/OSC投稿は基本Trueのみ
    timestamp_ns: int

@dataclass(frozen=True)
class AudioFrame:
    pcm: bytes                # s16leを基本とし入出力境界で形式を明記
    sample_rate: int
    channels: int
    captured_ns: int
    stream_id: str
```

- `SpeechRecognitionProvider`: `start()` / `feed(AudioFrame)` / `on_partial` / `on_final` / `stop()` / `cancel()`。既存のバッチ型プロバイダとは別の**ストリーミング可能な契約**にし、legacy providerを動かし続ける。partialの確定値上書き、finalの重複抑制、発話ID紐付けを明示。
- `TTSProvider`: `synthesize_stream(text, voice, language, options, cancel_token)` がレート情報とPCMチャンクを返す。speech.cppが拒否する引数を送らない。
- `VoiceConversionProvider`: `start` / `stop` / `health` / `configure` とPCM入力/出力接続の契約。最初は**既存VCソフトが物理/仮想デバイスを扱う外部アダプター**でよい。内部RVC推論を丸ごとコピーしない。
- `AudioRouter`: `source selection`, `device enumeration`, `resample`, `virtual mic output`, `monitor`, `mute/duck`, `buffer limits`, `hotplug`, `status metrics`。プラットフォーム固有の配線を隔離する。
- 処理は非同期・非ブロッキング。有界キューを使い、過負荷時は追加遅延を無制限に溜めない。音声ルーティングと字幕キューのbackpressureポリシーを分ける。
- 既存`SENT` / `CHAT` / `RECEIVED`配信形式は変更しない。新しいイベントが必要なら**別タイプで追加**し、旧VRCT-TTS互換を守る。

## 4. 動作モードと優先順位

| モード | マイクからVRChatへ | テキスト/翻訳表示 | TTS | 備考 |
|---|---|---|---|---|
| Original / Passthrough | 生マイク | 任意 | 任意 | ユーザーの明示選択時のみ |
| Voice Conversion | 生マイク→VC | 原音の字幕翻訳を並列実行 | テキスト送信時だけ可 | **直接の会話を遮らない** |
| Translated Speech | 通常音声は抑制（設定可） | ASR→翻訳→OSC/字幕 | 翻訳文TTS | 二重発声をデフォルトで防止 |
| Text-to-Speech | 他の選択モードを維持 | VRCT送信テキスト→OSC | 原文または訳文 | 送信イベントごと最大1回 |
| Listen/Subtitle | 自分は無音でも可 | 相手の音声→ASR→翻訳字幕 | デフォルトOFF | 他人の発言を勝手に自分のOSCへ流さない |

既定は既存VRCTと同じ振る舞い（新機能は全部OFF）。VC無効／モデル未ロード／engine切断で勝手に生声へフォールバックしない（無音、明示的再選択、警告）。入力側のミュート、ゲーム側のミュート、VRCTでのミュートを取り違えない。

### OSCに関する制約

`/chatbox/input` は144文字・最大9行。送信回数・更新間隔の制限を扱う共通formatterを再利用する。部分認識をOSCへ連打しない。`/input/Voice`はVRChat内のマイク設定により「状態トグル」または「PTT風」の動作で、盲目的にON/OFFできないため**自動操作は初期版ではOFF**、以降もオプトイン＋設定検証を必須とする。VRChat内蔵Chatboxから文字列をOSC逆取得する設計は採用しない。

## 5. 音声・モデルの方針

### TTS

- 日本語のデフォルト候補: `speech.cpp irodori-tts-mf` / F16。品質優先プロファイル: `irodori-tts` / F16 / 16～40steps。最初の音声までの参考値は作者のRTX 2080 VulkanでMF 0.12秒 p50。ただしVRCT／VRChatを含むE2E値ではない。
- `speech serve`が返す`response_format=pcm`を使用し、HTTPレスポンスヘッダ `X-Sample-Rate` の値（Irodoriは通常48kHz）を実際の値として扱う。完成WAVが返るまで待たず再生する。Irodoriは文単位の生成後にPCMをストリームするため、長文でTTFAが伸びる。
- 参照音声は本人の許可を持つファイルのみ。事前に`voice.gguf`へ変換してキャッシュし、毎発話で参照音声をエンコードしない。TTSなし時にもVRCTが動く。
- 日本語以外のTTS: 別ポートの`speech serve qwen3-tts-0.6b`等に振り分ける。speech.cppの単一serveインスタンスは**タスク種別ごとにモデル最大1個**なので、同じTTSタスクでモデル併用する場合は複数プロセス/ポートを管理する。
- テキスト分割は文節・句読点を尊重。チャット入力は単発、翻訳音声は確定区間ごと。キュー重複除去／優先順位／キャンセル・タイムアウトを持つ。

### ASR / VAD

- 1段目はspeech.cpp REST(`/v1/audio/transcriptions`)で接続・精度を検証。専用アダプターは`temperature`など未サポートなパラメータを送らず、モデル名や`response_format`対応を事前チェックする。
- 2段目で `/v1/realtime` WebSocketを使い、`session.type="transcription"`, `input format=audio/pcm 24000Hz`, VAD `server_vad` を適用。サーバにSilero VADを同時ロードする。`delta`は字幕専用、`completed`だけ翻訳確定・OSC・TTSへ流す。発話IDで暫定字幕を置き換える。
- multi-languageは`qwen3-asr-0.6b`でPoC、日本語優先なら`parakeet-tdt_ctc-0.6b-ja`も比較。単一recognizerの**同時要求は直列化**されるため、mic + speakerでp95遅延増の実測が必要。悪化する場合はサーバ分離／優先度分離／speaker字幕の低優先化を比較。
- Audio captureの48kHz/44.1kHzなどから、内部処理専用の24000Hz mono s16leへ明示的にリサンプルし、ヘッダだけ変える誤処理を防ぐ。複数VAD（二重区切り）は避ける。
- 音声認識の**partialをTTSで発声しない**。確定音声の途中で取消し不可能になるため。ストリーミング字幕だけは更新可能。

### VC / ボイチェン

- speech.cppには一般的な生音声→生音声VCがない。外部の別エンジンが必要。
- 比較候補: [w-okada VCClient](https://github.com/w-okada/voice-changer) （OS・edition依存。Windows RVCをベンチ対象、Linux標準のRVC対応は**未確約**）、[Seed-VC Realtime](https://github.com/jiaheguo521/seed-vc-realtime) （Windows/Linux、Zero-shot、GPL-3.0）。Beatriceは同梱条件を別途精査。
- **選定ゲート**: ユーザーの4080 SUPER級GPUでVRChat起動中、(A)変換音声がVRChatの仮想マイクから聞こえるか、(B)計測した入力→仮想出力遅延のp50/p95、(C)途切れ、(D)品質、(E)VRAM、(F)Windows/Linux可否、(G)配布ライセンスを計測・記録。数値で比較して採用する。100～300msを**確約しない**。Seed-VCの作者報告値（430～690ms）を無視しない。
- VC engine本体とモデルをVRCT内部へ安易にコピー／混入しない。外部プロセス・音声デバイスの疎結合から始め、実証後にPCM adapterを作る。
- 原声が意図せずVRChatへ流れないよう、VC失敗時はfail-closed（無音＋警告）、ユーザーが選んだときのみpassthrough。

### Windows / Linux

- Windows初回: VRCTの既存PyAudioWPatch/WASAPIを利用する。仮想マイクとしてVB-CABLEなどを手動セットアップし、**アプリの再生先デバイス**を仮想ケーブルの入力へ、**VRChatの入力デバイス**を対応する仮想録音デバイスへ設定。変換済み音声とTTSの混合はAudioRouterで行う（外部VCの既存出力の再生先と衝突しないよう検証）。
- Linux: PipeWireのvirtual sink/source/loopbackで対応。`pw-link`や`pw-cli`、WirePlumberとの接続状態とデバイスhotplugを扱う。VRCT自体の`PyAudioWPatch`/`pycaw`/`windows-capture`等の互換化は**独立タスク**とする。最初はバックエンド／CLIでLinux E2E、後でTauri UIのLinuxパッケージへ。
- 物理マイクは用途に応じて共有captureし、VCとASRにfan-out。排他WASAPIモードに依存しない。相手の音声はゲーム出力の個別captureから取り、仮想マイクmonitorやTTSを再びASRへ送るループを防ぐ。

### Linux利用を先送りしないための早期PoCゲート

プロデューサーのVRChat主環境は**CachyOS + WiVRn + Pico 4 Ultra**なので、WindowsでUI統合を先行する場合も、Linuxのバックエンドを最終段階まで無検証にしてはならない。P0で`PipeWire仮想マイクにテストPCMを書き、VRChat側で受信する手順`を設計し、P1で**VRCT GUI非依存の小さなCLI**から`speech.cpp→PipeWire→VRChat`を実証する（手元にHMD/GPUが無ければ実証手順を作り、未検証と明記）。P2でLinuxの外部VC経路の手動スモークテストも追加。P5は**VRCT本体のLinuxネイティブUI/配布の完成**に集中する。Windows限定APIをimportしないLinuxヘッドレス起動は早くからCIで確認する。

## 6. フェーズ別タスク・完了基準

| 段階 | 実施内容 | 完了条件（客観的） |
|---|---|---|
| **P0: ベースライン＋実験設備** | forkの現行テスト/ビルド確認、声・GPU・入出力デバイス検出、speech.cpp接続疎通、音声latency harness、Windows/Linux初期可否、ライセンス一覧。`docs/voice-stack/`に設計決定ADRを書く。 | 変更前テスト結果と再現コマンド、測定フォーマット、依存バージョン、根拠付きVC選定候補が記録される。 |
| **P1: テキストTTS縦切りMVP** | `models/tts`に`speech.cpp` adapter、VoiceEventBus、`CHAT_MESSAGE_SPEC`の非同期フック、PCMプレイヤー、UIでTTS ON/OFF/原文・訳文/voice選択、VRChat virtual micへ音声送信。 | VRCTのテキスト入力を1回送信すると、OSC Chatbox表示＋仮想マイクTTS発声が**各1回**。OFFなら既存挙動完全維持。単体・E2Eテスト。 |
| **P2: 直接VC縦切りMVP** | 物理マイクcapture/VC外部adapter/音声ルーター/仮想マイク、passthrough・converted・mute切替、故障安全、device hotplug、簡易GUI。まずWindows、Linux backend検証も可能な範囲で。 | 翻訳・ASR OFFでも実マイクの声をVC経由でVRChatに流せる。VC停止時に意図せぬ生声流出なし。オンオフしてもデバイスを解放し続ける。 |
| **P3: speech.cpp STT** | 専用REST provider検証→Realtime WebSocket producer、mic/speaker別session、VADイベント、partial/final/置換、翻訳とオーバーレイの連携。 | マイクと相手音声の文字起こしが表示できる。暫定文の修正でもOSCやTTSが重複しない。既存Whisper等へいつでも戻せる。 |
| **P4: 翻訳発声の統合** | final訳文→対応TTSモデルへ、音声routerへ。優先順位、待ち行列、遅延過大時の破棄/キャンセル、VCとのduckingとdouble-talkポリシー。複数言語対応。 | マイクで日本語を発話→訳文字幕と必要なら訳文音声をVRChatに出せる。直接VC＋字幕のみとの切替ができる。ゲーム音声を誤って再送信しない。 |
| **P5: 安定化・OS対応・配布** | Windows長時間試験、Linux PipeWire backend/CLI/GUI、GPU負荷競合、ライセンス検査、パッケージ除外、マニュアル、既存リグレッション。 | Windows本番相当で30分以上、Linuxバックエンドで主要E2E、障害復帰、音声loopなし。fork独自リリースに制限付きOCRモデルを含まない。 |

**各Pで機能ブランチ／小さなレビュー可能なコミット**。P1を完了する前に一度にVC/ASR/UI大改造をしない。失敗した実測・不合格の基準は無理に突破したと報告しない。未達ならデータと切り分け方法を残す。

## 7. 推奨配置（新規。既存の同名ファイルがあれば調整）

```text
src-python/
  models/
    tts/
      speechcpp_tts.py       # REST PCM stream、声/言語、キャンセル
      tts_scheduler.py       # 送信重複防止・キュー
    transcription/
      transcription_speechcpp.py  # REST adapter
      speechcpp_realtime.py       # WebSocket、partial/final、VAD
    voice_conversion/
      provider.py            # VC抽象インターフェース
      external_vc.py         # 外部VC process/devicesの状態管理
    audio_routing/
      audio_router.py        # mix/mute/duck/fan-out
      audio_stream.py        # bounded PCM buffers/clock/resampler
      devices_windows.py     # Windows WASAPI/driver adapter
      devices_pipewire.py    # Linux PipeWire adapter
    voice_events.py         # SpeechMessageEvent, EventBus
  test/
    test_speechcpp_tts.py
    test_speechcpp_stt.py
    test_voice_events.py
    test_audio_router.py
    test_voice_conversion.py

src-ui/
  logics/voice/              # 状態/設定/metricsのfrontend連携
  views/app/...              # 既存UI規約に合わせてVoice設定パネル追加

docs/voice-stack/
  architecture.md
  decisions.md
  local-setup-windows.md
  local-setup-linux.md
  benchmarks.md
  licensing.md
  troubleshooting.md
```

- 実際のディレクトリ構造に合わせて変更可。重要なのは**層分けとテスト可能性**で、ファイル名の強制ではない。
- `src-python/config.py`、`model.py`、`controller.py`、`mainloop.py`、UIのAPIルーティングにも小さな設定/起動停止経路を追加。既存設定のデータマイグレーションと未設定初期値をテストする。
- TTSやVCの重い依存関係（torch/gguf weights）はVRCTの既存`requirements.txt`へ直接足さない。外部ランタイムをピン止め・疎結合にし、PyInstallerサイドカー肥大化やCUDA競合を避ける。
- VC候補ソフトのREST/WSの**正式な入出力仕様を読んでから**接続する。APIが無ければ外部仮想デバイスadapterでPoCする。未確認のendpointを捏造しない。

## 8. 実測・性能ゲート（すべて「目標」、達成済みではない）

| メトリクス | 仮の目標 | 計測点・注意 |
|---|---|---|
| テキスト→TTS開始 | p50 < 350ms / p95 < 800ms | UI送信イベントから仮想マイクへ最初の非無音PCMを書いた時点。温まった短い日本語文で測定。 |
| 直接VC入力→出力 | p50 < 250ms / p95 < 400msを目指す | 物理入力PCMのトリガー→仮想出力。達成不能なら現実の実測を残し、モデルを見直す。 |
| 発話終端→字幕確定 | p95 < 1.2s | VAD確定待ちを含む。partialは確定とは別に測定。 |
| 発話終端→翻訳字幕 | p95 < 2.0s | ASR finalから翻訳表示までの内訳を取る。翻訳先/エンジン別に測定。 |
| 発話終端→訳文音声開始 | p95 < 3.0sを目標 | 文章長・言語・GPU競合で大きく変動。確約しない。 |
| 長時間連続稼働 | 30分・クラッシュ0/増え続ける待ち行列0 | VRChat + VRヘッドセット + GPU負荷あり、TTS/VC/ASR同時。 |
| 復旧 | モデル/VC接続断・デバイス挿し直しでもUI操作可能 | 死んだセッションのバックオフ再接続とstop/killの時間上限を検証。 |

測定はp50/p95/p99、ウォームアップ前後、マイク・ASR・翻訳・TTS・VC・AudioRouterを分け、GPU/VRAM、FPS、サンプルレート、変換モデル、設定、OS、音声ドライバをログに残す。作者のベンチとE2Eを混同しない。音声の同意がないログ保存は避け、テレメトリーで生音声/書き起こし本文を送らない。

## 9. テスト設計・完成時の受け入れシナリオ

### 自動テスト（モデル未DLでもCIで動く）

- API mock: `/v1/audio/speech`は`pcm`チャンク＋正しい`X-Sample-Rate`を受ける。`wav`、4xx、5xx、モデル未起動、TTS取消し、切断中の例外を検証。
- Realtime ASR mock: `session.created`、`session.update`、`speech_started`、`delta`、`completed`、`failed`、`clear`、切断再接続、重複`item_id`、逆順、部分字幕の置換。
- Audio: mono/stereoと44.1/48kHz→24k/48k変換、PCMフレーム境界、ring buffer overflow、静音時無音、停止とデバイス解放。
- Modes: muted VCで生音声が漏れない、字幕のみはマイクに音を流さない、remote受信をマイクへ再送信しない、TTSの原文／訳文切替、OSC144文字・9行処理、発話ID重複抑制。
- Regression: 既存Google/Whisper/Cloud ASR、翻訳プロバイダ、OSC、VR overlay、WebSocket通知、メッセージ履歴、UI、構成読込、既存testが通る。
- CI: 外部モデル、VRChat、CUDA、仮想ケーブルなしでもunit/integration fake serverが動く。実機smokeだけ手動。

### 手動E2E（Windowsを必須、LinuxはP5のゲート）

1. マイクミュート／VC/TTS OFF→元のVRCTと同様に動作する。
2. 文字「こんにちは」をVRCT UIから送信→Chatbox表示とTTS音声が各1回。音声キューへ同文を二重投入しない。
3. VC ONで喋る→変換した音声がVRChatに届く。翻訳OFFでも動く。
4. VC ON＋STT ON→変換音声は低遅延経路、文字起こしは原音並列経路。重くても音声が無制限に遅れ続けない。
5. 翻訳発声ON→音声は訳文、字幕も訳文。直接VCが同時に流れない設定がデフォルト。相手の音声字幕は再発声しない。
6. テキスト読み上げの再生中に停止→PCM再生が即座に終了し、キューとVRChatマイク経路が残らない。
7. VCエンジン停止・speech.cpp異常終了・VRChat再起動・仮想デバイス差し直し→UIが凍らず、適切にエラー/再接続できる。
8. 英語テキスト→Irodoriへ渡さずQwen3-TTS等へ振り分けるか、「未対応」と明示する。
9. 30分混在負荷→CPU/GPU/メモリ、音声ドロップ、音声ループ、FPS低下を記録。

## 10. セキュリティ・ライセンス・配布

- `speech.cpp`の`serve`は**無認証**。デフォルト`127.0.0.1`で待ち受け、0.0.0.0公開を既定にしない。LAN接続はTLS/認証の追加なしに公開しない。VRCT既存WebSocketトークン方式を無効化しない。
- モデル取得はユーザー同意のうえ、配布元・バージョン・モデルID/ハッシュを記録。リモートコード実行を要求する不明なモデルや、許諾不明の音声モデルを自動実行しない。
- ユーザーの録音・学習・参照音声は本人または話者の同意が必要。モデルカードの音声クローン禁止用途・ディープフェイク禁止事項等を優先。
- `NOTICE.md`に従い、**`src-python/models/ocr/onnx/chatbox_yolox_tiny.onnx`をフォーク独自のビルド成果物へ同梱しない**。開発用フォークとしての実行は認められているが、独自リリース配布は別。ビルド/CIで存在検査と除外テストを加え、モデル不在時のUI機能低下を明示。
- Seed-VC RealtimeのコードはGPL-3.0。MIT VRCTに直接コピー/リンクしてよいとは即断しない。初回は別プロセスとしてユーザーが別途インストールする選択肢とし、独自バイナリ同梱・コード取り込みは法的/ライセンス条件の再確認をゲートにする。
- VCClientのBeatrice等はモデル・利用条件が異なる。OSS表記や商用可否をモデル単位で確認する。
- フォーク独自のリリースではアプリ名・バンドル識別子・publisher表示を本家の公式配布に見せかけないよう整備する。既存ライセンス・NOTICE・帰属を維持。
- 生音声・文字起こしのログ出力はデフォルト無効（必要なら一時的opt-in）。障害レポートから声・秘匿情報・APIキー・接続トークンを削除。

## 11. 推奨する実装順序とPR区切り

1. `feat(voice): establish measurement harness and architecture` — ベースライン、テスト、ADR、機能フラグ。
2. `feat(tts): add speech.cpp streaming text-to-voice` — P1のみで動く最小縦切り。
3. `feat(audio): add virtual mic routing and external voice conversion` — P2直接ボイチェン。
4. `feat(asr): add speech.cpp ASR adapter and realtime events` — P3。
5. `feat(translation): add spoken translation and routing policies` — P4。
6. `feat(platform): harden windows and add linux pipewire` — P5。

変更が大きければさらに分割。ブランチは`feature/low-latency-voice-stack`を出発点にするか、上記の小PRを順に積む。既存のテスト/ビルド失敗は「新規導入前からあるか」を証拠付きで区別する。upstreamへ自動PR・merge・releaseはしない。

## 12. Codexへの完了報告フォーマット

各フェーズの終わりに、(a)変更ファイルと設計意図、(b)動く機能、(c)テストコマンド/実際のPASS-FAIL、(d)測定値と環境、(e)未検証/未達成項目、(f)セキュリティ・ライセンス差分、(g)次フェーズの入口を短く報告する。手元にVRChatやGPUがない場合は**実機テストを完了と書かない**。fake-server integrationまで進め、必要な実機確認方法を示す。

## 13. 原典（先に参照すること）

- imozuruスキル: https://github.com/MaryCache/imozuru/blob/main/skills/imozuru/SKILL.md
- フォーク pipeline: https://github.com/kein5/VRCT-VOX/blob/develop/src-python/models/message_pipeline.py#L81-L178
- フォーク Controller: https://github.com/kein5/VRCT-VOX/blob/develop/src-python/controller.py#L967-L1215
- フォーク既存STT: https://github.com/kein5/VRCT-VOX/blob/develop/src-python/models/transcription/transcription_providers.py#L182-L250
- フォークASRパイプライン: https://github.com/kein5/VRCT-VOX/blob/develop/src-python/models/transcription/transcription_transcriber.py#L1-L30
- フォークWebSocket: https://github.com/kein5/VRCT-VOX/blob/develop/src-python/models/websocket/websocket_server.py
- フォークライセンス: https://github.com/kein5/VRCT-VOX/blob/develop/NOTICE.md#L12-L50
- VRCT-TTS: https://github.com/misyaguziya/VRCT-TTS/blob/master/README.md
- speech.cpp TTS/ASR API: https://github.com/nyosegawa/speech.cpp/blob/main/docs/server.md
- speech.cpp Irodoriモデル特性: https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/irodori-tts.md
- w-okada VCClient: https://github.com/w-okada/voice-changer/blob/master/README.md#L53-L68
- Seed-VC Realtime: https://github.com/jiaheguo521/seed-vc-realtime/blob/main/README.md
- Seed-VC license: https://github.com/jiaheguo521/seed-vc-realtime/blob/main/LICENSE
- PipeWire virtual source/loopback: https://docs.pipewire.org/page_module_loopback.html
- VRChat OSC Input/Chatbox: https://docs.vrchat.com/docs/osc-as-input-controller

