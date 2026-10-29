# Mia2026: 実RVCのローカル検証

2026-10-29。ユーザー提供の`Mia2026.zip`で、**実モデル変換、固定worker、私有PipeWire、60秒連続動作、実Tauri GUIを確認した**。
モデル・index・同梱文書・画像・変換音声は配布しない。ユーザーの「このツールにはバンドルしない」を継続条件とする。
P2全体の受入完了ではなく、物理マイク→VRChat・聴感・長時間/混在負荷・Windowsは未確認。

## 入力と許諾の境界

- ユーザー提供ZIP: `/home/kei/Downloads/Mia2026.zip`。`.pth` 57,589,683 bytes、`.index` 31,588,619 bytes。
- `torch.load(weights_only=True)`でv2・48 kHz・f0ありを確認。公式固定実装と同じspeaker 0、formant 0、pitch 0で試験。
- ZIP同梱の「RVC girls RVC音声変換モデル 共通利用規約」v1.0（2026-09-04）を読み、リアルタイムVC/VRChat用途と、モデル・index等の再配布禁止を確認。今回の検証許可を、モデルの公開・同梱・共有サービスへの許可に拡張しない。
- 変換元は以前から使用している4.88秒の合成日本語試験音声。新しい物理マイク録音はしていない。
- 基礎モデルHuBERT 3ファイル＋RMVPE 1ファイルは、今回ユーザーが明示承認。固定revisionとサイズ/hashを照合し、合計370,392,700 bytesを取得した。[固定manifest](rvc-base-artifacts.proposal.json)。

ローカル保存先は`tmp/voice-resume/rvc-mia-poc/`。`private-model/`は0700、モデル/index/termsは0600、Git ignore対象。
画像は不要なので展開していない。元ZIPは変更していない。private manifestにモデル/規約のSHA-256を記録した。
変換音声も同じignored領域に0600で保存し、音声・重みを外部レビューやサービスへ送っていない。

誤同梱対策として、CPU/CUDA両PyInstaller specのTOCから`Mia2026.pth/.index/.zip/.png`を除外し、
配布guardでも同名ファイル（大小文字を区別しない）を拒否する。名前変更された任意のモデルを検出する仕組みではない。
private領域を配布元へコピーしないことと併用する。モデル名は利用事実の説明にだけ使用する。

## 実行環境と再現性

| 項目 | 検証値 |
|---|---|
| GPU / driver | RTX 4080 SUPER / 615.78.08 |
| Python | uv専用venv、3.12.14 |
| Torch / torchaudio | 2.7.1+cu118 / 2.7.1+cu118 |
| RVC source | `81eed5e8f68b6bed1789f682fe78cdd324495afc`、変更なし |
| 本体処理 | CUDA、FP16、CUDA graphs OFF、RMVPE |
| 既存プロトコル | 48 kHz mono S16、80 ms/block、block終了後160 msの鮮度上限 |
| streaming | 40 ms SOLA overlap、10 ms search、2 s左履歴 |

`integrations/rvc/requirements-cuda.lock`と`requirements.lock`はハッシュ付き。
実環境へのoffline再適用でそれぞれ23/39 packagesが一致した。`requirements.freeze.txt`も保存。
既存アプリのPython環境は変更していない。最小推論依存だけを導入し、RVCのGUI/学習依存は導入していない。
導入済みwheel metadataで`praat-parselmouth 0.4.6`はGPLv3と確認した。RVC本体のMIT表示だけで
実行環境全体の配布条件が決まるとは扱わない。runtimeの最終配布監査はP5に残る。

最初のsandbox内`nvidia-smi`はGPUへ接続できなかったが、権限外の読み取り確認では正常だった。
ドライバー故障ではなく、sandboxからのアクセス差として切り分けた。GPU使用量は試験開始前に3,378 MiB、利用率28%。
ほかのGPU負荷を停止・固定した比較試験ではないので、数値からSeedとの優劣は判断しない。

## 成功した実機試験

| 試験 | 結果 | 範囲 |
|---|---|---|
| エンジン単体 | index 0 / 0.5とも61 blocks、4.88秒の有限・非ゼロPCMを生成 | 実モデル、resampling、SOLA。聴感の保証ではない |
| 本番worker pipe | 61 blocks成功、準備完了まで約3.45秒 | 本番workerの既定thread設定、80 ms間隔の入力 |
| 私有PipeWire | 4 PASS、43.26秒 | indexあり/なし × 通常Stop/worker強制終了。元入力継続中も停止後2秒無音 |
| 60秒連続 | 1 PASS、70.63秒（準備/停止確認を含む） | index 0.5、761 blocks、期限超過・worker停止なし、observerの100 ms超read gapなし |
| 本番Tauri GUI | 1 PASS、25.22秒 | RVC選択/保存→実変換→私有仮想マイク、global mute、明示Stop、再起動時の設定保持とcapture OFF |
| 新RVC環境のモデル不要試験 | 22 PASS、1.62秒 | Tensor/worker/原典例外/ローカルファイル検証 |
| 配布除外 | RED 6失敗→GREEN 8 PASS | 両specのTOC、directory/ZIP/直接ファイルの誤同梱拒否。偽データだけを使用 |
| 最終回帰 | 標準1,222 PASS / 6 SKIP / 46既存警告、音声757 PASS / 9 SKIP / 2警告 | 14.45秒/75.78秒。任意RVC Tensor試験は上記の別venvで実行 |
| 最終ビルド | Vite / Tauri debug PASS | Linux開発バイナリ。モデルを含む配布パッケージは作成していない |

native GUIはDPMS消灯防止ガードを使用し、ユーザーの普段のconfigとは別のテスト設定で起動した。
native試験はホストVRChatの音声経路に接続していない。再生したのは私有PipeWire内の合成入力だけ。

## 性能測定の境界

**A: エンジン単体（capture/OS/VRChatを除外）。** `BlockSession.convert`の前後でCUDA同期を取り、
resampling・特徴抽出・検索・pitch・合成・SOLAを含むwall timeを計測。試験scriptはCPU threadsを1に設定。
各条件61 blocks、先頭3 blocksを除く58 blocksでwarm分布を計算した。

| index混合率 | 初回block | warm p50 | warm p95 | warm最大 |
|---|---:|---:|---:|---:|
| 0 | 226.57 ms | 17.36 ms | 19.32 ms | 20.46 ms |
| 0.5 | 297.75 ms | 16.90 ms | 33.99 ms | 42.27 ms |

初回loadは条件ごとに10.65秒/2.26秒で、ファイルcache等の条件が異なる。GPU最大allocatedは約467.47 MiB。
これはTorch allocatorの値で、プロセス全VRAMやVRChat込みの使用量ではない。

**B: 連続OS経路（本番worker既定設定）。** 入力block終了のソフトウェアtimestamp→OS出力write成功。
60秒の761 blocksで **p50 69.38 ms / p95 69.84 ms / p99 70.04 ms / 最大75.04 ms**。
80 ms blockを溜める時間、ハードウェアADC、音響的な発話位置のずれ、OS出力後の消費、VRChatを含まない。
この値を「マイク→VRChatが約70 ms」と読み替えない。短い4試験では同じ境界のp50が約32〜37 msで、
実行条件による差もある。分布は`numpy.percentile`のlinear方式。

**C: Stop→私有monitorが無音になるread。** native GUIの1回は81.39 ms、連続試験の1回は19.61 ms。
read完了timestampを用いた単発値であり、Stop応答時間のp95ではない。いずれもその後2秒無音を確認。
observerのread gapがないことだけで、音声内容の欠落が一切ないとは判断しない。

[集計JSON](rvc-mia-validation-results.json)。生の数値ログはignored検証領域内。

## 再現手順と残件

runtime作成は[README](../../integrations/rvc/README.md)の2段階uv手順を使う。
モデル取得・利用の同意がある環境だけで、次の変数をローカルファイルへ設定する。

```sh
export VRCT_RVC_RUNTIME=/absolute/path/to/runtime
export VRCT_RVC_MODEL=/absolute/path/to/permitted.pth
export VRCT_RVC_INDEX=/absolute/path/to/matching.index
export VRCT_RVC_INPUT=/absolute/path/to/synthetic-48k-mono-s16.wav
export VRCT_TEST_LIVE_RVC=1
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python \
  python -m pytest tests/platform/test_native_rvc_worker.py -q
# 60秒連続: VRCT_RVC_RUN_SECONDS=60、-k 'stop and 0.5'
# native GUI: VRCT_TEST_NATIVE_RVC_UI=1 を設定し、消灯防止guard経由で
# tests/platform/test_native_rvc_ui.py を実行する。
```

Windows、実マイク→VRChat、聴感、30分以上、制御したGPU競合、実ASR/TTS併用は残件。
このRVC成功を、未特定のSeed-VC間欠停止が解消した証拠にはしない。
モデルを含む配布・公開・upstream連絡/PRは実行していない。
