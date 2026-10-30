# Semgrep指摘の是正（2026-10-29）

アプリの修正先は `frail-walrus` worktree（開始時 HEAD `ac6d2c431f4e`）。元のスキャン対象checkout の HEAD `79419a1f` とは異なる。アプリの変更はこのworktreeの未コミット差分であり、元のcheckoutへ反映・マージしたという意味ではない。

既存のTTS・RVC／Quick Chat担当エージェント `44b1c384-ce49-4c0e-89a6-9be9f713ad30` に編集範囲と検証結果を共有し、主担当が修正した。新しいサブエージェントは作成していない。

## 変更と原典

- 3つのワークフローの外部Action参照15か所を、開発元リポジトリで確認した完全なコミットSHAへ固定。既存のメジャーバージョンを保った。`setup-uv@v6` は注釈付きタグをcommitへ解決し、Rustの固定先は `default: stable` も確認した。参照の記録はローカル保管の `action-refs.json`（公開対象外）。固定先の更新時も開発元の参照と差分を確認する。[GitHubの公式対策](https://docs.github.com/en/actions/reference/security/secure-use)
- `release.yml` の `run` 内に残っていた `env.VERSION` の式展開をPowerShellの環境変数参照へ変更。バージョンを単一行の数値・識別子形式に制限してから `GITHUB_ENV` に記録する。手動起動、`contents: read`、候補成果物のみを保存する既存の設計を維持した。[GitHubの入力受渡し方針](https://docs.github.com/en/actions/reference/security/secure-use#use-an-intermediate-environment-variable)
- `controller.py` のログ／設定フォルダを開く2か所を `shell=False` に変更。引数配列と既存のWindowsパス変換を維持し、スペース・日本語・`&`・`%TEMP%` を1つのパス引数として扱う。[Python 3.11のsubprocess仕様](https://docs.python.org/3.11/library/subprocess.html#security-considerations)
- 接続確認の既定URLをHTTPSへ変更。証明書検証とタイムアウトを維持し、TLSエラー時にHTTPへ戻さない。[Requestsの証明書検証](https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification)
- YOLOXエクスポートの `torch.load` に `weights_only=True` を明示。既存のNumPyスカラー許可リストは維持。PyTorch 2.7の既定値だけに依存せず、`TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` が未指定引数へ与える影響を避ける。[PyTorch 2.7の仕様](https://docs.pytorch.org/docs/2.7/notes/serialization.html#environment-variables)
- [summarize_semgrep.py](../../tools/summarize_semgrep.py) を追加。既存manifestとraw JSONを読み、raw件数・重複除去後件数・診断・解析範囲の不足を分けて出力する。元データを書き換えず、不完全な解析は終了コード1、欠損／不正な入力は2で返す。`complete` は指定されたスキャン計画の記録に限る。[Semgrepの終了コード](https://docs.semgrep.dev/cli-reference)、[出力スキーマ](https://github.com/semgrep/semgrep-interfaces/blob/main/semgrep_output_v1.atd)
- スキャンに使われた外部の `run-scans.sh`（外部スキルの補助スクリプト） も修正。終了コード0/1でも `errors`、スキップされたルール／ファイルがあれば `partial=true` とし、その件数をmanifestへ記録する。不正な結果配列を「検出0」としない。これだけは元のインストール先へ適用済みで、隣に回帰テストを追加した。既存の `static_analysis_semgrep_3` は変更していない。

## 元の21件の対応

番号は初回レビューの `review.json` と共通。行番号は古いスキャン対象のもの。

| ID | 元の箇所 | 今回のworktreeでの対応 |
|---|---|---|
| 1 | overlay_image.py:517 | 長い関数宣言。誤検知と判断し、変更なし。 |
| 2 | overlay_tooltip.py:82 | 描画座標の算術。難読化コードではなく、変更なし。 |
| 3 | SupportersContainer.jsx:27 | 静的な案内文。誤検知と判断し、変更なし。 |
| 4, 5 | controller.py:3468,3473 | シェルを介さない起動へ修正。 |
| 6 | yolox_chatbox_export.py:51 | `weights_only=True` を明示。監査ルールは引き続き検出する（下記）。 |
| 7, 10, 11 | release.yml:16,101,106 | checkout・Node・PythonのActionをSHA固定。 |
| 8, 9, 13 | release.yml:29,72,151 | タグ起動・タグ名埋め込みの旧処理は、このブランチで既に削除済み。残存するVERSION式展開も今回除去。 |
| 12 | release.yml:111 | 旧actions-rs/toolchainは既にdtolnayへ置換済み。後継Actionを今回SHA固定。 |
| 14, 15, 16 | release.yml:170,180,190 | 旧リリース公開Actionはこのブランチで既に削除済み。 |
| 17 | utils.py:361 | 接続確認の既定URLをHTTPSへ変更。 |
| 18 | src-tauri/src/lib.rs:42 | current_exeは起動ログ位置の取得。悪用経路は今回確認できず、変更なし。 |
| 19 | utils/dev_sidecar/src/main.rs:41 | Win32のプロセス終了連動用FFI。unsafeという構文だけでは脆弱性を確定できず、変更なし。 |
| 20 | utils/dev_sidecar/src/main.rs:45 | 開発用sidecarがPython環境の位置を解決。権限昇格等の悪用経路は確認できず、変更なし。 |
| 21 | utils/dev_sidecar/src/main.rs:87 | コマンドライン引数を配列で転送。シェル文字列として実行しておらず、変更なし。 |

機械可読の対応記録: [semgrep-remediation-2026-10-29.json](semgrep-remediation-2026-10-29.json)。検出を消すための `nosemgrep` やルール除外は追加していない。

## 検証

- アプリ・ワークフロー・集計・配布の関連pytest: **49成功**。既存依存ライブラリの非推奨警告5件。
- 実際に適用したスキャン補助スクリプトの回帰pytest: **10成功**。模擬Semgrepで終了コード0/1/2/7、診断あり、スキップあり、不正JSON配列を検証。ネットワーク不要。
- 新規PythonコードとテストのRuff、変更したPythonツールの構文検証、補助スクリプトの `bash -n`、修正差分の `git diff --check`: 成功。YOLOXツールの既存docstringにあるバックスラッシュのSyntaxWarningは、ホストPython 3.14による構文確認時に表示された。
- Semgrep **1.182.1 / CE** で対象6ファイルを修正前後比較。開発元から固定commitで取得した関連6ルールを使用し、**19件 → 1件、解析診断0件**。これは元の12ルールセット／Proスキャンの全件再実行ではない。
- 残る1件はTrail of Bitsの `pickles-in-pytorch`。ルールは `torch.load(...)` に一致し、`weights_only=True` を除外条件にしていない。安全設定の明示は確認したが、任意のモデルが安全であることや実重みの互換性まで証明したものではない。
- Windows実機でのExplorer／PowerShell、CI実行、実際のYOLOX重みの変換は未実施。既存GUI担当のテスト結果は、この49件に含めていない。

再実行例:

```bash
.venv_linux/bin/python -m pytest -c tests/voice/pytest.ini \
  tests/voice/test_security_regressions.py tests/voice/test_semgrep_report.py \
  tests/voice/test_fork_distribution_identity.py tests/voice/test_distribution_artifacts.py -q

python3 tools/summarize_semgrep.py path/to/static_analysis_semgrep_3/scans.json
# 元の解析診断があるため、JSONを出力した上で終了コード1になる。
```

修正前後の限定スキャン・使用ルール・テストログはローカル保管。公開リポジトリには含めていない。

## 元のスキャン結果の訂正

raw合計は23件（ERROR 8 / WARNING 8 / INFO 7）、重複除去後は**21件（ERROR 6 / WARNING 8 / INFO 7）**。12スキャン・報告されたファイルの和集合582という数字は確認できた。

一方、raw JSONには**48診断（完全一致の重複を除くと36）**があり、5スキャンに影響している。内訳はRule parse error 15、Timeout 4、PartialParsing 13、Other syntax error 16。補助スクリプトの修正は今後の誤報を防ぐもので、過去の解析漏れを埋めたという意味ではない。

Java等の第三者ルール解析失敗、Apiiroのタイムアウト、ロケールYAMLやPowerShellのパーサー診断は、個別のカバレッジ不足として残る。`p/yaml` はHTTP 404で除外されているため、汎用YAMLの包括的検査も行われていない。元結果を「全解析成功」「秘密情報なし」「安全性確認済み」とは扱わない。

訂正済み集計 `corrected-summary.json` と原本 `scans.json` / `results.sarif` はローカル保管。元データを用意した上で、上のコマンドから再集計できる。

## imozuruの記録

詳細レポート・抜き書き・調査地図・調査ログはローカル保管。参照した公式原典は「変更と原典」にリンクを記載した。

公式原典9本を保存し、PythonのガイドからPEP 324、GitHubのガイドからscript injections、PyTorchの説明からtorch.load APIへたどった。6論点すべてに原文の場所が付いたため1周目で区切った。取得失敗なし。検索・原文取得・引用の検証記録を保存済み。
