# VRCT-TTS 配布境界の分離（2026-10-29）

ユーザーの5項目に対し、除外・公開経路・identity・説明・上流候補の変更を実装した。
**完成したWindows ZIP/NSIS、Linux製品package、最終ライセンス監査は未検証。公開可能とはまだ判断しない。**

## 変更と確認範囲

| 項目 | 実装したこと | 残る確認 |
|---|---|---|
| OCR | CPU/CUDA specからOCR/rapidocrディレクトリ全体収集を除去。OCR通知3ファイルと元LICENSE/NOTICEだけを明示収集。hook展開後のdatas/binariesもsource/destinationで除外 | Windowsの実PyInstaller成果物 |
| 配布検査 | tree、ZIP、入れ子ZIP、明示指定NSISを検査。破損/暗号化/未対応archive、読めないNSISは失敗。Tauri build、batch build、ZIP作成、CIへ接続 | 最終Windows ZIP/NSIS実物とインストール後のtree |
| ソースarchive | `.gitattributes`でOCR重みをexport対象外に。git checkout内の原本と著作権表示は保持 | GitHubで公開する実物との照合は公開前に行う |
| 公開先 | 本家HF uploadとtelemetry secrets生成を削除。workflowは`workflow_dispatch`、contents readのみ、候補の検査/CI保管だけ | Windows candidate workflow未実行。リリース公開処理は無効 |
| 更新 | NSISはforkのGitHub tag/ZIPへ固定。configの更新URLもforkへ変更。組込み更新/版一覧取得は無効、GUIは配布元からの更新を案内 | Windowsで再有効化する場合の版選択・checksum厳格化・更新/取消/復旧。AUR版では無効を維持 |
| Telemetry | SDK client/key読込みを削除し互換async APIはno-op。古いキーが残っていてもclientを作らない。初期設定OFF、GUIの無効なトグルを除去 | 翻訳等のユーザー指定API通信まで無効化したという意味ではない |
| Identity | 製品名`VRCT-TTS`、実行名`vrct-tts`、sidecar `vrct-tts-sidecar`、identifier `io.github.kein5.vrct-tts`、publisher `kein5` | Windowsインストール先/registry/共存、Linux desktop package/XDGパス移行は未検証 |
| 説明/支援 | README各言語、非公式表記、fork Releases/Issues、原作者への謝辞。GUIエラー支援先とissue templateもforkへ。元LICENSE/著作権維持 | 将来の実releaseに応じて導入手順を更新 |
| 上流還元 | 共通修正2件のpatchとPR文案をローカルに分離 | 上流最新HEADへの適用・Windows検証・送信指示。連絡/PRは未実施 |

元の制限付きOCRファイル1件だけの除外を、OCRディレクトリ/既知名とモデル拡張子に基づく
保守的な除外へ拡張した。音声用Silero VADはOCRではないため、既存依存として保持する。
Mia2026の既知資産名も引き続き拒否する。

この検査器はパスとarchive inventoryに基づく混入防止で、任意に改名・バイナリ内へ隠した
モデルの検出や全ライセンス適合性を証明するものではない。NSIS内に別archiveがあれば、
未検査のまま通さず失敗する。最終SBOMと配布内容台帳も必要。

ZIP作成では欠損入力とI/O失敗を成功扱いにしていた問題も修正した。
入力検査→一時ZIP→最終検査→置換の順にし、失敗時には既存の候補を保持する。

## 実行した試験

| 試験 | 結果 | 限界 |
|---|---|---|
| OCR/配布回帰の初回RED | 15 FAIL / 7 PASS | 除外範囲、入れ子、未検査NSISを検出 |
| fork identity/telemetry/更新方針RED | 5 FAIL | 変更前の本家向け設定を検出 |
| ZIP失敗伝播RED | 2 FAIL / 15 PASS | 欠損入力とdisk-full模擬 |
| 最終関連回帰 | **42 PASS**, 1.12s | 両specをAnalysis/TOC境界で実行。実ZIPと7zの非NSIS拒否、模擬NSIS inventory、実Unix sidecar。Windows freezeではない |
| 既存標準Python suite | **1,222 PASS / 6 SKIP**, 14.03s | 46 warnings。既存非推奨API/mock coroutine警告を含む |
| Vite | PASS | bundleサイズ警告あり |
| locked/offline Tauri build | PASS, `debug/vrct-tts`生成 | 開発sidecarなのでcheckout依存 |
| 実Tauri GUI | **3 PASS**, 110.10s | DPMS guard、外部network隔離、モデル不要。描画/新名称/設定反復/保存再起動/ミュート |
| Ruff（追加guard/tests） / diff check | PASS | 全体security scanではない |

関連suite:

```sh
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --offline --no-project \
  --python .venv_linux/bin/python python -m pytest \
  tests/voice/test_distribution_artifacts.py tests/voice/test_config_and_distribution.py \
  tests/voice/test_fork_distribution_identity.py tests/platform/test_dev_sidecar.py -q
```

標準suiteのtelemetry mock試験はsandbox内ではself-pipe通知が進まず失敗/待ちになり、
同一コードをsandbox外で実行すると12 PASS / 0.83s。最小socketpair送信でもsandbox内はerrno=1（Operation not permitted）を再現。faulthandlerとCPython原典を照合した。
環境差として残し、製品のtelemetry無効化を戻したり失敗をskipしたりしていない。
旧版installerからfloating最新版へ戻る1テストは、forkの固定版方針に合わせて改訂した。

生ログ、nativeスクリーンショット等: `tmp/voice-resume/fork-distribution/`。
imozuru原典・map/log: `tmp/voice-resume/research/fork-distribution/`。
調査はAIT/subagentを使わず直接実施。

## 完成したWindows成果物に必要なゲート

```sh
python tools/check_voice_distribution.py VRCT-TTS.zip VRCT-TTS_cuda.zip \
  src-tauri/bin/_internal --nsis path/to/VRCT-TTS_VERSION_x64-setup.exe
```

NSIS検査には7-Zipが必要。検査に成功したZIPとinstallerのhashを記録し、
Windows実機で導入・更新・取消・削除・本家との共存を確認する。
現行NSISは配布ZIPを取得する方式なので、installerだけの検査をpayload検査の代用にしない。
CIはこの検査が失敗したら候補artifactを保管しない。完成したinstallerの実物を
このLinuxセッションで検査したとは主張しない。

次は[Linux package案](linux-distribution-proposal.md)に沿いcheckout不要のruntimeと可変パスを整理する。
speech.cpp/外部VC/各モデルは[ライセンス台帳](licensing.md)の独立した条件を維持する。
Trail of Bits Skills監査は依頼済み・未実施で、公開前の必須ゲート。
[上流候補](upstream-contribution-candidates.md)はローカル資料だけで、PR/打診は送信していない。
