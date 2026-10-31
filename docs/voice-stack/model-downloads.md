# 設定画面からの既定モデル取得

TTS・ASRの「同梱speech.cppサーバー」内とRVC設定画面に取得UIを追加。提供元、モデル名、正確な容量、利用条件へのリンク、用途・注意、保存先を表示し、チェックボックスへの同意と開始操作を必要とする。翻訳モデルの起動時取得への同意とは独立している。

同意は警告を開いた時点のカタログ版に結び付ける。更新された未確認の版で開始しない。

取得成功後の「モデルパスを適用」は別操作。完了ファイルを再検証し、現在の保存パスが画面で確認した値と一致し、対象が停止中の場合だけ反映する。編集中の設定は保存または破棄が必要。device、low_latency、RVC runtime、pitch/index_rate、入力モードは維持する。モデルのロード、発声、サーバーやマイクの開始は行わない。

## 固定カタログ

版 `2026-10-31.1`。TTSは各2候補から選択でき、ASRはHaas-jaの1候補、RVCはSaishoの1候補。

| ID | リポジトリと固定revision | ファイル / bytes | SHA256 |
|---|---|---|---|
| irodori-v41-f16 | sakasegawa/Irodori-TTS-v4.1-Small-MF-GGUF @ 9db7da1bec3d1069ef8e29732e0497be60c7b047 | Irodori-TTS-866M-MF-v4.1-F16.gguf / 1920321792 | e237dc3eefe469b8bba87872beacf12fb7fe00dbdf85767edca8ec04ab910d13 |
| irodori-v41-q8 | 同上 | Irodori-TTS-866M-MF-v4.1-Q8_0.gguf / 1207133984 | 2d161b0bbcd74f906f6b07e03d031075f8ae916db1b8bd4daf16cb37b451086a |
| qwen3-06b-q8 | sakasegawa/Qwen3-TTS-12Hz-0.6B-CustomVoice-GGUF @ fd9df9364613a92a86b4137074bc281204823033 | Qwen3-TTS-12Hz-0.6B-CustomVoice-Q8_0.gguf / 1213534464 | f606ea3981aa42762b16db9a94826d2d560eb60f0b102001618f40d5a2f78cc6 |
| qwen3-06b-q5 | 同上 | Qwen3-TTS-12Hz-0.6B-CustomVoice-Q5_K.gguf / 873894144 | 4bb9ba9e822ab614798c416c7f0187994f349be41221966fa911aca24f237930 |
| rvc-saisho | Saisho-Utane/Saisho-Model-RVC @ 7a61b17e4f014fc5013a489f2b5cd3a7ee9e2b1a | model.pth / 57577658 | 82312a29a3996a451aaa3d3776566cec85b47b5414fce53da82b2d66b04f3d35 |
| rvc-saisho | 同上 | model.index / 278065619 | e9f7396e5db3077274c720d055e43abb8f1eac5609cbdf48b198ca4f4a35cad5 |
| haas-ja-q8 | sakasegawa/Haas-ja-v1.0-GGUF @ 6b965d5007ba780585de51549d57a8c1c0d67c7e | Haas-616M-ja-v1.0-Q8_0.gguf / 656381472 | cd5f60b2f1c411404b83fca4a65e3ce30a26d9e951b6a346529e65f22758afeb |

[Irodoriカード](https://huggingface.co/sakasegawa/Irodori-TTS-v4.1-Small-MF-GGUF/blob/9db7da1bec3d1069ef8e29732e0497be60c7b047/README.md)と[Qwenカード](https://huggingface.co/sakasegawa/Qwen3-TTS-12Hz-0.6B-CustomVoice-GGUF/blob/fd9df9364613a92a86b4137074bc281204823033/README.md)から元モデルへたどり、speech.cpp v0.9.0の[Irodori](https://github.com/nyosegawa/speech.cpp/blob/v0.9.0/docs/models/irodori-tts.md)・[Qwen](https://github.com/nyosegawa/speech.cpp/blob/v0.9.0/docs/models/qwen3-tts.md)資料と照合した。専用GGUFはcodecを含む。IrodoriはMITとcodec基盤Apache-2.0、提供元の無断模倣・誤情報生成禁止なども表示。QwenはApache-2.0。

[Haas-jaカード](https://huggingface.co/sakasegawa/Haas-ja-v1.0-GGUF/blob/6b965d5007ba780585de51549d57a8c1c0d67c7e/README.md)から元モデル[third-intelligence/Haas-ja-v1.0](https://huggingface.co/third-intelligence/Haas-ja-v1.0)へたどり、speech.cpp v0.10.0の[FastConformer資料](https://github.com/nyosegawa/speech.cpp/blob/v0.10.0/docs/models/fastconformer.md)と照合した。Apache-2.0。このrevisionのファイルはspeech.cpp 0.9.4以降が必要で、同梱0.10.0で読める。ASRサーバーにはVADモデルも必要だが、カタログには含めず従来どおりパスを指定する。HaasはGPU推奨量の実測をVRCT側で記録していないため、ハードウェア推奨の対象にしない。

2026-10-31、同梱0.10.0 Vulkan版とHaas Q8_0・Silero v6.2で、`SpeechServer`経由のGPU/CPU起動、`/v1/models`での認識モデル列挙、REST認識、Realtime（サーバーVADあり/なし）のライブ試験を実行しPASS。入力はIrodori MFで合成した日本語2文で、認識精度の評価ではない。

[Saisho作者カード](https://huggingface.co/Saisho-Utane/Saisho-Model-RVC/blob/7a61b17e4f014fc5013a489f2b5cd3a7ee9e2b1a/README.md)は本人の声・自前データセット・CC BY 4.0・帰属必須を明記。Voice model created by **Saisho Utane** — [作者](https://huggingface.co/Saisho-Utane) — Used under the [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/). 本アプリはモデルを改変しない。モデル利用者にも公開物や説明でのクレジット、ライセンスへのリンク、改変表示を案内する。Mia2026はカタログに含めない。

RVCのmetadataはv2/48 kHz/f0=1。初期の短時間試験後、長めのミュート入力試験 `native-guidance-rvc-strict-2` で `vc_capture_overrun` による停止を検出した。先行する検索例外を追跡し、IVFインデックスの狭い探索範囲による近傍候補の欠落が原因と判明。RVCアダプターで探索範囲を初期化時に調整し、待ち行列・鮮度制限・不正検索結果の拒否は維持した。失敗記録も保持している。

修正版AppImage `b8050d10c7243da5d57dda92d09784912947ad6516eccde152d11e4ef3bb4fe0` の `native-rvc-fixed-strict-3` は1 PASS（45.82秒）。ミュート中の全合成音声入力（非ゼロ138フレーム）に対し出力増分0、入力完了後の新鮮な稼働状態と同じgenerationを確認。解除後にも別の全入力を完了し、第三の入力中の停止と再起動OFFを確認した。無音判定はS16絶対値64以下、停止後2秒継続であり、全バイトゼロや知覚的な音質を確認した試験とは区別する。詳細は[実機検証記録](model-downloads-integration-report.md)を参照。

RVC音声モデル/indexだけでは動作しない。別途runtimeのengine、Python環境、HuBERT設定/重み、RMVPEが必要（integrations/rvc/README.md参照）。既定runtimeの自動インストールやダウンロード処理によるpickleの読込みはこの機能に含めない。

## GPU・空きVRAMによる案内

TTS設定を開くと、整合性確認済みの同梱speech.cpp 0.9.0を `devices --json` で実行する。モデルはロードしない。GPU名、総容量・空き容量、確認時刻を表示し、再確認ボタンも設けた。実行はバックエンドの非同期処理で3秒timeout、終了時は所有する子プロセスだけをterminateし、応答しなければkillして回収する。固定実行ファイルの出力を受け取った後、64 KiB以内かとJSONの型・値域を検証する。任意の実行ファイルやURLは指定できない。

同じGGUFを各対応バックエンドで利用するため、GPUメーカー別にモデルを分けず、空き容量に応じて標準候補と軽量候補を案内する。ただし、実機検証はLinux / RTX 4080 SUPER / Vulkanに限る。AMD・Intel・Metal・CPUの実行成功を確認した表示にはしない。

| 枠 | 標準候補 | 軽量候補 | 上流のVRAM測定例（標準 / 軽量、十進GB） |
|---|---|---|---|
| 日本語 | Irodori MF F16 | Irodori MF Q8_0 | 2.30 / 1.59 |
| 多言語 | Qwen CustomVoice Q8_0 | Qwen CustomVoice Q5_K | 1.33 / 0.99 |

上流値はリンク先のspeech.cpp v0.9.0資料にあるRTX 2080 / Vulkan・日本語20文での測定例であり、必要最低容量ではない。量子化による容量削減と音声品質の変化の可能性も表示する。Qwen Q4は上流の転記誤り率の増加を考慮して今回の候補から除外した。

案内には次の条件を使う。

- 実行エンジンが既定で使う最初のGPUを対象にする。複数GPUの容量は合算せず、別GPUへの切替も行わない。
- `max(上流の測定例, 親担当の観測ピーク) × 1.25 + 余裕容量` が現在の空きVRAMに収まる場合、標準を優先し、次に軽量を案内する。
- 余裕容量は「VRChat等と併用」の2 GiBが既定。「TTS単独」の0.5 GiBも選べる。25%と余裕容量は案内用の方針であり、確保済みメモリや動作保証ではない。
- CPU指定、共有メモリGPU、容量不明、取得失敗、2分を超える古い測定は理由を表示する。空き0と不明は区別する。収まる候補がない場合も自動選択を勧めず、手動選択は可能にする。

選択しても設定のモデルパスや実行デバイスは変わらない。警告への同意、取得、検証後のApplyは従来どおり別操作。手動選択を保持し、取得中に別候補へ切り替えても進捗・取消・適用ボタンを残す。RVCは声の選択であり、このVRAM見積りは適用しない。TTS・RVC・ASR・ゲームの同時利用や長文には追加の余裕が必要になる。

軽量2候補は親担当が実HF全取得と固定size/hashを検証済み。Irodori Q8、Qwen Q5、Qwen Q8は実GPUで合成・取消・停止・再起動し、各モデル3回のPCM一致を確認した。別の実GUI経由でも各2回、独立参照との全PCM一致と前後の無音を確認。Irodoriは48 kHz、Qwenは24 kHzのモデル固有rateでの照合であり、ホスト側の48 kHzへの再サンプリングや知覚音質まで確認した結果ではない。観測ピークVRAMはそれぞれ1,499 / 1,000 / 1,332 MiB（100 ms間隔の所有PID測定）で、測定間のピークを取り逃す可能性がある。

新しい案内UIを含むAppImage `3c034035748633fa4e11d56c09379bd8dfe751dbf86b62aee0d1c3945a33036a` でも、実GPU表示→軽量2候補の選択→既取得cacheの製品検証→Apply→同梱日本語/多言語サーバーの起動・停止→再起動時OFF・パス保持を確認した。これはcache検証であり、新UIで全ファイルを再転送した試験ではない。条件・保存先・失敗記録は[親担当の実機検証記録](model-downloads-integration-report.md)を参照。

同じAppImageのIrodori F16・低遅延待機ONでは、固定短文のwarm 30回がp95上限50.054284 ms、p50上限46.018233 ms。測定は信頼されたGUIクリックから最初の非ゼロPCM書込み完了まで。warmupを含む31発声の全S16 PCM一致・前後ゼロ、OFF時2.304秒ゼロ、各送信のOSC1回を保存記録から独立再計算した。これは軽量モデルの速度保証ではない。試行間隔は約10.18〜10.24秒で、任意長文・ゲームとの競合・物理聴感へ一般化しない。独立確認は `tmp/tts-latency-100/guidance-independent-review/`、測定詳細は[低遅延試験記録](tts-low-latency-report.md)を参照。

RVC検索修正を含む最新版は `build/gpu-model-guidance-rvc-fixed-2026-10-30-artifacts/` のAppImage（SHA256は上記b8050d10…）。30回の性能値は旧3c034035…版の測定として保持する。新しい入力hash記録はRVC等のコピー対象も含む575件。親担当の展開検査でアダプター・ライセンス18件が元ファイルと一致し、本担当も記録と現sourceのhashを照合した。旧543件の一致記録にはintegrations以下は含まれていなかった。

b8050d10…版のTTS再確認 `native-rvc-fixed-tts-smoke` は1 PASS（72.01秒）。warmup＋warm2件の全PCM一致・前後ゼロ、OFF時2.266666秒の全バイトゼロ、各送信のOSC1回を保存PCMから独立確認した。warm2件は性能の再認証には足りず、`summary.verdict=insufficient_samples` のまま保持している。

## 取消・失敗・終了の境界

保存先はconfig.jsonと同じディレクトリの `downloaded_models/<id>/<revision>/`。ネットワークは固定HF URLから、HTTPSと許可された配信先へのリダイレクトだけを許可する。親担当のHEAD確認で3モデルに使われていた `us.aws.cdn.hf.co` を完全一致で追加し、他のサブドメイン/HTTP/認証付きURL拒否を回帰確認した。認証情報・任意URL・任意の展開コマンドは受け取らない。読取りを小分けにし、容量とSHA256を照合。全ファイル成功後に同じファイルシステム上でディレクトリをrenameする。既存の破損cacheを上書きせず、失敗して報告する。空き容量は総ファイル容量+64 MiBを事前確認し、書込み中のENOSPCも失敗扱い。

取消はEventを保持して完了処理と排他し、本文待機中のsocketをshutdownしてread1を解除する。終了時も同じ処理を行う。ただし**DNS・接続・headersが戻る前は即時停止できない**。ネットワーク操作は15秒timeoutだがDNSなども含めた一律15秒の終了保証ではない。closeの2秒待ちで残った場合は未完了をログに出し、モデルパスを適用しない。

強制終了の残骸は、次の明示的な取得開始時に回収する。root単位のOSロックを取得できた場合だけ、製品・モデル・revision・ファイル名が一致する所有marker付き `.partial-<uuid>` を削除する。生存する他プロセスの取得、未知/不完全marker、余分なファイル、symlinkは回収しない。完了ディレクトリも削除しない。再開用Range転送は実装しておらず、取り消した転送は次回やり直す。

overlay relayは新しいcatalog/state/start/cancel/applyとhardware取得/更新の7ルートをすべて拒否する。新しいJotai atomはdynamicStoreRegistryに登録しない。リンクはTauriではopener経由、mainウィンドウの権限はHF・CC BY・ApacheのURLに限定する。失敗時はコピーできるURLを表示する。ブラウザ試験での模擬invoke成功と、実AppImageによるURL付きブラウザプロセスの起動確認は別の記録として扱う。

## 実装と試験

- `src-python/models/model_downloads/{catalog,transport,staging,manager,hardware,guidance}.py` とController/stdioの7ルート。
- `ModelDownloads.jsx` / `useModelDownloads.js`、SpeechServers/DirectVoiceSettingsへの小さな挿入。en/jaの独立namespace。
- `modelHardwareAdvice.js`で取得値と候補から案内を算出。CPU・共有メモリ・容量不明/ゼロ・複数GPU・測定期限を区別する。
- IPC送信関数を安定させ、再描画に伴うcatalog/state再取得ループを修正。idle時の取得回数不変をブラウザで確認。
- Apply後の確認済み保存値がcleanフォームへ反映されない問題は、`useSettingsDraft.jsx`で直前の保存値とdraftを比較する形に修正。未保存の編集は保持する。
- 初期3候補版の関連backend **92 PASS**（所有するloopbackサーバー、HTTP停止body、SIGKILL回収、RVC/TTS Apply、既存speech/controller/consent回帰）。`/tmp/vrct-model-download-backend-final.log`。
- 初期3候補版のブラウザ新機能7件＋speech server5件 **12 PASS**。先行の全フォーム25件ではstatus locator競合1件を検出し修正、他24件成功。修正後の対象を再試験。`/tmp/vrct-model-download-browser-final.log`。
- relay/既存翻訳3言語同意 **8 PASS**。Vite本番build成功（出力は `/tmp/vrct-model-download-ui-dist`、通常dist不変更）。
- 既定pytest suiteはsandbox内で **1218 PASS / 6 SKIP / 4 FAIL**。失敗はchatboxのloopback UDP、OSC単一受信thread、TelemetryFacadeのapp_started/error重複抑止2件。4件を所有loopback許可付きで単独再試験すると **4 PASS**。suite全体の同条件再実行ではないため全体GREENとは記載しない。ログは `/tmp/vrct-model-download-default-{suite,recheck}.log`。

GPU案内追加後の担当試験は次のとおり。上の初期結果へ足し合わせない。

- backend **58 PASS**：取得manager、controller、hardware probe。SIGTERMに応答しない所有fake子プロセスのkill・回収も含む。`/tmp/vrct-model-hardware-final-unit.log`。その1件追加前のHTTPを含む実行は59 PASS（対象の組合せが異なる）。
- ブラウザ **14 PASS**：取得UI9件と既存speech serverフォーム5件。軽量候補の案内・選択・同意、取得中の候補切替と取消、GPU取得失敗時の手動選択を確認。`/tmp/vrct-model-hardware-ui-green.log`。
- Node **12 PASS**：容量案内・overlay拒否・既存翻訳同意。`/tmp/vrct-model-hardware-node.log`。Vite本番buildも成功、出力は `/tmp/vrct-model-hardware-ui-dist`。
- 親担当の新source統合回帰は既定 **1,222 PASS / 6 SKIP**、音声 **1,170 PASS / 51 SKIP**。`tmp/tts-latency-100/guidance-regression.log`。skipは成功に含めない。

imozuru原典は `tmp/model-download-research/` のmap/log/manifest、原文22件、照合済みextracts/report.html/digest.html。GPU・音声・SteamVR・通常アプリの操作は親担当が実施し、本担当は実装・オフライン/ブラウザ試験と保存結果の独立照合を担当した。
