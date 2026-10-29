# 上流へ還元する差分候補（ローカル草案、未送信）

連絡・issue・PR（draft含む）は明示的な指示があるまで作成しない。
以下のpatchは元コミットのうち指定ファイルだけを取り出したレビュー用資料。
上流最新HEADへ適用・再試験済みとは扱わない。公開前に現行CONTRIBUTINGと重複修正を確認する。

## 候補1: Chatbox sample playerのPOSIXキー入力

**PR題案:** Support nonblocking POSIX console input in chatbox sample player

Linuxでinteractive playbackを拒否していたCLIを、P/Q/R + Enterで操作できるようにする。
fd readinessを確認して1byteずつ読み、TextIOWrapperの先読みによるコマンド取りこぼしを避ける。
Windowsのmsvcrt操作は保持する。EOFは終了として扱う。

元コミット`c8dcc42a`のうち`tools/chatbox_sample_player.py`、そのテスト、READMEだけ。
[レビュー用patch](upstream-candidates/01-posix-chatbox-input.patch)。TTS、モデル、fork名変更を含めない。
実PTY、pipe EOF、Windows APIのモックを含む回帰を本forkの標準suiteで検証した。
Windows実コンソールは別PCで確認が必要。

## 候補2: 開発sidecarのUnix起動

**PR題案:** Launch the development Python sidecar natively on Unix

Windows固定の`Scripts/python.exe`に対し、Unixでは`bin/python`を選ぶ。
UnixのexecでPIDとstdioを保ち、sidecar終了時にPythonだけが残らないようにする。
Windows Job Objectの処理は維持する。

元コミット`66b16e6d`から`utils/dev_sidecar/src/main.rs`とモデル不要のprocess契約テストを抽出。
[レビュー用patch](upstream-candidates/02-unix-dev-sidecar.patch)。当時の本家側名称を保持しており、
今回の`vrct-tts-sidecar`への改名は含めない。本forkで11件のLinux実プロセステストが成功。
適用先でのWindows CIと、現行上流のvenv選択仕様との照合が必要。

## 次に独立化できる候補

- `c8dcc42a`の残り: Windows APIを境界で差し替え、Linuxでも契約テストを実行する修正。
  `platform_test_support.py`を含む小さなテスト移植PRに分ける。
- `22ef68f2`のDPMSガード: KDE消灯中の描画停止をアプリ不具合と誤判定しないGUI試験補助。
  VRCT-TTS音声試験とは切り離した最小再現・ガードを提案候補にする。

`speech.cpp`管理、VC、ASR字幕、翻訳発声、今回のfork配布設定は別の機能群。
採用を前提とした一括PRにしない。`integrations/seed_vc`のGPL表示や依存・モデルの条件を
MITの共通不具合修正へ混ぜない。ライセンス残件は[台帳](licensing.md)に保持する。
