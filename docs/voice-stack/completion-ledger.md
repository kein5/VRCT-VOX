# VRCT-TTS 全機能実装の継続記録

基準: [ユーザー仕様書](spec/VRCT_cpp_Codex_Implementation_Spec.md)、[開始指示](spec/VRCT_cpp_CODEX_START.md)、[原典索引](spec/VRCT_cpp_imozuru_evidence_map.md)。入力3ファイルは提供された原本の写し。
開始HEAD: `9dbd2400`。既存の`frail-walrus` worktreeを継続する。

## 継続・停止条件

2026-10-27: ユーザーは全機能完了まで閉ループで進めるよう指示。通常の実装・修正・自動試験・ローカルコミットは確認待ちを挟まない。
追加指示: 問題発生時はimozuruで原典と関連実装を調査。それでも解決策を得られなければループを終了し、作業を中断する。
未測定の性能や実機試験を成功として扱わず、仕様の各ゲートを維持する。モデルの新規取得・配布には仕様の同意条件を適用する。
2026-10-28追加指示: リポジトリを`kein5/VRCT-TTS`へ改名し、予定機能完成後に公開して上流へ全部/一部の取り込みを打診する。
改名とローカルremote更新は実施済み。
**同日後続指示が優先: 上流への連絡・取り込み打診・PR作成（draft含む）は完成後も自動実行しない。**
実行前にユーザーの明示的な指示を必要とする。完成後の成果公開は維持、上流mergeは別。
詳しくは[公開・上流方針](publication-and-upstream.md)。

2026-10-29追加指示: 実装がひととおり揃った後、公開前に**Trail of Bits Skillsによる
セキュリティ監査**を実施する。適用するSKILL.mdを確認し、コード・依存関係・配布物を調査、
指摘の重要度と根拠、修正・再検証結果、未確認範囲を記録する。現時点では未実施。
音声・モデル・認証情報の外部送信、上流連絡・PRの許可へは拡張しない。
公式の[Trail of Bits Skills](https://github.com/trailofbits/skills)と
[静的解析の入口](https://github.com/trailofbits/skills/tree/main/plugins/static-analysis)を確認済み。
実施時は版・ルール・対象範囲を記録し、導入や文書確認だけをスキャン完了として扱わない。

### 現在のPCで進める範囲（2026-10-28追加指示）

ユーザーはWindows作業を後日、別のWindows PCで行う方針を指定した。
このLinux PCでは、進行中のP4マイク翻訳発声の受入試験を完了させ、P2直接VCの製品統合、
P5のLinux配布・OS共通の安定化/ライセンス確認を進める。
P3のLinux側に残る実機確認も対象として保持する。Windows専用経路の実装・実機試験は後日へ移し、
必要事項と再現手順を引き継げる形で記録する。Windows未対応を理由に独立したLinux作業を止めない。
一方、Windows要件を完了扱いにはせず、両OSを含む全機能完成とは区別する。
VCの聴感・物理入力・HMD・混在負荷などの未検証条件と、上流PR/連絡を自動実行しない指示は維持する。

### 再起動のため中断（2026-10-29）

ユーザーのPC再起動・アプリ更新の希望により、短い回帰確認と保存を行って中断する。
複合試験でSidecarのGCによるVC停止を観測し、転送の別プロセス化を実装したが、
実モデル混在のキュー超過がまだ1件残る。30分合格・speech.cpp同梱は未完了。
再開点・検証結果・原典は[再起動前記録](combined-voice-checkpoint-2026-10-29.md)。

### 再起動後の再開（2026-10-29）

後続の「再開して」に従い再開し、uvで再起動により消えたPython参照を復元した。
実RVC/ASR/VAD/TTSの120秒複合試験と停止・異常終了の短い試験は通過。
30分試行で空のASR確定文が翻訳へ流れる不具合を再現し、終端として破棄するよう修正した。
音声回帰797 PASS / 9 SKIP、標準回帰1,222 PASS / 6 SKIP。
実GUIの設定遷移に対するテスト操作も、動く文字ではなく実際のバーと遷移状態で検証するよう修正。
その後も`vc_block_expired`／`vc_capture_overrun`を再現。imozuruで公式原典を調べ、
工程別診断とスレッド制限の比較を行ったが安定した解決策を得られず、指定された停止条件で中断した。
別録音したPCMの同期ずれも未解決。30分受入れ・P5同梱は未完了。
詳細と証拠の範囲は[再開後記録](combined-voice-resume-2026-10-29.md)。

後続情報: 前回、別セッションでComfyUI＋MiniMaxによる動画生成が稼働していたとユーザーから報告。
生成停止後の再開指示を受け、既定設定のまま30分再試験が**1 PASS**（全体1,862.05秒、継続1,806.32秒）。
464件の発声完了、強制終了後も原音漏れなし・翻訳発声継続、停止・再起動OFFを確認した。
GPU919観測でComfyUI検出0、照会失敗0。過去の失敗原因をGPU競合と確定したわけではなく、
スレッド設定の前回比較も外部負荷を管理した実験ではない。[結果JSON](combined-voice-gpu-isolated-results.json)。
物理/VRChat/HMD・聴感・制御した競合・過去のPCMずれ・RSSの長期推移は未検証。
P5の[固定配布部品計画](../superpowers/plans/2026-10-29-speechcpp-bundle-artifact.md)へ進む。

P5-A完了: speech.cpp0.9.0の公式CPU/Vulkan ZIPから実行ファイル＋通知だけを作るツールを実装
（`bcd5c623`）。関連67 PASS、両実物のhash照合・移設起動・禁止資産検査が成功。
[配布部品報告](speechcpp-bundle-report.md)。モデルは非同梱。GUI所有サーバーとLinuxアプリ配布は次工程。
局所レビューでZIP検証後の差し替え・特殊metadataの待ちを2RED→GREENで修正したが、
後日依頼されたTrail of Bits Skillsによる全体監査はまだ行っていない。

### P5の追加要件（2026-10-29ユーザー承認）

speech.cpp本体をVRCT-TTSの配布物へ同梱する。検証した版・hashを固定し、OSごとの実行ファイルと
必要な再配布可能依存物、ライセンス表示を揃える。現在は未実装・未配布。
GUIから同梱サーバーの起動・状態確認・終了を管理し、既存のlocalhost HTTP接続を活用する。
既存の外部サーバーを指定する方法も保持する。アプリが起動したプロセスだけを終了対象とする。
モデルは既存ファイルの指定、または個別条件を示して同意後に取得する方針とし、本体同梱の承認を
全モデル・参照音声の取得や再配布の承認へ拡張しない。Windows実機作業は後日の別PCで行う。

**以下はP2 RVC実装時点の記録（2026-10-29）。**
Seed-VCの間欠停止原因は未特定のまま保持し、独立したRVC統合を進めた。
GUI・共通経路・固定RVC workerを実装。その後ユーザー提供Mia2026と承認済み基礎モデルで実変換・私有PipeWire・60秒連続・実Tauri GUI試験が成功。[実RVC報告](rvc-mia-validation-2026-10-29.md)。Mia2026は検証専用で同梱禁止。
独立レビューの3指摘は`c8d3c399`で修正。標準1,222件、音声721件、実TauriのVC/原音試験2件が成功したが、
過去の`vc_block_expired`とキャプチャ開始失敗を解消した証拠にはしない。
[最新レビュー・残課題](direct-vc-review-2026-10-28.md)。今回のP5追加要件は記録のみで、同梱実装は開始していない。

**以下は2026-10-28の再開時点の記録。** ユーザー提供のDPMS再現調査と消灯防止ガードを照合し、
通常configの実Tauriで描画・設定保存復元・終了と再起動後のミュートを確認した。
10/27の原因はDPMS未記録のため推定と区別する。[追記報告・試験手順](native-ui-report.md)。
本番UI→実speech.cpp→独立仮想マイクの9ケースも通過した。[本番音声試験](native-voice-report.md)。
さらに本番UI→実speech.cpp→ホスト仮想マイク→VRChatローカル再生を別実行し、9ケース通過。
[ホスト受入れ報告](native-vrchat-report.md)。Native Task 3の最終reviewは完了し、
Important 2件を再現テストで修正。選択回帰280 PASS / 1 SKIP。
[指摘・修正と判断](native-plan-review.md)。
さらに本番UIでOSC実UDP送信と音声の各1回・OFF互換を確認し、導入済みIrodoriのUI起点30回測定は
誤差を含む上限p50 208.296ms / p95 367.064ms。[計測条件と境界](native-latency-report.md)。
VRChat未起動・独立PipeWireでの値である。その後、同一実Tauri送信による本人Chatbox描画と
仮想マイク発話1回、OFFで表示更新・無音を確認した（2ケース）。[実表示の報告](native-chatbox-report.md)。
Windows・混在負荷等の残条件を全機能完了として扱わない。

## 要件と現在地

| 段階 | 実装・証拠 | 未完了の受入条件／次の成果物 |
|---|---|---|
| P0 | baseline・ADR・測定器・ライセンス台帳 | 新しい構成ごとの差分検証を継続 |
| P1 | TTS provider、scheduler、UI、OSC契約、Linux/Windows出力adapter。部品UI試験16件、実Tauri/全Modelの描画・保存復元・安全な再起動、本番UI→実TTS→独立仮想マイク9件とホスト/VRChat9件。本人Chatbox実表示＋発話1回/OFF無音2件、UI→PCM write30回で目標内 | Windows実機、VRChat併用の性能・混在負荷 |
| P2 | Linuxの原音/Seed-VC/RVC選択、外部変換worker、入力選択・設定保存・開始停止を本番Controller/UIへ接続。実Seedと合成入力で変換→私有仮想マイク、発話途中停止、同名入力再作成時の自動再接続なし、再起動OFFを確認。最新native VC/原音2試験PASS（[報告](direct-vc-review-2026-10-28.md)） | 過去の間欠停止原因、同じ入力によるVC/ASR/TTS併用、物理マイク→VRChat、聴感・長時間遅延・負荷、Windows、最終ライセンス比較。RVCはMia2026で実変換・私有仮想マイク・60秒連続・本番GUIを検証。実マイク/VRChat・聴感・長時間・制御したGPU負荷比較は未検証 |
| P3 | legacyを維持し、speech.cpp REST/Realtime、mic/speaker別session、VAD、Linux capture/resample、有界queue、字幕置換・確定翻訳・大きいoverlayを接続。実Tauri/private音声/実ASR/VADで表示・停止・再起動OFFを確認（[報告](realtime-captions-report.md)） | 実翻訳モデルの品質/速度、物理発話終端からの遅延、HMD表示、native legacy録音への切替、Windows、混在負荷 |
| P4 | テキストの原文/訳文TTS、mic finalの選択訳文発声、共有queueの優先度・期限・取消、managed直接音声の抑制/明示mix、Controller/UI接続、Mainからの入力別停止を実装。実ASR/VAD/Qwen・私有音声経路で原音＋TTS＋原文/訳文OSCのnative試験3件PASS（[報告](spoken-translation-report.md)） | 実翻訳品質/速度、多言語全体の受入、動的ducking、VC統合・混在負荷。P4全体は未完了 |
| P5 | Linux専用graphと一部host試験、禁止OCR重み除外検査。speech.cpp本体同梱をユーザー承認済み | speech.cpp同梱・GUIからのサーバー管理、配布・fork識別、両OS障害復旧、30分混在負荷、回帰、実artifact台帳 |

## 判断

- Ruling: P1の実アプリ検証に必要なLinux起動作業をP5から前倒しする — Windows実機を前提にしたままP1を完了扱いにせず、利用者のCachyOSで実経路を検証するため — Windows・HMDを代替した証拠にはならない。
- Ruling: 調査原文とraw試験はworktreeの`tmp/voice-completion/`、共有する結論・計画・測定要約はdocsへ — 書込み可能範囲と既存成果物方針に合わせる — tmpを削除すると原文/raw再取得が必要。
- Ruling: 既存設計Bを条件付きで継続し、全機能を一度に作り直さない — 既に停止・故障の証拠があり、追加抽象化の利益は未測定 — Bの判断を覆す条件はADR004/005のまま。
- ユーザー確認（2026-10-28）: fork元の途中認識も翻訳・OSCへ送る経路と比較し、新Realtimeの「partialは原文字幕更新、finalを翻訳し、選択した成功訳文のみTTSへ」を採用。途中の認識変更による表示と発声の齟齬を避けることを優先し、翻訳字幕・OSC・TTSが確定を待つ挙動を維持する。OSCは既存送信設定に従う。認識/翻訳の正しさや実測遅延の保証ではない。[設計記録](../superpowers/specs/2026-10-28-spoken-translation-design.md)。

## 現在の作業

Linux本番起動: Python依存不足、Windows固定sidecar path、起動時のモデル自動取得を調査。
imozuruの2検索役は完了。原文を保存し、Tauri prerequisites→sidecar契約、PyAudioWPatch→固定SpeechRecognition実装、uv環境→Python削除APIへたどった。
既存GTK/WebKitGTKとPortAudio開発環境は検出済み。Python3.11.17専用venvをuvでtmpへ用意し、Windows限定依存・任意OCR/buildを除いた既存依存111packageを導入。既存venvは未変更。

### Native Task 1: Linux開発sidecar

Windowsのinterpreter pathを固定参照する問題を再現（6 FAIL / 4 PASS）。OS別pathとUnix execによる同一PIDへの置換を追加し、10 PASS。
音声180件と併せて190 PASS。Ruff/diff check PASS。元の軽量環境で全体pytestは引き続き80 collection error。
実Tauri・全Model・Windows実機はこの試験の範囲外。根拠: [Tauri sidecar契約](https://v2.tauri.app/develop/sidecar/)、[Rust CommandExt::exec](https://doc.rust-lang.org/std/os/unix/process/trait.CommandExt.html#tymethod.exec)。
テストは`tests/platform/test_dev_sidecar.py`、rawは`tmp/voice-completion/sidecar-{red,green}.log`と`task1-tests.xml`。

### Native Task 2進行中: Python import互換

実依存で再現した2点を原典と照合して修正: s16 WAV処理がPyAudioWPatchを必要としていた箇所を固定16bit幅に変更、
Windows専用WINFUNCTYPEの宣言を既存OS判定へ合わせた。実PCM・画像helper試験は各RED→GREEN、既存transcriberと合わせて60 PASS（依存警告7件）。
本番Modelのimportが成功。TauriのLinux cargo check/buildも成功したが、GUI起動・Controller.initはまだ未検証。
Rust依存取得と正しいtarget tripleのsidecar配置で、従来font-kit未キャッシュ/sidecar不在によるbuild停止は解消。
Windows captureはLinux未対応のまま。これをGUI全体・ASR入力の完成とは扱わない。

### Native Task 2: 本番初期化・設定の保存復元

`AUTO_DOWNLOAD_MODELS`を既定OFFで永続化し、起動時の初回取得と再試行の両方へ適用。
その他設定にON/OFF操作を追加。旧configにキーがない場合もOFF。既存モデルの利用と明示取得APIは維持する。
`VRCT_CONFIG_DIR`で設定・logsだけを分離し、既存利用者の設定を変更せず実起動を試験できるようにした。
Linuxの`.venv_linux`選択、Windows専用3依存のmarker、任意OCR除外profileを追加。
既存venvは未変更。Windowsで評価したmarkerは既存3依存を選択するが、Windows実機試験の代替ではない。

検証: 関連suite **201 PASS**、実Main/Controller/Modelを2回起動するstdio試験 **1 PASS**、Vite build PASS。
最終選択回帰（実stdio、UI endpoint契約、既存transcriberを含む）は **266 PASS / 5 warnings**。
保存した日本語voice名が再起動後も復元され、音声OFF・モデル自動取得OFFを確認。Tauriや音声経路はこのstdio試験に含めない。
全体suiteは **1173 PASS / 16 FAIL / 6 SKIP**。修正前の実依存環境と同じ16失敗で、
内訳はWindows endpoint tracker 4、Windows専用sample-player 3、Windows clipboard 7、VR panel capture 2。
軽量環境の80 collection errorと区別する。これらをLinux対応済みとしてskipで隠さず、P5の未対応項目として残す。
変更範囲のRuffで新規違反は解消。既存config unused import 1とtranscriber import-order 5は未変更。

raw: `tmp/voice-completion/{settings-red,settings-green,task2-selected,task2-general,native-startup,task2-ui-build}.log`。
実起動stdout/stderr・保存設定は同`native-startup-run/`内（テスト用生成tokenを含むため公開対象外）。
imozuru原典10本、ローカル実装snapshot、hash一覧と引用照合済みreport/digestは同`research/linux-native/`。
Python検索役の追加queryは未回収と記録し、回収できた7 queryのhitsを保存。原文の再配布はしない。
起動障害の解決策は得られたためユーザー指定の中断条件には該当せず、実Tauri受入れへ進む。

- Ruling: Linux環境では任意OCRだけをuv excludeで導入対象から外す — Windowsのrequirements選択を変えず、未対応captureとcv2競合を起動経路から外す — Linux OCR対応時は依存契約を再評価する。
- Ruling: 言語復元テストの入力を`Japanese`から既存の保存形式`ja`へ修正 — config原典の許容値に合わせるテスト修正であり、製品の言語形式は変更しない。

### Native Task 3途中: DOM接続と描画を分離して中断

内蔵モデル不足でUI全体がSplashに留まる条件と、Python warningの続きがfatalになる処理を修正。
実Tauri DOM試験はRED→GREEN。診断ログも`VRCT_CONFIG_DIR`へ分離した。
完成部分の選択回帰280 PASS / 1 SKIP / 5 warnings、Node 2 PASS、Vite/Tauri build PASS。
ただし描画を確認するrAF試験は1 FAIL、PID照合した実ウィンドウ画像は黒。
imozuruで調べた回避候補は試験プロセス内でのみ比較し、いずれも有効な解決策にならなかった。
実Tauri→音声経路への受入れは開始せず、ユーザー指示に従いここで実装ループを中断。
詳細・再開条件・証拠の限界は[native-ui-report.md](native-ui-report.md)を参照。

### P2 入力転送UIまで完了、実VC PoCの取得同意待ち

明示identityの開始・停止、TTS独立、全体mute、同名再作成、再起動OFFを本番UIで確認。
実Tauri/Controller/private PipeWireは16ケースを2回PASS。独立レビューCritical0/Important0、UIのMinor2は保留。
[入力制御報告](source-controls-report.md)。
次の[実VC PoC候補](vc-engine-poc-proposal.md)と[固定artifact一覧](seed-vc-poc-artifacts.json)を用意。
Seed候補約1.524GBは未取得。VADはHF固定モデルを明示的な別候補として扱い、既定ModelScope版との同一性を主張しない。
仕様§8のモデル取得同意と許可ある参照音声が必要。上流への連絡・PRは引き続き禁止。

### P2 実VC PoCと独立レビュー完了（2026-10-28）

前節の取得同意待ちは解消。ユーザーが固定5モデル取得と参照音声利用を承認し、uvの隔離runtimeで実変換を確認した。
[PoC報告](seed-vc-poc-report.md)・[判断と保留](seed-vc-poc-decisions.md)。実モデル59 PASS、私有経路7ケースPASS、レビュー修正後関連356 PASS。
外部GPL候補の評価までで、製品converted機能は未公開。物理mic/VRChat/Windows、品質、語頭、長時間VAD/負荷は未検証。
次は品質・継続性ゲートを実施し、採用可否と製品統合を分けて判断する。全機能閉ループの指示を継続し、PR/上流連絡は実行しない。

### P3 専用REST adapterの先頭工程（2026-10-28）

P2の聴感回答待ちの間に、仕様指定のREST-first部品/CLIを作成。[報告](speechcpp-rest-asr-report.md)。
新規モデルなしで実speech.cpp0.9.0/ReazonSpeechを検証。レビュー後29実/模擬テスト、関連471PASS。
Realtime用Silero約1.24MBは[固定候補](speechcpp-vad-proposal.md)を確認し、取得同意待ち。重みは未取得。
P2実デバイス/品質とP3WS/capture/UI/final統合は未完了。ユーザーへSilero同意とVC聴感を別途依頼中。


### P3 Realtime部品・承認済みSileroの実試験（2026-10-28）

前節のSilero同意待ちは解消。固定1,238,624 bytes/MITモデルをユーザー承認後に取得しSHA256照合。
mic/speakerの2セッションで各7 partial・2 final、無音入力で更新なしを実モデルで確認した。
[プロトコル報告](realtime-asr-protocol-report.md)。独立レビューImportant2を再現修正し、模擬36PASS・実試験込み38PASS。
関連542PASS/11SKIP、既定1173PASS/16既知FAIL/6SKIP。現時点ではファイル入力による通信部品の検証。
次はcaptureの明示format変換と有界queue、UI字幕、finalだけを既存翻訳へ接続する。
P2品質についてユーザーは「今は試聴できない」と回答。未確認を残し、独立工程を継続する。
41秒のVC継続試験は完了済みだが、30分混在負荷・実デバイス・Windows・聴感の代わりにはしない。


### P3 連続PCM入力部品と実Realtime接続（2026-10-28）

[入力報告](realtime-audio-ingress-report.md)。44.1/48k→24kmonoのanti-alias変換と有界queueを追加。
元48k合成fixtureを実server_vadへ流し、mic/speaker各6partial/2final、無音で更新なし。
独立レビューImportant1（send待ち中の停止）を修正し、実モデル込み56PASS・関連526PASS/11SKIP。
物理capture/選択UI/partial表示/final統合は次工程。license配布条件とWindows実機は保留。

### Linux Realtime capture（2026-10-28）

取得cycleとidentityを保持するnative helper、20ms parser、Python ownerを追加。
私有OSの合成source/sink-monitor→実speech.cpp/ReazonSpeech/Sileroでpartial7/final2ずつ、開始前無音・停止後結果破棄を確認。
取得/変換/protocol/実モデル97 PASS。音声回帰480 PASS/12 opt-in SKIP、defaultは1173 PASS/既知16 FAILのまま。
[報告](linux-realtime-capture-report.md)・[時刻境界付き結果](linux-realtime-capture-results.json)。
Ruling: raw pw-catでは取得時刻が失われるためnative libpipewire helperを使用。C/PipeWire/対応kernelの配布条件が増える。
Ruling: latency変更後のbuffer epoch対応が保証されないため停止を維持し、実試験producerは先に構成。実運用の経路変更で手動再選択が必要になる。
Ruling: 非協調callbackを無理に終了せずnative取得を先に停止し、残callbackがあればconsumer_busy。UI側の停止世代破棄は後続で必要。
P3の次工程はUI字幕・final翻訳接続。物理録音・Windows・P4/P5・VC聴感を完了扱いにしない。
Linux captureの独立review Important2は合成C6case RED→GREENで修正。実ASR/VAD込み音声suite490 PASS/8 opt-in SKIP、default既知16失敗不変。破損PCM/NULLlatencyの停止契約を保持。追加reviewなし、Minorなし。

### Realtime字幕接続: session owner（2026-10-28）

source別の単一使用RealtimeSessionと保存設定validationを追加。取得/Ingress/WSを所有し、update queue32・停止時のnamespace即無効化・非join取消とclose完了境界を分離する。
model/languageを既存RESTでpreflightし、host名localhost入力は既存helperで数値loopbackへ正規化する。
設定に録音enabledを保存しない。起動中取消、2source独立、切断/queue overflow、古い字幕破棄、再停止のterminal stateを検証。
新規関連54 PASS、実ASR/VAD込み全音声527 PASS/8 opt-in SKIP、default1173 PASS/既知16 FAIL不変。
Controller/UIへはまだ接続していない。次工程は同sourceのlegacyとの排他、字幕更新・final翻訳・停止世代のIPC接続。

### Realtime字幕接続: Controller・UI・実アプリ受入れ（2026-10-28）

上記session工程の「Controller/UI未接続」は解消。source別の開始停止・設定保存、legacy排他、partial/final/翻訳の同一行更新、speakerのOSC/TTS禁止、大きいoverlayのpending/history管理を接続した。
[報告](realtime-captions-report.md)・[結果](realtime-captions-results.json)。実Tauri/実ASR/VAD/private OS音声の受入1試験25.06秒PASS、各source2字幕、HTTP翻訳4件、mic訳文と一致するUDP2件、speaker0、停止後追加0、再起動captureOFF。
翻訳は本番LMStudio adapterと固定HTTP応答による接続試験であり、実MTモデルの品質・速度ではない。
外部翻訳でローカルCTranslate2が必須だった処理と、字幕本文の常時process.log保存をRED→GREENで修正。標準suite1181PASS/既知16FAIL/6SKIP、失敗名は前回と完全一致。
受入修正後の音声suite564PASS/7Seed opt-in SKIP/2warnings56.62秒。最終独立reviewを続ける。
Ruling: private PipeWireではhost Pulse/ALSAを隔離できないため、native legacy録音への切替は未実行。Controller排他試験を実録音の代替としない。
Ruling: Realtimeのoverlayは大きい表示に接続し、小さい表示はlegacy providerのまま。HMD表示は別gate。
物理遅延、Windows、VC聴感/製品統合、P4訳文発声、P5配布/負荷/ライセンスを未完として継続。上流PR/連絡は行わない。

### Realtime字幕工程の独立review完了（2026-10-28）

[レビュー記録](realtime-captions-review.md)。Important4を再現して修正: フィルター通知の暗黙本文保存、拒否したoverlay更新の履歴復活、legacy stopのtimeout誤認、停止後のenergy操作不可。
imozuru原典照合と6件の模擬cleanup試験で、未完了threadを保持し正常停止を確認してからRealtimeへ引き継ぐ境界を追加した。
最終関連55PASS、音声568PASS/7Seed opt-in SKIP、標準1194PASS/既知16FAIL/6SKIP（失敗名一致）、実Tauri受入1PASS25.15秒。Ruff/diffPASS。
Minor1: 両source停止後にpollが終わり「Stopping captions」表示が残る場合がある。再開始は可能、busyならbackendが拒否する。保留を明示。
P3 Linuxの製品接続工程は完了。物理/Windows/実MT/HMD等の受入条件は前記のまま未検証。次はP4 mic final訳文発声と音声排他を実装する。ブランチ・ledgerは継続のため保持し、公開・上流PR/連絡はまだ実行しない。

### Linuxの既存16失敗の修正（2026-10-28）

ユーザーの追加指示に従い、P4の前にimozuruでTDD原典とPython/pytest公式仕様を調査。
既存16失敗を再現後、Windows APIをテスト対象モジュール内に隔離し、Linux上でも既存の回帰条件を検証可能にした。
ChatboxのOS共通処理を妨げるWindows限定ガードを除き、POSIX端末入力を追加。
新規PTY/EOF試験はRED→GREEN。Linuxで標準suite **1222PASS / 0FAIL / 6既存SKIP / 46既存warnings**。
元の16件をskip/xfailに変更していない。新規12件を追加。Windowsネイティブ動作の確認とは区別する。
COMピーク自動選択・Win32フォーカス/キー送信・Windowsパネル撮影のLinux実装を追加した意味ではない。
[修正範囲・原典・検証と残条件](linux-test-portability-report.md)。最終独立reviewはCritical/Important/Minorとも0件。
本節より前の16FAILは当時の記録として保持する。

### P4 native受入と独立レビュー修正（2026-10-28）

明示承認済みの読み取り専用Codex CLIレビューが完了。AITの子→親通知を使わず実行できた。
指摘3点をREDで再現し、Resume時の両経路確認、旧ASR所有者の発声取消、最初の非ゼロ書込みまでの期限維持を修正。
追加のPipeWire通知回帰はimozuruで公式change_mask契約と実通知を照合して解決した。
修正後: 選択110 PASS、標準1222 PASS/6既存SKIP、音声665 PASS/7任意Seed runtime SKIP、実Tauri3 PASS。
Native/Vite/Tauri build・変更範囲Ruff・diff検査PASS。P4のこの実装計画は完了、P4全要件の受入ではない。
[測定境界・残条件・レビュー修正](spoken-translation-report.md)。P2の外部VC製品統合を継続する。

### P2 live worker部品（2026-10-28）

原音/VCの排他owner、時刻・session・sequence検証付き外部Seed worker、所有スレッド終了時の強制停止を実装。
既存許可済みモデルと合成入力による私有音声経路でStop/worker死亡の2試験PASS。Controller/UI接続は次。
標準1222 PASS/6 SKIP、音声689 PASS/8任意runtime SKIP。物理入力・品質・継続負荷の受入ではない。
[実装・ライセンス境界・測定](direct-vc-product-report.md)。

### P2 Controller/UI接続とnative受入の残件

fdb53643で原音/Seed-VC選択と保存、明示開始・停止を接続。標準1222 PASS/6 SKIP、音声705 PASS/8任意SKIP、ブラウザ1 PASS、Vite/Tauri build PASS。
Native productの初回は2回目発話で期限超過、診断1回目は再開始capture失敗。診断2・3回目は全項目PASSだが、先の間欠失敗を解決扱いにはしない。
captureのみ40回開始停止PASS。根因調査中。P2コードの独立外部レビューは自動承認審査がP4限定の許可では実行不可と判定し、P2の明示承認待ち。
[調査経過・未検証境界](direct-vc-product-report.md)。全機能完了、公開、上流PR/連絡は実施していない。

**現在の停止点（2026-10-28追記）:** 診断コード除去後の実Tauri本番VC＋既存原音転送は2 PASS（98.49s）。ただし初回の期限超過・再開始capture失敗の根因は未確定。imozuru調査で解決策未確定なら中断するユーザー指示に従い、次の機能追加を停止。P2独立外部レビューの明示承認も待機中。Task4/P2全体は未完了。未検証条件を試験成功で上書きしない。
