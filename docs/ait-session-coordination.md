# Aitの別セッションとの連携

2026-10-29にローカルのAit 0.1.21で、セッション一覧取得、実行中セッションへの送信、相手からの返信まで確認した。

## 使用方法

対象セッションと同じワークスペースのルートから実行する。Python標準ライブラリのみを使用する。

```bash
python3 tools/ait_coordination.py list
python3 tools/ait_coordination.py status <相手のAitエージェントID>
python3 tools/ait_coordination.py activity <相手のAitエージェントID> --limit 5
```

連絡内容をUTF-8のファイルへ書いて送信する。

```bash
python3 tools/ait_coordination.py send <相手のAitエージェントID> \
  --message-file /tmp/coordination-message.txt \
  --message-id <今回の連絡に固有のID>
```

`CODEX_SESSION_ID`をAitのセッションメタデータと照合して送信者を特定する。Codex以外や通常の端末から使う場合は、一覧で確認した自分のAitエージェントIDを`--caller-id`に指定する。AitのIDとCodexのセッションIDは別物。

`activeTurnBehavior: "steer"`で実行中の相手に追加情報を渡す。相手が待機中なら新しいターンが始まる。これは単なる受信箱への記録ではなく、相手の作業へ入力される。担当範囲、編集対象、重要な発見を簡潔に伝え、依頼していない作業の追加や通知の往復を避ける。

`accepted: true`は受付完了を示す。相手が読んで対応した証明は、返信または`activity`で確認する。通信が途中で切れて結果が不明な場合は、同じ`--message-id`で再試行し、重複した指示を避ける。

## 接続と権限

- 対象はLinuxのAit Desktop。同一ユーザーが起動したdaemonを、正確な`--data-dir`で照合する。既定のデータディレクトリは`~/.ait-server-desktop`。
- 接続先はdaemonの`--listen`引数にあるloopbackアドレスに限定する。デスクトップ版は動的ポートなので、7316を固定値にしない。
- Desktopがdaemonに渡す`AIT_SERVER_TOKEN`を、そのプロセスの環境からメモリ上だけで取得する。トークンを表示、ファイル保存、コマンド引数への展開、Codexグローバル設定への書き込みはしない。
- 0.1.22では環境変数がない場合、同じDesktopデータディレクトリの、同一ユーザー所有の`local-api.token`を読む。2026-10-30に既存セッションへの送信・返信を確認。値をログや成果物に残さない。
- HTTPプロキシとリダイレクトを使わず、`/v1/server/info`のserver IDを選択したデータディレクトリのIDと照合する。
- 送信・状態参照・履歴参照の対象は同一ワークスペースに制限する。自分自身への送信は拒否する。
- sandboxからホストの`/proc`やlocalhostへアクセスできない場合は、通常の承認付きコマンド実行を利用する。今回の検証もその方法で実行した。daemonの再起動、設定変更、DBの直接編集は不要。

このヘルパーは都度実行するCLIであり、常駐監視や新しいMCP接続のグローバル登録は行わない。

## 今回の担当調整

セキュリティ監査セッションは`tools/ait_coordination.py`、この文書、`docs/security/`を担当する。別セッションはAppImage関連の実装、パッケージング、ビルドCIとその試験を担当する。相互に担当ファイルを編集・コミットしない旨の返信を確認した。

## Provider execution failedの観測

2026-10-29 15:20:27 JSTに、監査セッションでCodexの`poll`が`provider session operation failed`となり、Aitが`Provider execution failed`を記録した。daemonは0.1.21、Codex CLIは0.164.0。15:20:16頃に別セッションへのMCP送信が受理されたことは確認したが、時間的な前後関係だけで原因とは断定しない。

その後、両セッションの実行継続と、相手からの返信を確認した。daemonの診断には具体的な失敗イベントやスタックがなく、根本原因は未特定。過去の0.1.20向け修正が今回の原因を説明するとは限らない。必要な証拠は時刻、バージョン、`poll`の失敗分類に留め、認証情報や会話内容を公開しない。

## 公式ソース

調査したコミット: `3aebf9d90d7088e4b970dbd5d817151707e026e0`。実機のAPIも照合済み。

- [MCPエンドポイントとプロトコル](https://github.com/ait-app/ait/blob/3aebf9d90d7088e4b970dbd5d817151707e026e0/crates/api/src/mcp.rs)
- [list_agents / send_agent_prompt等のスキーマ](https://github.com/ait-app/ait/blob/3aebf9d90d7088e4b970dbd5d817151707e026e0/crates/api/src/mcp/catalog.json)
- [実行中のCodexへのsteer](https://github.com/ait-app/ait/blob/3aebf9d90d7088e4b970dbd5d817151707e026e0/docs/decisions/providers/adr-046-codex-streaming-and-steering.md)
- [旧Hub / Chat / Loop APIの廃止](https://github.com/ait-app/ait/blob/3aebf9d90d7088e4b970dbd5d817151707e026e0/docs/decisions/daemon/adr-045-remove-hub-chat-loop.md)
- [Desktopのdaemon起動・トークン管理](https://github.com/ait-app/ait/blob/3aebf9d90d7088e4b970dbd5d817151707e026e0/apps/desktop/src/daemon/rust-daemon.ts)
