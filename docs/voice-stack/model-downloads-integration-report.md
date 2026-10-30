# モデル取得の実機検証（2026-10-30）

これは[モデル取得機能](model-downloads.md)の担当単体・ブラウザ試験とは別に、親担当が実ネットワーク・実AppImage・GPUで行った記録。途中の候補と最終検証版を区別する。

## 固定3モデル版のAppImage

`build/tts-model-downloads-2026-10-30-artifacts/VRCT-TTS-3.6.0-beta.1-linux-x64-vulkan-release.AppImage`

SHA-256: `f5d567ad54265253e08e29cf38d174feb908896db99213bdbda1a174df2f11e4`。
この版はIrodori F16・Qwen Q8・RVC Saishoの3候補で、後続のGPU/VRAM案内と追加量子化は含まない。

`tmp/tts-latency-100/native-final-downloads-2/` は実Tauri GUIで1 PASS（26.24秒）。

- Irodori/Qwen/RVCの提供元・ライセンス・正確な容量・保存先・注意事項を実ダイアログで確認。
- 同意チェック前は開始不可。確認して戻るだけではモデルフォルダを作成しない。
- RVCをGUIからHugging Faceへ要求し、model.pth + model.indexの全335,643,277 bytesを取得。保存後に親もsize/SHA-256を再計算しカタログと一致。
- 完了だけでは既存設定を変更しない。「モデルパスを適用」でモデル/indexだけを反映し、cleanフォームが取り込むことを確認。他の入力設定は一致。
- 再起動後にパスを保持、入力選択は空・captureは起動しない。通常ユーザーの設定は変更しない。

`native-final-downloads-1` はリンククリック後、X11のactive window名でブラウザを判定したためFAILとした。WaylandのFirefoxへ提供元URLが渡された実プロセスを後で確認し、`opener-process-evidence.json` に記録した。これはURL付き起動の証拠であり、ページ内容やHTTP成功の確認ではない。ブラウザ終了は自動承認レビューで既存タブへの影響が懸念され拒否されたため、終了せず残している。ダウンロード本体は上記の別実行で成功した。

`download-live/report.json` は製品managerによる別の実転送試験。RVC全取得・ハッシュ成功、Irodori/QwenはGGUF先頭4 bytesの応答後に取消。後者をTTS全ファイルの実ネットワーク取得成功とは扱わない。旧試行のCDN拒否は `us.aws.cdn.hf.co` 完全一致追加で修正し、拒否記録も保持した。

## RVC実変換

`native-final-rvc-1` は同じAppImageで1 PASS（28.08秒）。取得したSaishoモデル/indexと既存のRVC runtimeを使い、合成日本語PCMから実変換、入力無音時の管理経路mute中の無音、resume後の変換出力、停止後2秒無音、再起動時のパス保持・入力OFFを確認。index_rate=0.5。停止操作→専用source継続無音のreadは81.260074 ms（n=1）。物理マイク、知覚的な声質、VRChat内部再生を検証した結果ではない。

事前にCPUの `torch.load(weights_only=True)` でv2/48k/f0=1、457 weight tensorsを確認した。RVCランタイム・Python環境・HuBERT・RMVPEの自動取得は含まない。

Voice model created by **Saisho Utane** — https://huggingface.co/Saisho-Utane — Used under the [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/). モデルは改変していない。

## 軽量候補の独立検証

追加候補は同じ固定revisionのIrodori MF Q8_0とQwen CustomVoice Q5_K。`variant-downloads/report.json` で全ファイルの取得とsize/hashを検証した。

| 候補 | bytes | SHA-256 |
|---|---:|---|
| Irodori v4.1 MF Q8_0 | 1,207,133,984 | 2d161b0bbcd74f906f6b07e03d031075f8ae916db1b8bd4daf16cb37b451086a |
| Qwen3 0.6B Q5_K | 873,894,144 | 4bb9ba9e822ab614798c416c7f0187994f349be41221966fa911aca24f237930 |

`variant-smoke-1` は実speech.cpp 0.9.0/Vulkan0で以下3候補が成功。日本語固定文「こんにちは。音声の接続テストです。」・seed42、Irodori voice=none、Qwen voice=ono_anna。health/options、2回合成、PCM到着後の取消、サーバー停止、再起動後の再合成と取消、子回収を確認した。各モデル内の計3回は全PCMのSHA-256が一致。量子化の異なるモデル同士の音声一致は要求していない。

| モデル | 生成PCM rate | 所有モデルプロセスの観測ピークVRAM |
|---|---:|---:|
| Irodori MF Q8_0 | 48,000 Hz | 1,499 MiB |
| Qwen Q5_K | 24,000 Hz | 1,000 MiB |
| Qwen Q8_0（既存cache） | 24,000 Hz | 1,332 MiB |

RTX 4080 SUPER、NVIDIA driver 615.78.08。`nvidia-smi -q -x` の所有speech PIDのused_memoryを約100 ms間隔で取得した最大値であり、測定点間のピークや最低必要容量を保証しない。GUI、物理出力、ルーティング、ASRによる内容正答率をこのHTTP合成smokeで検証したとはしない。100 ms性能目標はこの試験の判定に含めない。

`speech-devices.json` はモデルをロードせず同梱speechの `devices --json` を実行した点時記録。NVIDIA GPUの総17,171,480,576 bytes・空き14,246,150,144 bytes、CPUを確認した。空き値はその瞬間のもので予約は行わない。他メーカー/機種での実機成功へ一般化しない。

## 軽量候補の実GUI・全PCM照合

`native-variants-1.log`: 3 PASS（79.50秒）。Irodori Q8 / Qwen Q5 / Qwen Q8を各2回、実AppImageの送信から別プロセスの実GPUサーバーへ送り、専用sourceで録音した。別起動の `variant-smoke-1` 合成参照に対して6/6件すべて全PCMが偶数offsetで一致し、前後はゼロ。捕捉の連続性・長さも確認した。

Qwenは24 kHz、Irodoriは48 kHzで専用graphと録音rateを一致させた。Qwenの意図的な再サンプリングを欠落と誤判定しないためであり、一般の48 kHzホスト経路の検証には広げない。日本語本文をQwenにも送るため、日本語外部サーバーURLに所有Qwenを指定した。この試験は新catalogの選択・同梱多言語枠での起動確認とは分ける。使用AppImageは上記f5d567固定版。

## 回帰結果とレポートの確定

固定3モデル候補時点：既定suiteは1,222 PASS/6 SKIP、音声suiteは1,152 PASS/49 SKIP。skipはブラウザ・実音声等のopt-inで、未実行分を成功へ含めない。ログは `tmp/tts-latency-100/final-{default,voice}-suite.log`。

レビューで、測定ハーネスが外側context cleanup前にpassedを保存できる潜在問題を検出した。保存済み実行はpytest exit 0も確認済みで、この問題による誤合格ではない。現行ハーネスは外側with完了後に成功を確定し、例外時failedを保存する。旧版のcleanup失敗注入で誤passedを再現し、修正版2件成功。既存の保存harness/resultは書き換えていない。

## GPU案内を含む新AppImage

`build/gpu-model-guidance-2026-10-30-artifacts/VRCT-TTS-3.6.0-beta.1-linux-x64-vulkan-release.AppImage`
SHA-256: `3c034035748633fa4e11d56c09379bd8dfe751dbf86b62aee0d1c3945a33036a`。catalog版2026-10-30.2。ビルド前後の記録対象543件のhash一致を確認。この記録にはintegrations配下を含めていなかったため、全製品入力を網羅した記録ではない。旧f5d567版は保持。

`native-guidance-final-2` は1 PASS（41.36秒）。実Vulkan0行としてRTX 4080 SUPER、空き13.31 GiB/総15.99 GiBを観測し、標準推奨からIrodori Q8とQwen Q5を手動選択した。実HF取得済みファイルを試験config下に事前配置し、製品の全size/hash検証→別Apply→同梱の日本語/多言語サーバーの起動・停止を確認。パス以外の保存値を保持し、再起動時はサーバーOFF/モデルパス保持。これはcache検証であり、再度のネットワーク転送ではない。

最初の `native-guidance-final-1` はハーネスが音声設定とサーバー設定の同名fieldsetを取り違えて失敗。2ではBundled speech.cpp servers内へ限定した。GPUの検証済み機種名を実GPU検出と誤認しないよう、Vulkan0を含む実デバイス行を待つ。失敗記録も保持。

新sourceの回帰は既定1,222 PASS/6 SKIP、音声1,170 PASS/51 SKIP（`guidance-regression.log`）。担当ブラウザ14 PASS・Node12 PASS、probeの無応答子回収も単体確認。最終低遅延分布は `native-guidance-latency-30` の独立実行結果で別判定する。

最終3c034035版の低遅延30回も `native-guidance-latency-30` で1 PASS（355.82秒）、p95上限50.054284 ms、全PCM31/31一致。`native-guidance-controls-final` は停止4種と復帰1 PASS、`native-guidance-rvc-final` はSaisho実変換・停止・再起動1 PASS（27.35秒）。RVC停止→専用source継続無音84.046854 ms、n=1。最終まとめは `tmp/tts-latency-100/final-release-verification.json`、配布フォルダの `verification.txt`。

## 無出力判定のレビュー補強

保存結果のレビューで、旧RVC試験はミュート中に非ゼロ入力を流しておらず、旧controlsの無音判定は短い音漏れの後に2秒静かになる場合を除外できないと判明した。旧結果は保存したまま、その範囲の主張を限定する。RVCの再開後変換・停止、低遅延30回の厳密PCM一致・性能結果を否定するものではない。

補強版ではRVCミュート中も合成PCMを再生し、独立したoriginal captureへの非ゼロ入力到着・producer完了と、全区間の出力nonzero_frames不変を要求する。controlsのOFF新規送信・再ON・保持ミュート新規送信でも、操作前後のnonzero_frames不変、新規sample増加、連続captureとreader生存を要求する。これらの無音閾値はS16絶対値64以下であり、strict30の全byteゼロ判定とは異なる。実silence関数への短い音漏れ注入は旧版RED→新版GREEN。関連25件成功。新規実機結果は別ディレクトリに保存する。

## RVC検索修正を含む最終配布候補

`build/gpu-model-guidance-rvc-fixed-2026-10-30-artifacts/VRCT-TTS-3.6.0-beta.1-linux-x64-vulkan-release.AppImage`
SHA-256: `b8050d10c7243da5d57dda92d09784912947ad6516eccde152d11e4ef3bb4fe0`。

補強した `native-guidance-rvc-strict-2` は旧3c034035版でFAILとなった。ミュート中の非ゼロ入力は出力されなかったが、入力完了より前にRVCワーカーが停止していた。これは遮断の全体合格にはしない。診断でSaishoのIVF検索が近傍8件を集められず、欠落ID=-1を拒否して終了していたことを確認した。詳細と原典は[RVC検索修正記録](rvc-index-search-report.md)。旧保存結果は保持した。

修正はRVCアダプターの初期化時の探索設定だけ。新たにintegrations/config/build関係を含めた575入力を記録して前後一致を確認し、AppImageを実展開したmanifestのアダプター・ライセンス18件もsourceと照合。`rvc-fixed-build-{inputs,verified}.json`に保存した。

`native-rvc-fixed-strict-3` は実GUIで1 PASS（45.82秒）、exit0。ミュート中に全合成PCMを再生して独立入力captureが138非ゼロframes増加、出力は0増加。producer完了の約2.136秒後にも新鮮なactive/requested=true・errorなし・同じgenerationを確認。Resume後は別の全入力を最後まで処理し、出力195非ゼロframesと新鮮なactive状態を確認。その後の第三の入力中に停止し、70.955044 msで後続2秒の継続無音、再起動OFF。無音閾値はS16絶対値64以下、遅延はn=1の操作呼出→専用source readで、物理聴感やVRChat到達は未確認。

`native-guidance-controls-strict-2` は旧3c034035版で1 PASS（59.16秒）。OFF新規送信・再ON・保持ミュート新規送信の全3区間でnonzero_frames増分0、97,920〜98,880の新規samples、reader連続性を確認した。停止4種も成功。以後の製品変更はRVC loaderのみでTTS/controls部分は不変。新FAISS回帰5件（任意runtimeでunittest）と通常環境の関連54 PASS/6 SKIPを区別する。6 skipのうちFAISS5件は別runtimeで実行済み、任意ML依存の既存worker suiteはこの通常環境で未実行。

最終b805版の `native-rvc-fixed-tts-smoke` は1 PASS（72.01秒）。ウォームアップ＋2送信の全PCM3/3が偶数offsetで1回だけ参照一致し前後ゼロ、OFFは2.266666秒全byteゼロ、OSC全4件各1回。warm2件の上限48.540881/49.052663 msはsmoke値で、summary.verdict=insufficient_samplesを保持する。既存担当も保存PCM・時計を独立再計算し一致。30件の性能判定は3c034035版の記録に限定する。
