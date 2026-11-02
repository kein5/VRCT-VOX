# VRCT-VOX 機能仕様書

VRCT-VOXの機能、API、データ、振る舞いの約束をまとめた文書の入口。ここから全部の文書に行ける。

製品の目的と利用者は`PRODUCT.md`、見た目と操作は`DESIGN.md`、開発の進め方は`AGENTS.md`と`docs/development.md`にある。この仕様書は、それらが決めた方針のもとで「いま何がどう動くか」を書く。

## 文書の一覧

| 文書 | 書いてあること | 種類 | 作り方 |
|---|---|---|---|
| [全体像](overview.md) | 構成要素、外のシステムとの関係、画面とページ | 説明 | 手書き |
| [IPCプロトコル](ipc-protocol.md) | UIとサイドカーの間のメッセージの形、状態コード、起動、ロック、監視 | 決まり | 手書き |
| [横断的な振る舞い](cross-cutting.md) | エラー、保存、同意、秘密情報、国際化、停止とミュート、初期化中の扱い | 決まり | 手書き |
| [データ形式と保存](data-and-persistence.md) | 主なデータの形、`config.json`、ログやモデルのファイル、環境変数 | 参照 | 手書き |
| [外部インターフェース](external-interfaces.md) | OSC、WebSocket、OBS、クラウド、音声サーバー、ウィンドウ、Tauriのコマンドとイベント、ホットキー | 参照 | 手書き |
| [ユースケース](use-cases.md) | 利用者がすること15件と、関係する画面・エンドポイント | シナリオ | 手書き |
| [シーケンス](sequences.md) | 起動、設定の変更、チャットの送信、文字起こし、読み上げと停止、APIキーの登録 | シナリオ | 手書き |
| [契約](contracts.md) | 変えてはいけない約束と、確かめているテスト | 決まり | 手書き |
| [未決事項](open-issues.md) | 調べて見つかった食い違いと、決まっていないこと | 記録 | 手書き |
| [用語集](glossary.md) | 画面の言葉とコードの名前の対応 | 参照 | 手書き |
| [IPCエンドポイント一覧](reference/ipc-endpoints.md) | 全エンドポイント、処理する関数、初期化前の扱い、UIの受信先 | 参照 | 生成 |
| [エラーコード一覧](reference/error-codes.md) | 全エラーコード、分類、既定の文言、UIの処理の有無 | 参照 | 生成 |
| [設定キー一覧](reference/config-keys.md) | 全設定キー、型と検証、既定値、保存のしかた | 参照 | 生成 |

## 目的別の入口

| したいこと | 読むところ |
|---|---|
| あるエンドポイントが何をするか知る | [IPCエンドポイント一覧](reference/ipc-endpoints.md)で処理する関数を見て、`src-python/controller.py`を読む |
| 新しい設定を足す | [設定キー一覧](reference/config-keys.md)、[設定の保存](cross-cutting.md#設定の保存)、[データ形式と保存](data-and-persistence.md) |
| 新しいエラーを足す | [エラーの扱い](cross-cutting.md#エラーの扱い)、[エラーコード一覧](reference/error-codes.md) |
| 機能の流れを追う | [ユースケース](use-cases.md)から[シーケンス](sequences.md)へ |
| 外部のアプリと連携する | [外部インターフェース](external-interfaces.md) |
| 変更が何かを壊さないか確かめる | [契約](contracts.md) |

## 更新の決まり

- `reference/`の3つの一覧はコードから生成する。手で編集せず、`python tools/spec_catalog.py --write`で作り直す。
- `python tools/dev.py check`は`tests/devtools/test_spec_catalog.py`で一覧が最新かを確かめる。エンドポイント、エラーコード、設定キーを変えたら、同じ変更で一覧も作り直す。
- 手書きの文書は、振る舞いを変えた変更と同じプルリクエストで直す。文書は機能ごとに小さく保ち、同じことを2か所に書かず、リンクでつなぐ。
- 実装と食い違う記述を見つけたら、どちらが正しいかを確かめる。決められなければ[未決事項](open-issues.md)に書く。
- ファイルや関数の場所は、行番号ではなくファイル名と名前で書く。行番号はすぐに変わるためである。

## この仕様書が採り入れた考え方

文書の構成を決めるために、仕様書・API文書の作り方の原典を調べた（2026-11-02。調査の記録は手元の`~/research/functional-spec-practices/`にある）。採り入れたことと、その出典は次のとおり。

| 考え方 | この仕様書での形 | 出典 |
|---|---|---|
| 参照の文書は製品の構造に合わせて並べ、事実だけを書く。説明や手順と混ぜない | 一覧（参照）と、決まり・シナリオの文書を分けた | [Diátaxis: Reference](https://diataxis.fr/reference/) |
| APIの参照は製品のコードから生成すると、コードに忠実なまま保てる。ただし生成した参照だけでは文書として足りない | エンドポイント、エラーコード、設定キーは生成し、プロトコルと振る舞いは手で書いた | [Diátaxis: Reference](https://diataxis.fr/reference/)、[LSP 3.17のMeta Model](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) |
| 文書の問題で多いのは、あいまい、不完全、誤り、古い、である | 生成と検査で古くなるのを防ぎ、未決のことは未決事項に分けて書いた | [Uddin & Robillard, How API Documentation Fails (IEEE Software, 2015)](https://www.cs.mcgill.ca/~martin/papers/ieeesw2015.pdf)、[Aghajani et al., Software Documentation Issues Unveiled (ICSE 2019)](https://emadpres.github.io/pdfs/icse2019.pdf) |
| メッセージの規約は、共通の基本プロトコル（メッセージの形、要求と通知の違い、エラーの形）と、個々のメッセージの説明に分ける。通知には応答を返さない | [IPCプロトコル](ipc-protocol.md)と一覧に分け、要求と通知を区別した | [LSP 3.17 Base Protocol](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)、[JSON-RPC 2.0](https://www.jsonrpc.org/specification)、[AsyncAPI 3.0.0](https://www.asyncapi.com/docs/reference/specification/v3.0.0) |
| 複数の構成要素にまたがる決まりは1か所にまとめる | [横断的な振る舞い](cross-cutting.md)を設けた | [arc42 §8 Crosscutting Concepts](https://docs.arc42.org/section-8/) |
| 実行時の流れは、重要な場面、外部とのやり取り、起動と停止、エラーから代表を選んで書く。数を多く書くことは重要ではない | [シーケンス](sequences.md)を6場面に絞り、エラーの分岐を入れた | [arc42 §6 Runtime View](https://docs.arc42.org/section-6/)、[C4 Dynamic diagram](https://c4model.com/diagrams/dynamic) |
| 仕様には実際の利用場面と、未決事項を書く。冒頭に目次となる全体像を置く | [ユースケース](use-cases.md)、[未決事項](open-issues.md)、このページの一覧 | [Spolsky, Painless Functional Specifications Part 2](https://www.joelonsoftware.com/2000/10/03/painless-functional-specifications-part-2-whats-a-spec/) |
| 大きな文書は更新されない。小さく分けた文書なら更新される見込みがある | 機能ごとの小さな文書に分け、このページから引けるようにした | [Nygard, Documenting Architecture Decisions](https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions) |
| 文書をコードと同じ道具（Git、レビュー、自動テスト）で扱い、文書のない変更を止められるようにする | 一覧の検査を`check`に入れた | [Write the Docs: Docs as Code](https://www.writethedocs.org/guide/docs-as-code/) |
| 契約は、相手とのやり取りの約束を確かめるテストで守る | [契約](contracts.md)ごとに確かめているテストを書いた | [Fowler, ContractTest](https://martinfowler.com/bliki/ContractTest.html)、[Robinson, Consumer-Driven Contracts](https://martinfowler.com/articles/consumerDrivenContracts.html) |

調べても分からなかったこと:

- 生成や契約テストで文書のずれがどれだけ減るかを測った研究は見つからなかった。上の判断は、原典の主張と、文書の問題を調べた研究に基づく。
- ユースケースの書式の原典（Cockburnのテンプレート）は取得できなかった。ユースケースは、きっかけ、主な流れ、うまくいかないとき、関係するもの、の簡単な形にした。
