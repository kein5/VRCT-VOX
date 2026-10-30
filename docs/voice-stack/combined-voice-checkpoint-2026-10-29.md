# 再起動前の作業記録 — 2026-10-29

ユーザーのPC再起動・アプリ更新のため中断する。**全機能完了・長時間安定・公開可能という記録ではない。**
再開順は「残る混在停止の切り分け → 30分試験 → speech.cpp同梱」。Windowsは別PCで後日。
上流への連絡・PR・push・公開はしていない。

## 確認できたこと

- 同じ合成sourceから実RVCと実ReazonSpeech/Sileroへ分岐し、確定訳文をQwen TTSへ渡す。
  翻訳は既存LMStudioアダプターに接続した固定HTTP応答であり、実翻訳モデルの品質試験ではない。
- 短い実Tauri試験ではTTS各1回、原文＋訳文のOSC各1回、ASR停止後のRVC継続、全体ミュート、
  RVC停止後の無音、再起動時の入力OFFを確認。41.37秒の試験で1 PASS。
- 別の短い試験ではRVC workerを強制終了してもASR/TTSが継続し、原音へ切り替わらなかった。
  51.92秒の試験で1 PASS。これらの短時間成功を長時間安定の根拠にはしない。
- 混合波形をTTS単独のenvelopeと比較すると誤判定するため、TTS/VC sink monitorを別々に記録。
  TTSの閾値は維持し、各分岐の時間合わせ後の合計と最終出力も比較する方式を追加。

## 発見した問題と変更

混在試験で`vc_capture_overrun`、`vc_block_expired`を再現した。
時刻だけの一時プローブは、アプリSidecarの第2世代GCが**98.59 ms**続いた区間と、
音声配送の停止・その後の一括配送・キュー超過が重なることを記録した。
直前の推論応答は約20〜37 msだった。RVC子のスレッド制限だけでは期限超過を防げなかった。
これは特定試行の観測であり、すべての停止原因をGCと断定しない。

既存の音声転送処理を別Pythonプロセスへ移し、アプリとは設定・状態だけを交換する構成を実装。
元の80 ms block、待ち1 block、block終端から160 msの期限、原音fallback禁止を維持する。
親/制御thread/supervisorの終了は既存native監視の連鎖で扱う。GCの無効化や期限拡大は行わない。
詳細は[設計](../superpowers/specs/2026-10-29-vc-transport-isolation.md)。

親PythonのGILを350 ms保持するモデル不要の実音声試験は、旧構成で停止するREDを確認し、
分離後は継続と停止後の無音を確認した。分離後の実モデル複合試験でもキュー超過が1回残り、
原因は未確定。診断付きの次の試行は74.29秒・21確定訳文まで進んだ後、試験用プロセス情報の
読み取りが`psutil.AccessDenied`になって終了した。計測不能は不完全な測定として記録する修正を追加したが、
その試験の成功・30分合格は主張しない。

実ASRは同じ音声でも後続試行で区間数が変わったため、連続試験は「毎回2区間」という仮定を除き、
実際の確定件数とTTS/OSC件数の対応を見る。認識内容の正確さ・聴感は未評価。

## 独立レビューと検証

許可済みP2/P4範囲で、コード・仕様・差分だけを読み取り専用Codex CLIへ送付した。
モデル・録音・認証情報は含めていない。AIT子通知は使用していない。
レビュー4件をすべてRED→GREENで修正した。

1. 状態通知pipeが満杯でもStopを処理する（通知はnonblockingの置換可能なsnapshot）。
2. 強制終了を正常cleanupと報告しない。
3. 初期要求の後ろにある不正な制御データを捨ててcaptureを開始しない。
4. 相対モデル/runtimeパスを検証時の絶対パスに固定して子へ渡す。

再起動前の検証: 関連116 PASS（既存警告1）、標準1,222 PASS / 6 SKIP（既存警告46）。
レビュー修正後の私有音声GIL停止試験も1 PASS（8.06秒）、停止後2秒の無音を再確認した。
新規/変更PythonのRuff、差分空白検査とnative helperビルドは成功。
全voice回帰、修正後の実モデル長時間試験、配布/frozen実機試験は再開後に行う。

## 再開方法と保存先

- 計画: [複合試験](../superpowers/plans/2026-10-29-combined-voice-validation.md)、
  [転送分離](../superpowers/plans/2026-10-29-vc-transport-isolation.md)。
- 実行ログ・再実行script・私有PCM: `tmp/voice-resume/combined-voice/`（git管理外）。
- 原典・調査ログ: `tmp/voice-resume/research/combined-voice/`。
- 一時プローブ: `tmp/voice-resume/combined-voice/probe/sitecustomize.py`。本番コードには組み込んでいない。
- 独立レビュー: 同ディレクトリの`review-result.md`。レビュー後の再レビューはしていない。
- Mia2026は検証専用、非同梱。既存モデルと合成入力を継続使用し、新規モデル取得はしていない。

再開時は更新後のOS/PipeWire/GPUドライバー/アプリ版を記録し、旧環境の測定値と区別する。
最初に短いモデル不要試験・実モデル試験を再実行してから30分試験へ進む。
物理マイク→VRChat、聴感、実翻訳品質、HMD、Windows、speech.cpp同梱は未完了のまま。

## 原典

- [PipeWire loopback](https://docs.pipewire.org/page_module_loopback.html): 分岐とsink monitor。
- [Python 3.11 GC](https://docs.python.org/3.11/library/gc.html): 世代別回収と観測callback。
- [固定RVC GUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8f68b6bed1789f682fe78cdd324495afc/realtime_gui.py): 起動時thread設定。
- [Faiss threading](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls)、
  [PyTorch 2.7 threading](https://docs.pytorch.org/docs/2.7/notes/cpu_threading_torchscript_inference.html): 競合仮説を調査。
  thread制限は本番変更として採用していない。
