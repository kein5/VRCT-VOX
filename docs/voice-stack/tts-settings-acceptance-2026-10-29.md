# TTS/RVC設定の統合確認（2026-10-29）

Task 1–5の実装はローカルコミット`dd2e239f`まで。後継セッションで独立レビュー5件を再現・修正した。
既存のOOM分類差分を保持しているため、今回の作業用Linux候補にはその未コミット差分も含む。
別セッションの資料、インストール済みAppImage、ホスト音声経路は変更していない。

| 確認 | 結果 |
|---|---|
| 音声回帰 | 1,012成功、36スキップ、既存警告6 |
| TTS/RVC・専用ページ・seed/Instructionブラウザ | 17成功 |
| 既存直接VCブラウザ | 1成功。模擬応答も本番同様にgenerationを更新 |
| 実Tauriの870×654、100%/150%、長いパス、Tab、改行保存 | 2成功 |
| 実Tauriの起動描画、設定保存・再起動復元 | 各1成功 |
| 私有PipeWireの独立停止、ASR transport→翻訳→OSC継続 | 2成功 |
| AppImage通常起動・描画・保存復元（FUSE/展開各方式） | 6成功 |
| tar候補の再配置・sidecar・同梱エンジン | 2成功、GUI等2スキップ（別実行で確認） |
| Vite、Linux build、AppImage作成・内容検査 | 成功。既存chunkサイズ警告あり |

ブラウザ初回読込の失敗は、MainFunctionSwitchの共通部品barrelが不要なCSS/SVGを読み込む経路まで記録した。
ToggleSwitchの直接importに変更し、元の4秒期限で通過。音声停止期限とassertion timeoutは延長していない。
ネイティブ試験は既選択タブの再クリックを避け、aria-labelで入力を特定し、改行をWebDriverのEnterで入力する。

RVCの入力・ピッチは開始応答前から固定され、設定ページから開始をキャンセルできる。
原音/Seed-VCの開始待ちはRVCの停止対象にならない。停止未確認時は所有者と処理中表示を保持する。
workerの非同期エラーはトップにも通知する。「破棄して移動」は閉じたまま残るフォームのdraftも戻す。
未保存のRVC開始、数値の範囲外、巨大seedの切り詰めも回帰試験に追加した。

既存Irodori v4.1 Small MFをCPUで起動し、「こんにちは。」を同じseed=42・同じInstructionで2回生成した。
各138,240バイトのPCMは完全一致（SHA-256 `165ac1cd748abe4757fb20705561fa4c64795ea2785ee9a06988514ddea336b6`）。
生成全体は4.742秒・5.108秒。モデル単体HTTP試験であり、GUIからの発声遅延ではない。
先行の2文試験ではCPU生成中のストリーム間隔でtransport timeoutが発生した。この制約を解消済みとは扱わない。
異なるseed、CPU/GPU間一致、Instructionの聴感は評価していない。

独立停止試験は440Hzの原音と880HzのHTTP模擬TTSを使用し、私有仮想マイクで確認した。
ASR継続試験も認識・翻訳・TTSのサーバーは固定応答で、実モデルの品質試験ではない。
実Tauri、sidecar、音声capture、配送、OSC、scheduler、PipeWire出力は製品経路を通す。
TTS ON→OFF→ONで翻訳3件・OSC3件に対してTTS2件となり、OFF中もcaptureが継続した。

100%表示の主要文字コントラストは入力12.83:1、通常操作4.71:1、保存操作5.30:1（disabledの薄色は除く）。
操作領域は36px以上、150%では54px以上。長いパスで横にはみ出さず、入力→InstructionのTab移動を実操作で確認した。
既存のログ/入力比率、送信ボタン非表示設定は保存後も保持した。MainSection・言語選択・クイック設定の実装は変更していない。

証跡は`.superpowers/sdd/2026-10-29-tts-settings-ui/recovery-*.log`と`tmp/tts-settings-recovery/`。
配布候補は`build/tts-settings-artifacts/`。モデル・OCR重みの非同梱検査を通過し、外部公開・pushはしていない。
Windows実機、VRChat/HMD、物理マイク、聴感は未検証。
