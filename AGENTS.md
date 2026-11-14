# VRCT-VOX 開発エージェント向けガイド

VRCT-VOX は、VRChat 向けに音声認識（ASR）、読み上げ（TTS）、声質変換（RVC など）、チャット読み取り（OCR）、翻訳をまとめたデスクトップアプリです。Tauri と React 18 の UI に、Python のバックエンドを組み合わせています。[VRCT](https://github.com/misyaguziya/VRCT) から派生したプロジェクトで、上流の追従や互換性は目標にしていません。

この文書は作業の入口です。詳しい内容は、下の表の正本を読んでください。

## 作業の基本姿勢

- 依頼の目的と範囲に沿って、必要な設計変更やリファクタリングは自分で判断して進めてよい。特定のファイルやモジュールを変更禁止にしたり、事前承認を必須にしたりはしていない。
- ただし、依頼にない機能追加や全面的な作り直し、外部への操作まで許されているわけではない。ユーザーの指示、公開・送信・配布の方針、ライセンスの条件は守る。
- 作業を始める前に、ブランチ、HEAD、未コミットの差分を確認する。自分が作っていない変更は消したり戻したりしない。
- 文書と実装が食い違っていたら、どちらかを機械的に正しいと決めない。説明が古いだけなのか、実装が守るべき方針を破っているのかを確かめる。判断できないときは未決として報告する。
- `docs/voice-stack/` には、日付付きの検証記録や提案が多く残っている。「未公開」「次工程」「今回」などの言葉は、書いた時点の状態を指す。採用済みの方針と区別して読む。

## 変更の対象ごとに読む資料

関係するものだけを読めば十分です。毎回すべてを読む必要はありません。

| 変更の対象 | 先に読む資料 |
|---|---|
| 製品の目的、守る機能、利用者の使い方 | `PRODUCT.md` |
| 機能、API（IPCのエンドポイント）、データ形式、横断的な振る舞い、契約 | `docs/spec/README.md`（一覧は `python tools/spec_catalog.py --write` で生成する） |
| UI の見た目、操作、アクセシビリティ | `DESIGN.md` |
| 開発環境、検証コマンド、コミット形式 | `docs/development.md` |
| 起動、ビルド、CI、配布候補 | `docs/readme_build.md`、`docs/voice-stack/release-candidates.md` |
| ブランチ、PR、依存、ダウンロードするモデル、表示する文言 | `CONTRIBUTING.md` |
| 同梱物、モデル、依存ライブラリのライセンス | `NOTICE.md`、`docs/voice-stack/licensing.md` |
| 名前、識別子、保存先、上流 VRCT との関係 | `docs/voice-stack/project-rename.md`、`docs/voice-stack/publication-and-upstream.md` |
| モデル取得の画面と同意 | `docs/voice-stack/model-downloads.md` |
| Linux のビルド、AppImage、実機での GUI 試験 | `docs/voice-stack/linux-build-pipeline.md`、`docs/voice-stack/appimage.md` |
| 音声まわりの設計判断 | `docs/voice-stack/decisions.md` と各 ADR（状態欄で、採用済みか提案かを確認する） |
| Ait の別セッションとの連絡 | `docs/ait-session-coordination.md` |

## 開発と検証の入口

入口は `python tools/dev.py` です。npm からも呼べます（`npm run doctor`、`npm run check` など）。スコープの一覧、準備の手順、終了コードは `docs/development.md` と `--help` で確かめてください。

```sh
python tools/dev.py doctor                  # 足りない道具や依存を表示する
python tools/dev.py setup --scope headless  # モデルなしの試験に使う依存を準備する
python tools/dev.py check                   # 軽量チェック（tooling、node、lint）
```

変更したら、軽量チェックと、変更した箇所に対応するスコープを実行します。影響が広いときは、検証を足します。

| 変更したもの | 追加で実行するもの |
|---|---|
| Python の音声、モデル取得、配布の検査 | `check --scope voice`（新しい Linux の checkout では先に `python tools/build_voice_gate.py`） |
| UI（`src-ui/`）や文言 | `check --scope ui` |
| Python のバックエンド全体（`src-python/`） | `check --scope backend --python <アプリ依存のある Python>` |
| Tauri や Rust（`src-tauri/`） | `check --scope rust` |
| 複数の領域、統合の前 | `check --scope all` |
| コミット | `check --scope commits --base origin/develop` |

- ブラウザ試験、ネイティブ GUI 試験、実機での音声やモデル推論の確認は、別の手順で明示して実行します。手順は上の資料の各節にあります。通常の `check` には含まれません。
- 実機で GUI を試験している間にディスプレイが消えると、描画が止まり、失敗の原因を取り違えます。Linux のデスクトップでは `tools/display_power_guard.py` の下で実行します（`docs/voice-stack/linux-build-pipeline.md`）。
- 文書だけを変えたときなど、影響が小さい場合は、検証もそれに見合った範囲で構いません。

## 検証と完了の報告

- 軽量チェックが通っても、全テストや実機での確認が通ったことにはなりません。
- 成功、失敗、スキップ、未実行、環境不足を分けて書きます。失敗は出力の要点を添えます。
- 完了の報告には、次の 4 点を書きます。
  - 変更の要点
  - 実行した検証と、その結果
  - 実行しなかった検証と、その理由
  - 残っている懸念
- 計測した値には、計測した環境と条件を添えます。ある PC での性能を、一般的な保証として書きません。

## コミットと変更履歴

人の開発者と同じ規約です。種別の表、例、分類の基準、リリースの手順は `CONTRIBUTING.md` の「Commit messages」と「Changelog and releases」にあります。

- コミットメッセージは Conventional Commits 1.0.0 で、英語で書きます。形は `<type>(<scope>)!: <summary>` です。要約は命令形で、先頭を小文字にし、句点を付けません。変わったことを、影響を受ける人の言葉で書きます。
- 種別は変更の中身で選びます。利用者ができることが増えたら `feat`、利用者が出会う不具合の修正は `fix`、開発の道具や CI だけの変更は `feat(dev)`、`ci`、`build`、`chore` などです。
- 設定、ファイルの形式、IPC や OSC の契約、対応する環境が前と同じに使えなくなるときは、`!` と `BREAKING CHANGE:` のフッターで明示します。フッターには利用者や開発者がすることを書きます。
- 種別だけでは CHANGELOG の分類がずれるときは `Changelog: user`、`Changelog: security`、`Changelog: internal`、`Changelog: skip` のフッターを付けます。
- commit-msg フックが入っていない環境もあります。コミットする前に `cog verify "<メッセージ>"` で確かめ、`python tools/dev.py check --scope commits --base origin/develop` も通します。
- `CHANGELOG.md` は `tools/changelog.py` が書くファイルで、載せるのは正式版だけです。正式版のリリースの準備を頼まれたとき以外は編集しません。書いた節を直すときは、まず `python tools/changelog.py print` の結果と比べます。ベータ版の変更は GitHub のプレリリースのノートに載せ、CHANGELOG には書きません。
- `cog bump` は使いません。タグは作らず、push もしません。タグは保守担当者が GitHub Releases の下書きを公開したときにできます。
- リリースの準備を頼まれたら、`package.json` の版、`npm run update-version` の順に進めます。正式版のときだけ、続けて `npm run changelog` を実行します。`chore(release): version X.Y.Z` で1つのコミットにします。

## 既存の重要な境界

詳しい内容は、それぞれの正本にあります。ここには要点だけを挙げます。

- **外部への操作**: 上流 VRCT への連絡、取り込みの打診、PR の作成（draft を含む）は、明示の指示がある場合だけ行います（`publication-and-upstream.md`）。push、PR、Release の公開、Hugging Face へのアップロードは、依頼の範囲に含まれているときに行います。Release は保守担当者が確認してから公開します（`release-candidates.md`）。
- **配布物とライセンス**: 上流のチャット吹き出し検出モデルを含む OCR の重み、許諾のないモデル、Mia2026 の音声を配布物に入れません。依存や同梱物を変えたら、`NOTICE.md` とライセンス台帳を確認します。ダウンロードできるモデルは、版、サイズ、SHA-256、ライセンスを固定してカタログ（`src-python/models/model_downloads/catalog.py`）に載せます。非商用など制限のあるライセンスのモデルは既定にしません。
- **互換性**: 内部識別子の `VRCT`、設定の形式、IPC と OSC の契約は、名前を変えるという理由だけで一括置換しません。保存先やアプリ ID などの識別子を変えるときは、移行の処理も用意します（`project-rename.md`）。
- **ユーザーの操作と同意**: モデルの取得は、ライセンスとサイズを示して同意を得てから行います。UI の変更によって、マイクの有効化、モデルの取得、メッセージの送信、音声経路の変更が勝手に起きないようにします。
- **停止と独立した制御**: 停止・ミュート、TTS と RVC の独立したスイッチ、Quick Chat、VR パネル、ホットキーの振る舞いを保ちます（`PRODUCT.md`、`DESIGN.md`）。
- **UI**: React 18、CSS Modules、Jotai、i18next の構成を保ちます。フレームワークの移行や、リモートのフォントは入れません。表示する文言は `locales/` に置き、`en.yml` と `ja.yml` は必ず更新します。キーボード操作、フォーカスの表示、長い日本語の表示、狭いウィンドウも確認の対象です。Windows の WebView2 と Linux の WebKitGTK の両方で動くことを前提にします。Baseline Widely available の機能はそのまま使い、それより新しい機能は機能検出と代わりの表示を付けたときだけ使います。
- **並行作業**: 別のセッションと担当を分けているときは、合意した範囲の外のファイルを編集・コミットしません。連絡の方法は `docs/ait-session-coordination.md` にあります。

## AGENTS.md 自体の更新

- パス、コマンド、参照先の訂正や、既存方針の範囲内での事実の訂正は、関連する作業のついでに更新してかまいません。
- 新しい禁止事項、保護する対象、事前承認のルールを足すことや、既存のルールを強めることは、まずユーザーに提案するだけにします。
- 既存の禁止事項や承認の境界を緩める変更も、単なる事実の訂正としては扱いません。
- 保護したい条件を足すときは、できるだけファイル単位の変更禁止ではなく、守るべき仕様、振る舞い、互換性を具体的に書きます。
- 一時的な注意や重複した説明は整理してかまいません。ただし、ユーザーと合意した保護の条件は、無断で削除しません。
- テストの件数、最新のコミット、その時点の未実装の一覧、特定の PC での性能値、採用前の設計案、一度限りの作業の指示は、ここに書きません。
