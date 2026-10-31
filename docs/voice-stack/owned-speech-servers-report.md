# 同梱speech.cppのGUI起動・停止（2026-10-29）

P5-Bの製品接続を実装した。既存の外部HTTP経路を維持し、日本語TTS・多言語TTS・ASR+VADを
GUIから必要なときだけ起動できる。[設計](../superpowers/specs/2026-10-29-owned-speech-servers-design.md)と
[実装計画](../superpowers/plans/2026-10-29-owned-speech-servers.md)に対応する。
Linuxの開発用配置で確認した結果であり、インストーラーやAURパッケージの完成ではない。

## 利用の流れ

1. 詳細設定の音声欄にある「同梱speech.cppサーバー」で、利用許諾のある既存GGUFを指定して保存する。
   ASRにはVADも必要。保存だけでは読み込み・録音・発声を始めない。
2. 必要な枠を起動し、準備完了を確認する。任意の声GGUFを指定した場合は声名`custom`を使う。
3. TTSの対象言語枠、またはリアルタイム字幕で接続先を「同梱サーバー」にして保存する。
   ASRではモデル・入力を選び、字幕開始を別途操作する。音声経路のミュート解除も独立した操作。
4. TTS枠を停止すると共有発声キューを取り消す。ASR枠を停止するとmic/speaker字幕と未完了の配送を取り消す。
   直接VCは独立している。再起動時は全サーバー・入力とも停止状態になる。

外部URLは設定に残り、選択を戻せば使える。同梱側が停止中でも、そのURLへ暗黙に接続しない。
停止中のTTSは`speech_server_not_ready`で知らせる。サーバー起動は127.0.0.1のOS割当ポートのみ。
外で起動したプロセスを名前やPIDの探索で終了する処理はない。

## 実装と検証

- 固定speech.cpp0.9.0、CPU/Vulkanの実行ファイルSHA256照合、通常GGUFファイル検証。
  モデルの自動取得やモデル同梱なし。[配布部品・通知](speechcpp-bundle-report.md)を継承する。
- 専用owner threadと既存Linuxネイティブsupervisorで寿命を管理。非同期起動120秒上限、終了確認3秒上限。
  終了未確認のownerを保持し再起動を拒否。親・owner thread・supervisor終了の契約試験を含む54 PASS。
- Controller/受信処理: 3つの通常handlerが塞がっていてもStopを処理し、待機中の古いStartを拒否。
  TTSの停止・異常終了取消、ASRの遅いfinal破棄、直接VCの独立性、設定保存・復元・終了を検証。
  音声回帰881 PASS / 15 SKIP（60.05秒）。SKIPは実モデル/ブラウザー等の明示起動が必要な試験。
- GUI: 保存と起動を分離、保存中の編集競合を防止。起動/停止の世代番号で古い応答を拒否する。
  ASRモデル一覧は接続先選択・URL・世代を照合し、同じポートを再利用しても古い一覧を採用しない。
  新規/既存ブラウザー・Controller試験53 PASS。標準Python試験1,222 PASS / 6 SKIP（14.32秒）。
  標準試験には既存依存の非推奨警告・mock下の未await警告46件があり、警告ゼロとはしていない。
- Vite build（1.61秒）、locked/offline Tauri debug build（49.29秒）、変更範囲Ruff・diff検査成功。
  Windows batch/cleanupを含む`npm run build`は使わず、Linux用のVite/Tauri段階を実行した。

試験用依存はuv、固定Playwright1.64.1/pyee13.0.1を既存キャッシュから利用した。
GUI保存中の入力消失とラベル照合の失敗は、imozuruでReact/Playwrightの公式原典と実装を確認して修正。
原典・経過は`tmp/voice-resume/research/owned-server-ui/`に保存した。

## 実モデル・ネイティブGUI

承認済みQwen3-TTS/ReazonSpeech/Sileroと既存合成入力のみを使い、外部ネットワークを分離した。
専用PipeWire上で試験し、DPMS消灯ガードを使用。実マイク・VRChat・ホスト音声経路を接続していない。

最終試験は1 PASS（76.24秒）。GUIでモデル指定→保存→起動→TTS発声→発声途中停止→
停止中の無音/外部fallbackなし→ASR字幕2件→ASR停止後に追加配送なし→起動直後の停止→
アプリ終了・再起動OFFを確認した。保持した外部HTTP fixtureは終了後も応答し、発声要求0件。
実TTSの履歴は完了1・取消1・停止中の拒否1。文字起こし精度や声の自然さの評価ではない。

| 観測 | 値 | 境界 |
|---|---:|---|
| TTS起動からready | 10.64秒 | GUI起動操作・モデル読み込みを含む |
| ASR起動からready | 3.03秒 | GUI起動操作・モデル/VAD読み込みを含む |
| 発声操作から最初の私有source音声 | 560.27ms | WebDriver click呼出し→PipeWire読取り |
| 停止操作から私有source無音 | 89.30ms | 同上、続く2秒の無音を確認 |

各値は最終試験のn=1。モデル単体のベンチマークでも、物理入力→VRChat/HMDの遅延でもない。
[メタデータJSON](owned-speech-servers-results.json)に原音・モデル・絶対パスは含めていない。
元のローカル証拠は`tmp/voice-resume/owned-speech/native3/`。

初回試験は新しい非同期フォームの表示待ちが不足し、2回目は合成入力を2回分キューに置いたまま
1回分の完了時間で判定して失敗した。テスト側を、実コントロール表示の確認・発話ごとの完了待ちに修正。
アプリのバッファや停止期限は変更していない。これらの失敗結果は最終合格と区別して保存している。

## 残る確認

Linux配布先のresources/config/cache分離、VRCT-VOXのアプリ識別・更新先、インストール/削除・更新試験は後続。
モデルの配布許諾確認は実行ファイルのライセンスと別。ユーザー提供Mia2026は引き続き検証専用で非同梱。
同梱枠でのIrodori/任意voice GGUFの実ロード、CPU推論性能、Windowsネイティブ管理、物理音声/VRChat/HMD、
聴感、制御したGPU競合は未検証。先の30分混在試験は[別の結果](combined-voice-gpu-isolated-results.json)であり、
今回の同梱起動経路で30分再試験したとは扱わない。

次はユーザー指定のAUR等の配布方式を検討する。登録・公開・push・上流連絡/PRは実施していない。
実装がひととおり揃った後のTrail of Bits Skills監査は、配布前の未実施ゲートとして保持する。
