# 日本語TTS低遅延待機の実測（2026-10-30）

最終AppImage（GPU案内を含む3c034035版）で、固定日本語短文を実GUIから30回送信した結果、送信クリックから最初の非ゼロPCM書込みまでのp95上限は **50.054284 ms**、中央値上限は **46.018233 ms**。今回の100 ms目標を満たした。前候補f5d567版のp95は82.759524 msで、両実行を区別して記録する。

両実行とも30回と独立したウォームアップ1回のすべてで、録音PCM内に参照PCMがサンプル単位で完全一致して1回存在し、前後はゼロだった。欠落・挿入無音・重複音声を許容する包絡相関だけの判定ではない。

## GPU案内版の30回測定（3c034035）

`build/gpu-model-guidance-2026-10-30-artifacts/VRCT-TTS-3.6.0-beta.1-linux-x64-vulkan-release.AppImage`

SHA-256: `3c034035748633fa4e11d56c09379bd8dfe751dbf86b62aee0d1c3945a33036a`。
`tmp/tts-latency-100/native-guidance-latency-30/` にartifact/harness/verification/GPU記録と、pytest配下の全PCM・時計・OSC・trace・reportを保存した。1 PASS（355.82秒）、32件の実行成功とsummary性能判定passを両方確認。以下の前候補と同じモデル・文・seed・観測境界で、GPU案内追加後に独立実行した。

| 観測 | 最終候補 |
|---|---:|
| p50 時計校正区間 | 42.696263–46.018233 ms |
| p95 時計校正区間 | 46.785374–50.054284 ms |
| 最大の校正上限 | 52.821534 ms |
| 固定参照との完全一致 | 31/31（ウォームアップ含む） |
| 最大連続PCM read間隔 | 43.358330 ms（100 ms超0） |
| GPUボード電力の全実行平均 | 98.763 W（3,560点） |

前候補との差は実行間のばらつきを含み、GPU案内機能がTTSを高速化した証拠ではない。電力は発声を含む全実行平均で、待機専用の増分ではない。任意のGPU・文章・待機時間や物理到達時間の保証に拡張しない。

## 前候補の成果物と共通測定条件

- AppImage: `build/tts-model-downloads-2026-10-30-artifacts/VRCT-TTS-3.6.0-beta.1-linux-x64-vulkan-release.AppImage`
- SHA-256: `f5d567ad54265253e08e29cf38d174feb908896db99213bdbda1a174df2f11e4`
- RTX 4080 SUPER / Vulkan GPU / 同梱speech.cpp 0.9.0 / Irodori v4.1 Small MF F16。
- 同じモデル・voice=none・ja・seed=42。本文は「こんにちは。音声の接続テストです。」。モデル読込済み、低遅延待機ON、処理待ちなし。
- 実Tauri/WebKitGTK → Python sidecar → 同梱サーバー → 専用PipeWire仮想source。通常アプリの設定、物理入力、ホスト音声経路は変更しない。
- 起点は信頼されたDOMクリック。ブラウザ時計とmonotonic時計を操作前後に校正し、時計幅を含めた保守的上限を採用。p95はnearest-rank（30件の29番目）。

保存証拠は `tmp/tts-latency-100/native-gc-fixed-30/` の `artifact.json`、`harness.py`、`verification.json`、`gpu.csv`。
`pytest/test_native_osc_once_with_voic0/` に `report.json`、`reference.pcm`、31件の発声PCM、OFF時PCM、`first-write.jsonl`、実GUI画像・ログを保存した。試験コマンドは1 PASS、356.95秒で終了。発声と同時のOSC送信は各1回、OFF送信時は発声なし。

| 観測 | 結果 |
|---|---:|
| p50 時計校正区間 | 41.053575–44.315650 ms |
| p95 時計校正区間 | 79.464511–82.759524 ms |
| 固定参照との完全一致 | 31/31（ウォームアップ含む） |
| 連続観測の100 ms超read間隔 | 0 |
| 最大PCM read間隔 | 43.620116 ms |
| GPUボード電力の全実行平均 | 93.504 W（3,570点） |

電力は起動・発声・待機を含む全実行の値で、待機時だけの増分ではない。旧基準との同時・対比較でもない。ゲーム負荷・長文・異なる声/seed・任意の長い待機・他GPUではこのp95を保証しない。最初の書込みは耳やVRChatに届く時点ではなく、DAC/無線/ネットワーク/VRChat内部処理・他プレイヤー受信は測定していない。read間隔も知覚音質や全ネットワーク欠落の指標には読み替えない。

## 実装と原因

GPUが省電力状態へ戻った後は同一短文のTTFAが208–351 msとなり、連続時31–34 msとの差を再現した。固定の短文「あ。」、seed=0の準備計算を専用tokenで反復し、生成PCMを破棄する選択式待機を追加。通常の送信queue・ユーザー本文・音声出力へ接続しない。通常はOFF。0.75秒間隔は339 msを残したので採用せず、完了後0.1秒待ちを採用した。アプリ終了/サーバー停止で回収し、待機だけの失敗は通常TTSを停止しない。

さらに、旧候補では第一音の目標達成後も音声途中に欠落があった。診断実行 `native-gc-diagnostic-30` のwarm-006で、世代2の自動GC 91.193 msと、参照サンプル14,080付近の途切れが重なった。256サンプル欠落と64 msの挿入無音を保存データで確認した。録音側の連続性は保たれていた。

`AudioRouter.play` のPCM生成器消費開始からwrite/drain終了まで、自動循環GCを延期する `defer_cyclic_gc()` を追加。参照カウントは継続し、同時利用者を数え、最後の退出で開始前のenabled状態を復元する。例外/取消/重複利用を単体検証した。出力バッファ容量は変更しない。延期はPythonプロセス全体に及び、他コードの明示的な `gc.collect()` は阻止しない。schedulerの30秒取消要求は全経路の絶対復元期限ではない。

公式[speech.cpp Irodori実装](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/src/engines/irodori-tts-engine.cpp)から初期warm_upとseed処理をたどったimozuru記録は `tmp/tts-latency-100/research/`。[Python GCの仕様](https://docs.python.org/3.11/library/gc.html)と合わせて自動循環回収だけを延期する設計とした。

GC診断は既定OFF。ON時もメモリ上の256件dequeへ記録し、発声後にファイルへ出す。overflow件数を持たないため、記録がないことをGC不在の証明にはしない。今回の合格根拠は保存PCM全体の厳密一致である。

## 停止と復帰

同じAppImageの `native-final-controls-1` は実GUI/実モデルで1 PASS。長文発声中に各停止を実行し、取消traceと2秒間の継続無音を確認した。

| 操作 | 呼出開始→専用source継続無音の最初のread |
|---|---:|
| 再生停止・queue破棄 | 42.285398 ms |
| TTS OFF | 83.495520 ms |
| 保持ミュート | 1.637626 ms |
| 同梱サーバー停止 | 6.169165 ms |

いずれもn=1で、遅延上限や物理聴感値ではない。OFF/保持ミュート中の新規送信と再ONでは、新規traceなし・後続2秒無音を確認した。ただし旧判定では途中の短い音漏れを除外できず、全区間の無出力は後述の補強試験で確認する。モデル読込途中の停止とアプリ再起動も確認した。再起動時は低遅延設定を保持するが、サーバーとTTS受付はOFF、管理sourceはmuteのまま。

## 保持した失敗記録

- `native-baseline-30` と `native-low-latency-30` は音声途中の欠落で失敗。後者は名前に反してCLIでstandbyを指定し忘れた通常モードであり、artifact/reportのfalseが正しい。
- `native-optimized-30` の旧包絡判定では30回成功、p95 87.759739 msだったが、後解析でwarm-020の挿入無音・欠落を確認した。第一音の計測値は保持するが、全体品質合格にはしない。
- その後S16偶数長/offset境界を含む全PCM一致ゲートを追加。1 byteずれを拒否する回帰も実施した。これらの失敗を削除・除外して最終30件を作っていない。今回の最終候補で新しく独立実行した30件が上記結果である。

## 独立レビューと後続ハーネス修正

既存レビュー担当44b1c384は、productionのexact_pcm/elapsed_bounds/summarizeを使わず保存bytesと校正50点から再計算し、31件の完全一致とp95/中央値を一致確認した。発声開始間隔は10.1735〜10.2461秒。独立記録は `/tmp/vrct-review-final30.{py,json}`。

レビューで「外側context cleanup前にJSONをpassedへできる」潜在P2を発見した。今回の実行はpytest exit0も確認済みでこの誤合格ではない。現行ハーネスでは外側with完了後へ成功確定を移し、例外時にfailed/error_typeを保存する。旧保存harnessを使ったcleanup失敗注入で誤passedを再現、新版の回帰2件成功。旧結果・保存ソースは保持した。`status=passed` は実行成功で、性能の合否は別の `summary.verdict` を必ず確認する。

## 最終候補の停止・復帰の再確認

`native-guidance-controls-final` は3c034035版で1 PASS（59.15秒）。再生停止11.658067 ms、TTS OFF80.472031 ms、保持ミュート16.713088 ms、サーバー停止11.076040 msで専用sourceの継続無音へ移行した（各n=1、操作呼出→read境界、2秒の無音確認）。OFF中の新規送信・再ON・保持ミュート中の新規送信は新規traceなし・後続2秒無音。後続の独立レビューで、この判定だけでは途中の音漏れを除外できないことが判明したため、全区間無出力とは扱わない。全4取消traceと読込途中取消、再起動OFF/設定保持、outer cleanup後のpassed/exit0を確認。

既存担当の独立最終レビューは `tmp/tts-latency-100/guidance-independent-review/`。生PCM・時計50点から最終p95/中央値/最大値を再現し、31発声一致・OFFゼロ・OSC各1回・固有trace31件を確認した。発声間隔は10.184〜10.241秒。

停止後の「無音」はToneCaptureのS16絶対値64以下という閾値判定で、strict30の全byteゼロとは別の基準である。OFF等の全区間無出力は、操作前後のnonzero_frames不変を要求するハーネスへ補強し、別実行で再確認する。

## 無出力判定の補強とRVC修正版

`native-guidance-controls-strict-2` は同じ3c034035版で1 PASS（59.16秒）。OFF新規送信・再ON・保持ミュート新規送信の3区間で、操作前後のnonzero_frames不変と2秒以上の新規samples・連続readerを確認。途中に200ms音が漏れる場合を拒否する実silence関数の回帰も成功した。停止4種の操作呼出→継続無音の最初のreadは40.182669 /83.661709 /39.356320 /11.563432 ms（stop/OFF/mute/server stop、各n=1）。これは64 S16閾値であり、strict30の全byteゼロと区別する。

後続b8050d10版はRVCのIVF探索設定だけを修正した配布候補。30件のp95上限50.054284 msは3c034035版で得た結果として保持し、b8050d10版で30回を再測定したとは扱わない。TTS経路の製品ソースは不変で、新版の実GUI/PCM照合smokeを別実行する。RVC側の失敗と修正は[rvc-index-search-report.md](rvc-index-search-report.md)を参照。

最終b805版の `native-rvc-fixed-tts-smoke` は1 PASS（72.01秒）。ウォームアップ＋2送信の全PCM3/3が偶数offsetで1回だけ参照一致し前後ゼロ、OFFは2.266666秒全byteゼロ、OSC全4件各1回。warm2件の上限48.540881/49.052663 msはsmoke値で、summary.verdict=insufficient_samplesを保持する。既存担当も保存PCM・時計を独立再計算し一致。30件の性能判定は3c034035版の記録に限定する。
