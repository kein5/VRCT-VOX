# AIT「Provider execution failed」調査

確認日時: 2026-10-28 20:26 JST（11:26 UTC）。対象: `ait-app/ait`。

## 結論

今回の「Codexの子エージェントが親へ連絡した直後に親の処理が止まる」症状に一致する修正は、**[PR #509](https://github.com/ait-app/ait/pull/509)としてマージ済み**。マージは2026-10-28 14:32:54 JST、コミットは`89ea11dd3724c1b08d33508c15d4531a1176d52d`。

調査時点の**公開安定版は0.1.20で、この修正を含まない**。0.1.20の元タグと再ビルドの両方で、親宛て通知を拒否する同一の実装を確認した。現在のmainと公開nightlyのソースには修正がある。0.1.21の変更履歴・リリース準備にも収録されているが、公開Releaseは確認できなかった。

したがって、現時点の報告は新規の未修正バグとしてではなく、**#509に関連する0.1.20での発生証拠と安定版への収録確認**として扱うのが適切。

## 既存Issue・PRとの照合

| 項目 | 確認結果 | 今回との関係 |
| --- | --- | --- |
| [PR #509](https://github.com/ait-app/ait/pull/509) | マージ済み。子→親の`send_message`で親のturnが失敗する症状を明記 | 直接一致。作成・通信・中断を分けて扱う修正 |
| [PR #497](https://github.com/ait-app/ait/pull/497) | マージ済み、0.1.20に収録。新版`subAgentActivity`を扱うコードを追加 | 関連する実装の前段。#509はその活動処理を修正 |
| [PR #510](https://github.com/ait-app/ait/pull/510) | 14:47:47 JSTにマージ済み。0.1.21の準備 | #509を次版の変更内容に含む。マージは公開配布の完了を意味しない |
| [Issue #491](https://github.com/ait-app/ait/issues/491) / [PR #492](https://github.com/ait-app/ait/pull/492) | Issueは完了扱いでclose、PRはマージ済み。0.1.19に収録 | 大きなCodex履歴を読む際の32 MiB制限。今回の子→親通知とは別原因 |
| [Issue #373](https://github.com/ait-app/ait/issues/373) | 完了扱いでclose | 起動・認証・タイムアウト等のログを含む。今回と同じ原因を示す証拠はない |
| [PR #300](https://github.com/ait-app/ait/pull/300) | Codexの大きなMCP結果とタイムライン上限の修正 | 同じエラー文言が出る別の経路。エラー文言だけでは原因を特定できない |

IssueとPRの両方を、open/closedを限定せず検索した。検索語は`Provider execution failed`、`subagent`、`subAgentActivity`、`codex`など。今回の通信問題を扱う独立したIssueは検索範囲では見つからなかったが、直接対応するPR #509は存在する。検索結果の不在を、Issueが絶対に存在しない証拠とはしない。検索条件と番号は[確認時点のJSON](upstream-snapshot.json)に保存した。

## 公開配布とソースの区別

| 対象 | 確認したソース | #509の修正 |
| --- | --- | --- |
| 0.1.20の元タグ | `98503c93c1288855b2248cb3f96eac2df2a368bd` | なし |
| 現在公開されている0.1.20再ビルドの公称ソース | `bca1f98b8338f2bd6dbdd7f4e733337a564ce466` | なし |
| 確認時点のmain | `7113431099355c59170bef9b825c92bd9b5d3f23` | あり |
| 確認時点のnightly | 同上。2026-10-28 20:19:59 JST公開、prerelease | ソースにあり。インストール・実機試験は未実施 |
| 0.1.21 | 変更履歴と準備PRあり | 公開Releaseは未確認 |

[0.1.20のリリース説明](https://github.com/ait-app/ait/releases/tag/v0.1.20)は、同じバージョン番号で再ビルドし、元タグを動かしていないことを明記している。再ビルド後も表示は0.1.20で、通常の「新しいバージョン」通知は出ない。この再ビルドを再インストールしても、確認したソースには#509が含まれない。

根拠はリリース説明だけではない。[再ビルド元のコード](https://github.com/ait-app/ait/blob/bca1f98b8338f2bd6dbdd7f4e733337a564ce466/crates/provider/src/local/codex/subagents.rs#L37-L45)に親宛ての拒否分岐が残り、[コミット比較](https://github.com/ait-app/ait/compare/89ea11dd3724c1b08d33508c15d4531a1176d52d...bca1f98b8338f2bd6dbdd7f4e733337a564ce466)でも修正より4コミット前であることを確認した。

[nightly](https://github.com/ait-app/ait/releases/tag/nightly)の公称ソースは#509の子孫であり、[固定したソース](https://github.com/ait-app/ait/blob/7113431099355c59170bef9b825c92bd9b5d3f23/crates/provider/src/local/codex/subagents.rs#L37-L56)にも修正がある。nightlyは差し替わるため、判断にはタグ名だけでなくコミットを使う。

[0.1.21の変更履歴](https://github.com/ait-app/ait/blob/7113431099355c59170bef9b825c92bd9b5d3f23/CHANGELOG.md#L3-L7)と[準備報告](https://github.com/ait-app/ait/blob/7113431099355c59170bef9b825c92bd9b5d3f23/docs/reports/releases/release-0.1.21.md)に今回の修正が記載されている。一方、確認時点のGitHub latest APIは`v0.1.20`、`v0.1.21`のRelease取得は404だった。これは未公開draftの不存在まで示すものではない。

## ローカルで確認した事実

障害時の記録はAIT Desktop/daemon 0.1.20、Codex CLI 0.164.0。調査環境はCachyOS Linux、x86_64、カーネル`6.18.55-2-cachyos-lts`。今回もCodexのバージョンを確認した。**障害時の実行バイナリを特定ソースへ対応付けるビルドIDは未確認**であり、0.1.20という表示だけから元タグ版だとは断定しない。

2026-10-28の最後に調べた障害では、次の順序を原本から再確認した。

| 時刻（JST） | 観測 |
| --- | --- |
| 19:25:04.163 | 子のCodex rolloutに`item_completed`、`SubAgentActivity`、`kind=interacted`。宛先は親のスレッド、`agent_path=/root` |
| 19:25:04.173632 | daemonが`Native provider observation failed`を記録。`provider=codex`、`operation=poll` |
| 19:25:04.200903 | 同じ親のturnが`Provider execution failed`。`category=unknown`、`source=session` |

子のイベントからpoll失敗までは**10.632 ms**。前回保存された同一親セッションの照合記録では7件のpoll失敗のうち5件で同様の並びがあり、間隔は5.836〜24.022 msだった。残る2件にはこの原因を割り当てていない。これは「全メッセージの5/7で失敗」という発生率ではない。

静的なコード経路と#509の修正・回帰テストはこの原因を強く支持する。ただし、稼働daemonへの計測追加、元RPCの完全再生、修正版を使った実機比較は行っていない。

## 再現と検証の扱い

投稿案には、子が親へ短いメッセージを返す最小プロンプトと、匿名化したイベント形の例を載せた。この最小手順を新しい実セッションでは実行していない。進行中の作業を止める可能性のある再現操作は実施しなかった。

#509は、修正前に親turnが失敗するオフライン統合試験を示し、修正後は12件の対象試験が成功したと報告している。親・祖先・兄弟への通信、子関係の維持、中断、履歴と再起動後の復元を扱う。これは上流PRの検証報告であり、今回こちらで実行した結果ではない。上流でも実モデル再生・他OSでの検証は未実施とされている。

## 投稿案と次の判断

同じ問題の修正PRがすでにあるため、新規Issueを作る場合も冒頭で#509を参照する。目的は0.1.20での発生証拠を共有し、どの安定版配布物から修正が使えるかを確認すること。投稿時にはRelease情報を再確認し、安定版が公開済みなら収録状況の記述を更新する。

今回の実施範囲は公開情報と既存ログの読み取り、およびこの3ファイルの作成。Issue・コメントの送信、AITの更新・再起動・設定変更、モデルを呼ぶ再現試験は行っていない。
