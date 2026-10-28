# P2 RVC統合 — モデル不要実装と検証

2026-10-29。ユーザー指示により、RVCモデルを取得せずP2の統合・自動試験を先行した。
**GUI・外部worker・共通音声経路を実装済み。実RVCモデルの変換成功を確認した段階ではない。**
既存Seed-VCの間欠停止原因は未特定のまま残す。

## Seed-VCとの機能差

| 項目 | 今回のSeed-VC経路 | 今回のRVC経路 |
|---|---|---|
| 変換先の声 | 利用許可のある短い参照音声 | 利用許可のある話者学習済み`.pth` |
| 話者ごとの追加学習 | 参照音声によるzero-shotで不要 | 手持ちの学習済みモデルを使うなら不要。新たな声のモデル作成には別途学習が必要 |
| 補助データ | 参照音声とSeed基礎モデル | HuBERT/RMVPEと任意の検索`.index` |
| 今回のGUI操作 | runtime・参照WAV | runtime・モデル・index・半音ピッチ・検索混合率 |
| 翻訳 | 行わない | 行わない |
| エンジン由来コード | GPL-3.0-only | MIT。モデルと依存の条件は別 |
| 音質・遅延の比較 | 実Seedの限定PoCはある | 実モデル未導入。同条件比較はまだできない |

一次資料: [Seed-VC](https://github.com/Plachtaa/seed-vc)、
[RVC固定README](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8f68b6bed1789f682fe78cdd324495afc/docs/en/README.en.md)。
Seed upstreamの全モデル・学習機能を、このリアルタイム統合が提供するとは主張しない。

## 実装範囲

設定→高度な設定→テキスト発声（speech.cpp）内の直接音声設定で、原音／変換を選び、
変換時にSeed-VC／RVCを選択する。RVCはモデル、任意index、ピッチ（-24〜24半音）、
検索混合率（0〜1）を保存できる。保存・再起動で自動開始しない。実行中は変更できない。
旧Seed設定・旧Start要求は互換。ASR・OSC・TTSの選択とは独立している。

`VCProcess`へcapture・有界queue・停止・出力寿命を共通化。RVC専用workerを固定moduleとして
native supervisorから起動する。creator thread/親/supervisorの終了でworkerを停止する。
48 kHz mono、80 ms block、未送信block 1個、block終了後160 msを超えた出力の拒否を維持する。
これは設定された期限であり、入力→VRChatの実測遅延ではない。失敗しても原音へ切り替えない。

RVC workerは固定原典の推論APIを呼び、resamplingとSOLAを処理する。RMVPE、speaker 0、formant 0を
初期対象とし、v1/v2・32/40/48 kHzを検証する。基礎モデルはlocal-only、checkpointはweights-only。
不完全な重み・部分初期化・要求した検索処理の失敗を成功扱いしない。
学習UI、VAD/denoise/RMS調整、モデル自動取得、Windows実装はこの追加の対象外。

[設計](../superpowers/specs/2026-10-29-rvc-integration-design.md)、
[計画](../superpowers/plans/2026-10-29-rvc-integration.md)、
[外部runtime配置と制約](../../integrations/rvc/README.md)。

## 試験結果

| 検証 | 結果 | 証明する範囲 |
|---|---|---|
| 標準pytest | 1,222 PASS / 6 SKIP / 46既存警告（14.15秒） | 既存機能の回帰 |
| 音声全体（ブラウザー・既存実ASRを有効） | 753 PASS / 9 SKIP / 2警告（73.54秒） | 音声契約・制御・GUI。RVC/Seedの任意ML試験等は別 |
| 任意Torch環境でRVCモデル不要試験 | 22 PASS（1.32秒、レビュー修正後） | 実resampling/SOLA、fake推論、実worker pipe、原典の例外経路、local検証 |
| RVC GUI実ブラウザー | 1 PASS（2.13秒、上記音声全体にも含む） | 選択・数値範囲・保存復元・明示Start/Stop・実行中変更禁止 |
| 私有PipeWire＋模擬RVC worker | 2 PASS（14.41秒） | 合成音→固定supervisor→共通経路→仮想マイク。停止/worker強制終了後の2秒無音 |
| Vite/native helper/Tauri debug build | PASS | UI生成、固定RVC起動分岐、Linux開発バイナリのビルド |

Torch試験は既存Seed用interpreterを再利用し、RVC推論はfake。RVC用依存環境の検証ではない。
私有PipeWire試験もfake workerであり、実話者変換・物理マイク・VRChat・聴感・性能を証明しない。
[native測定記録](rvc-model-free-native-results.json)は明示的に`real_rvc=false`。
標準試験の警告には既存telemetry coroutine・依存deprecated警告を含む。

再現:

```sh
UV_CACHE_DIR=/tmp/vrct-uv-cache unshare --user --map-root-user --net sh -c \
  'ip link set lo up; uv run --no-project --python .venv_linux/bin/python python -m pytest -q'
unshare --user --map-root-user --net sh tmp/voice-resume/run-realtime-voice-regression.sh
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --offline --no-project --with pytest==8.4.2 \
  --python tmp/voice-resume/seed-vc-poc/venv/bin/python \
  python -m pytest tests/voice/test_rvc_worker.py tests/voice/test_rvc_runtime.py -q
UV_CACHE_DIR=/tmp/vrct-uv-cache VRCT_TEST_RVC_ROUTE=1 unshare --user --map-root-user --net sh -c \
  'ip link set lo up; uv run --no-project --python .venv_linux/bin/python python -m pytest tests/platform/test_native_rvc_model_free.py -q'
```

実行ログは`/tmp/rvc-*.log`、raw native記録は`tmp/voice-resume/rvc-native-model-free/`。
公開前にprivate scratch runnerへ依存する手順を配布用手順へ整理する必要がある。

## 独立レビュー

ユーザー承認済みのP2コード・仕様・差分だけを、standalone Codex CLIのread-only packetへ渡した。
AIT子→親通知を使わず正常終了。音声・モデル・認証情報は資料に含めていない。
raw報告: `tmp/voice-resume/rvc-independent-review.md`。

Important 1件: FAISS検索成功後の特徴量変換/混合で例外が起きても、原典が例外を表示して
未混合のまま推論を続け得る。検索成功カウンタだけでは検出できない。
固定`infer/rtrvc.py`のretrieval節そのものをテストfixtureに保存し、`torch.from_numpy`を失敗させて
「例外が伝播しない」REDを再現。原典moduleだけの`traceback.print_exc`境界をエラー化し、
必ずworkerを失敗終了させる修正でGREEN。Python全体のtracebackは変更しない。
これは固定版内部へのadapterなので、原典更新時はhookとfixtureも再照合する。
独立レビューは修正前の1回で、修正後は回帰テストによる確認。

## 次の実モデル試験の候補と条件

公式READMEが指定する基礎モデル置き場は
[`lj1995/VoiceConversionWebUI`](https://huggingface.co/lj1995/VoiceConversionWebUI)。
モデルカードはMIT表示、本文は空。metadataだけを読み、固定revision
`e6d0c1a17da07c33557852f9dfa2bd44cc75737d`のHuBERT 3ファイル＋RMVPEを候補とした。
合計 **370,392,700 bytes（約370.4 MB）**。固定hash等は
[未承認の取得候補](rvc-base-artifacts.proposal.json)に記録。重みは取得していない。

これらだけでは話者変換できず、別途、利用許諾を確認できる話者`.pth`が必要。
同repoの`weights/白菜357k.pt`は声の利用条件とこのadapterへの適合を確認できていないため、
自動採用しない。取得時には対象ファイル・固定版・サイズ・条件を提示して同意を得る。
実runtimeはuvで分離し、依存lockとoffline smokeを完成させてからnative実変換へ進む。
性能はモデル単体の処理時間とcapture→仮想出力/VRChatを別に測り、p50/p95、欠落、VRAM、
ASR/TTS/VRChat併用負荷、長時間、聴感、Windowsを個別に受け入れる。

上流連絡・PR・push・公開は行っていない。P2全体および予定全機能の完成宣言ではない。
