# P5-A: 固定speech.cpp配布部品の作成

## 目的と範囲

ユーザー承認済みのspeech.cpp同梱を、まず再現可能な配布部品として用意する。
既存のHTTP/Realtime接続を変えず、モデルと参照音声を含まない部品を作る。
実装は先行する複合音声の30分試験の判定後に開始する。
これはP5全体の完成ではない。GUIの所有サーバー管理、アプリ識別変更、Linuxパッケージ、
更新経路、Windows実機受入れは後続工程として残す。

基準: [実装仕様](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md) §§7–10、
[追加承認](../../voice-stack/completion-ledger.md)のP5要件。
通常の実装・試験・ローカルコミットを閉ループで進める既存指示に従う。
モデル取得、公開、上流連絡、PRはこの作業に含めない。

## 採用案と代替

| 案 | 利点 | 費用・制約 | 判断 |
|---|---|---|---|
| 固定した公式releaseから実行ファイルだけを取り出す | 既に実試験した版と整合し、ビルド環境を利用者へ要求しない | アーカイブ検証・静的依存の通知・OS依存の明示が必要 | 今回採用 |
| 固定sourceから本プロジェクトで再ビルド | コンパイラ・依存・RUNPATHを管理できる | CIと再検証範囲が増え、今回の同梱に直ちには不要 | 公式成果物の移設・依存・ライセンス確認が成立しない場合の代替 |
| 利用者が外部speechを導入するだけ | 配布サイズが増えない | 承認された同梱要件を満たさない | 既存互換手段として保持 |

この選択と以下のファイル配置は実装担当の判断。利用者が個々の配置を指定したものではない。

## 固定するもの

- speech.cpp **0.9.0** / source **49f022a48bc1c7e797aa64dd08d2d9655baf299e**。
- Linux x86-64 Vulkan ZIP: **31,684,675 bytes**、SHA256
  `b435fd101a68d9c54d1d41ccc10ab87cce4a012a8564639568e914b67aa7d69c`。
- Linux x86-64 CPU ZIP: **5,471,367 bytes**、SHA256
  `e2e9a260fde6242e43f7fa57c658321c798d4f1f855b1adf973dd50361b5805b`。
- 配布部品ごとに1種類を明示的に選ぶ。実行中に別版・CPU/GPUへ暗黙に切り替えない。
- upstreamのglibc要件は2.34以降。Vulkan版はOSのVulkan loader/driverが必要。
  このPCで動くことを、すべてのLinuxで動くこととは扱わない。
- GGMLはsubmodule **cbdeccfd49ec9c702c175c273d36c47520cf4710**。
  cpp-httplib/miniaudioと静的GCCランタイムの通知も追跡する。

原典: [release](https://github.com/nyosegawa/speech.cpp/releases/tag/v0.9.0)、
[固定build workflow](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/.github/workflows/build.yml)、
[固定CMake](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/CMakeLists.txt)。
原文・取得記録: `tmp/voice-resume/research/speech-bundle/`。

## 配布部品の契約

`tools/speechcpp_bundle.py`が開発・パッケージ作成時だけ動く。
通常起動からダウンロードせず、CLIはローカルZIPまたは明示した`--download`を受ける。
取得URL、正確なサイズとSHA256は版管理したmanifestから選ぶ。任意URLは受け付けない。
本体の同梱承認をモデル取得の同意へ拡張しない。

生成先は次の小さな部品に限定する。

```text
speechcpp/
  speech
  bundle.json
  notices/
    NOTICE.md
    speech.cpp-LICENSE
    ggml-LICENSE
    cpp-httplib-LICENSE
    miniaudio-LICENSE
    GCC-COPYING3
    GCC-COPYING.RUNTIME
```

アーカイブ全体のサイズとハッシュを検証してから、正確に1個の通常ファイル`speech`だけを読む。
`extractall`は使わず、ZIP内のpathやsymlinkを出力へ反映しない。
libspeech/headerはこのHTTPプロセス連携では不要なので同梱しない。
モデル、音声、RVC/Seed runtime、OCR重みをこの部品へコピーしない。
本体と全通知のサイズ・SHA256を`bundle.json`に記録し、通知の原文は版管理する。

既存の生成先は上書きしない。不正・中断した取得やコピーでは、この実行が作った一時物だけを除去する。
完成manifestを最後に作り、検証に失敗した部品を完成品として返さない。
依存追加は不要で、Python標準ライブラリとuvで実行可能とする。

## ライセンス

speech.cpp、GGML、cpp-httplibは固定原文のMIT通知を保持する。
miniaudioは原文の二重ライセンスを保持する。GCCランタイムはGPLv3とRuntime Library Exception 3.1
の両文書を保持し、speech.cpp本体のMITだけで配布部品全体を説明しない。
原典: [GCC 11.4 COPYING.RUNTIME](https://github.com/gcc-mirror/gcc/blob/releases/gcc-11.4.0/COPYING.RUNTIME)、
[COPYING3](https://github.com/gcc-mirror/gcc/blob/releases/gcc-11.4.0/COPYING3)。
OSのlibc/Vulkan loader/driverはこの部品では再配布しない。
本工程の確認だけでVRCT-TTS全体の最終ライセンス監査が済んだとは扱わない。

## 受入れと失敗時

モデル不要の自動試験で、正常な小さなZIP、内容改ざん、切断、サイズ超過、重複speech、
symlink speech、通知の欠落/改ざん、既存出力の保護、非同梱ファイルの除外を確認する。
検証処理を`assert`だけで実装せず、最適化したPythonでも不正入力を拒否する。

実ZIPを取得・照合し、生成部品を別の一時ディレクトリへ移して、空の作業ディレクトリと
ユーザー環境に依存しない条件で`--version`を実行する。CPU版とVulkan版は別に記録する。
ELF依存を読み、意図しない同梱ライブラリや絶対RUNPATHへの依存を検出する。
モデルを取得しないことを確認し、禁止資産検査も実行する。
ここでは推論性能・GUI所有プロセス・配布インストールの成功を主張しない。

## 後続の接続点

次工程はこの検証済み部品を参照する所有サーバー管理を作る。
日本語TTS・多言語TTS・ASR+VADを必要なときだけ別プロセスで開始し、127.0.0.1へbindする。
外部サーバーの設定を保存したまま同梱版を選べること、起動中止・異常終了・アプリ終了で
所有プロセスを回収すること、再起動時にモデルロードや録音を勝手に始めないことが要件となる。
その実装API・UI・寿命管理は別の短い設計/実装計画で確定する。
