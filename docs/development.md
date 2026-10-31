# VRCT-VOXの開発

開発用の入口は `python tools/dev.py` です。環境の診断、依存関係の準備、対象を選んだ検証を同じCLIから実行します。CLI自体はPython 3.11以降の標準ライブラリだけで動きます。

```sh
python tools/dev.py doctor
python tools/dev.py setup --scope headless --dry-run
python tools/dev.py setup --scope headless
python tools/dev.py setup --scope ui
python tools/dev.py check
```

`doctor` は不足を表示します。`setup` は指定した依存関係を導入します。`check` の既定値は `quick` で、開発CLIの試験、Nodeの試験、Ruffを実行します。詳しいコマンドは各サブコマンドの `--help` で確認できます。Linuxで `python` がない場合は `python3`、WindowsではPython 3.11以降の `py` でも起動できます。

npmからも `npm run doctor`、`npm run check`、`npm run check:all`、`npm run test:voice`、`npm run test:ui` を使えます。準備は `npm run setup:headless` と `npm run setup:browser`、コミット検証は `npm run check:commits -- --base origin/develop` です。追加オプションはnpmの `--` の後ろに渡します。`npm run dev:web` はWeb UIの開発サーバーを起動する別コマンドで、検証には含めません。

## 用意するツール

モデルなしの試験にはPython 3.11とuv、UIにはNode.jsとnpmが必要です。Rustを検証するときはRust/Cargo、コミット形式を検証するときはCocogittoも使います。CIのNode基準は22.15.0です。開発CLIはNode 22以降を受け付けます。uv 0.13.5、Cocogitto 7.0.0でコマンドを確認しています。

不足するツールは各公式手順から用意してください。`setup` はOSのパッケージマネージャーやグローバルインストーラーを実行しません。Python本体の自動取得も無効にしているため、Python 3.11が見つからない場合は先に用意します。

| ツール | 公式手順 |
| --- | --- |
| Python | [Python downloads](https://www.python.org/downloads/) |
| uv | [uv installation](https://docs.astral.sh/uv/getting-started/installation/) |
| Node.js / npm | [Node.js downloads](https://nodejs.org/en/download) |
| Rust / Cargo | [Rust installation](https://www.rust-lang.org/tools/install) |
| Cocogitto | [Cocogitto installation](https://docs.cocogitto.io/) |

LinuxのTauri検証にはWebKitGTK 4.1などの開発ライブラリも必要です。必要なパッケージは[Linuxビルド手順](voice-stack/linux-build-pipeline.md)にあります。`doctor --scope rust` は主要ライブラリをpkg-configで調べます。WindowsではTauri用のC++ビルド環境などを別途用意します。Rustのコンパイル成功は、インストーラーの実機確認とは別です。

Linuxのトレイ用ライブラリは `ayatana-appindicator3-0.1` または `appindicator3-0.1` のどちらかがあれば診断を通します。Ubuntu向けのAyatanaパッケージ名を他のディストリビューションへ一律に要求しません。[Tauriの前提条件](https://v2.tauri.app/start/prerequisites/)と、使用中のlibappindicator-sys 0.9.0が両方のライブラリを扱う実装に合わせています。

## 依存関係の準備

`setup` はスコープを1つずつ指定します。通信を伴うコマンドなので、先に `--dry-run` で確認できます。キャッシュだけで準備するときは `--offline` を付けます。

| スコープ | 実行内容と保存先 |
| --- | --- |
| `headless` | `uv.lock` の `voice-test` グループだけを `build/dev/headless-venv` に同期 |
| `ui` | `npm ci --ignore-scripts` でルートの `node_modules` を準備 |
| `browser` | `uv.lock` の `voice-ui-test` グループを `build/dev/browser-venv` に同期。既存venvへの追加も可 |
| `backend` | `uv.lock` の本体・`dev`・`linux-build` を `build/dev/backend-venv` に同期（Linux） |
| `rust` | `cargo fetch --locked` でCargo.lockに従う依存を取得 |
| `sidecar` | Unixで既存Rustソースをコンパイルし、Tauri開発用wrapperと必要なplaceholderを準備 |

専用venvには所有マーカーを保存します。同じ場所にマーカーのない既存ディレクトリやシンボリックリンクがある場合は停止し、削除しません。`headless` と `browser` のrequirementsは直接依存の一覧なので、`uv pip install` で間接依存も解決します。完全なlockがあるLinux backendだけは `uv pip sync` を使います。[uvの環境指定](https://docs.astral.sh/uv/pip/environments/)と[依存の固定・同期](https://docs.astral.sh/uv/pip/compile/)に沿った使い分けです。

`setup --scope ui` は既存の `node_modules` をnpmの仕様どおり作り直します。package.jsonとpackage-lock.jsonに不一致があれば失敗し、lockを更新しません。[npm ciの仕様](https://docs.npmjs.com/cli/v11/commands/npm-ci)を参照してください。

Windowsでも `headless`、`ui`、`browser`、`rust` は同じ入口です。backend自動準備は現在Linuxのlockを使うため、Windowsでは診断を出して終了します。既存のWindows全体セットアップは `npm run setup-python` ですが、現在のbatは `.venv` と `.venv_cuda` を作り直します。既存環境を保持したい場合には実行せず、利用できる環境を `--python` で検証に渡してください。

### Tauri開発用sidecarを準備する

新しいcheckoutや改名前の開発環境では、Tauriが要求するsidecarが不足する場合があります。Linuxでは次の順に準備して診断します。

```sh
python tools/dev.py setup --scope sidecar --dry-run
python tools/dev.py setup --scope sidecar
python tools/dev.py doctor --scope rust
python tools/dev.py check --scope rust
```

`rustc -vV` でhost tripleを調べ、既存の `utils/dev_sidecar/src/main.rs` を `rustc --edition=2021` でコンパイルします。外部crateの取得はありません。出力は `src-tauri/bin/vrct-vox-sidecar-<host triple>` です。既存のAppImageビルドは別workspaceを使うため、この開発用出力を用意していなくても成功することがあります。

出力が未存在なら新規作成します。既存ファイルを置き換えられるのは、このCLIの `.dev-owner.json` と現在のバイナリのSHA-256が一致する場合だけです。不明な既存バイナリ、変更されたハッシュ、出力先のシンボリックリンクは拒否します。コンパイルは同じファイルシステムの一時ディレクトリで行い、成功後に `os.replace` で配布します。コンパイル失敗時は元のバイナリと所有記録を保持します。

更新途中の中断に備え、所有記録は置換前後のハッシュを一時的に保持します。完了すると新しいハッシュだけになります。同時setupはlockで拒否します。異常終了で `.vrct-vox-dev-sidecar.lock` が残った場合は、別のsetupが動いていないことを確認してから手動で扱います。CLIは他プロセスを停止しません。

`src-tauri/bin/_internal` が未存在または空なら、所有placeholderファイルだけをexclusive作成します。既存ファイルや非空のresourcesは変更しません。placeholderは配布用runtimeではありません。`doctor --scope rust` は新名のsidecarとresourcesの不足も診断します。

この直rustc方式はUnix向けです。Windowsでは既存ソースのJob Object処理が `windows-sys` を必要とするため、安全に停止して `utils/dev_sidecar` の既存Cargo方式を案内します。Windows実機は未確認です。wrapperを実際に起動するには、従来どおり `.venv`、`.venv_cuda`、Linuxの `.venv_linux` のいずれかへアプリ依存を用意し、必要に応じて `VRCT_DEV_VENV` を指定します。`build/dev/backend-venv` はwrapperの起動対象には自動追加しません。

### 既存Linux環境へUI試験の依存を追加する

```sh
python tools/dev.py setup --scope browser --python .venv_linux/bin/python --dry-run
python tools/dev.py setup --scope browser --python .venv_linux/bin/python
python tools/dev.py doctor --scope browser --python .venv_linux/bin/python
```

この操作は選んだPython 3.11のvenvに必要なパッケージを追加・更新します。無関係なパッケージをsyncで削除しません。システムPythonは拒否します。Windowsのvenvなら `.venv\Scripts\python.exe` のように実行ファイルを指定します。

PlaywrightのPythonパッケージとChromium実行ファイルは別です。`setup --scope browser` はChromiumやOSライブラリを取得しません。既存ブラウザを使う試験には `VRCT_TEST_CHROMIUM` の指定が必要です。ブラウザ試験の実行条件は[モデル取得UIの検証記録](voice-stack/model-downloads.md)を参照してください。通常の `check` は実機・ブラウザ試験の有効化変数を除外するため、専用試験は個別の手順で実行します。

## 検証する対象を選ぶ

```sh
python tools/dev.py check --scope tooling
python tools/dev.py check --scope node
python tools/dev.py check --scope voice
python tools/dev.py check --scope ui
python tools/dev.py check --scope backend --python .venv_linux/bin/python
python tools/dev.py check --scope rust --dry-run
```

| スコープ | 内容 |
| --- | --- |
| `tooling` | 標準ライブラリのunittestで `tests/devtools` を検証 |
| `node` | `src-ui` 以下の `.test.js` / `.test.mjs` を全列挙して `node --test` |
| `lint` | voice CIと同じRuff対象に開発CLI、配布候補CLI2本、専用試験を追加。自動修正なし |
| `voice` | `tests/voice/pytest.ini` を使ったモデルなしの契約試験 |
| `ui` | Nodeの試験と `npm run vite-build`。ブラウザの操作は含まない |
| `backend` | 既存 `pytest.ini` による `src-python/test`。runtime依存が必要 |
| `rust` | `cargo check --locked --offline`。キャッシュやOS依存がなければ失敗 |
| `quick` | `tooling`、`node`、`lint`。既定値 |
| `all` | 上記7対象。時間がかかるため統合時に明示実行 |
| `commits` | `--base` からHEADまでの新規コミット形式を検証 |

Pythonは専用venvを優先し、次に既存 `.venv_linux`、`.venv` を探します。`--python` があればその実行ファイルを使います。backend専用venvがない状態で `all` を実行しても、依存の不足を黙って省略しません。`doctor --scope all` で先に確認できます。

`doctor` と `check` は依存パッケージ・モデルを取得せず、アプリ、マイク、発声、GPU推論を起動しません。子プロセスでは `VRCT_` で始まる環境変数、pytest追加引数・外部pluginの自動読込みを除外し、Hugging Faceをofflineにします。これは試験の誤起動を防ぐ設定であり、任意のテストコードを封じるネットワークsandboxではありません。HTTP/UDP契約試験はローカルの一時ポートを使います。通信を禁止するsandboxではその試験が失敗します。

`check` はキャッシュや検証用の一時ファイルを作り、UIでは `dist`、RustではCargoのビルド先を書き換えます。起動中の通常アプリを停止するnpmの `dev` / `build` / `task-kill` は呼びません。tooling試験では、Linuxにrustcがある場合に一時ディレクトリでwrapperをコンパイルし、隔離したダミーPythonで引数転送を確かめます。配布ビルドは[Linuxビルド手順](voice-stack/linux-build-pipeline.md)の専用workspaceで行います。

最初に見つかった失敗で停止します。終了コードは次のとおりです。

| コード | 意味 |
| --- | --- |
| `0` | 選択した検証の成功。`--dry-run` なら計画の表示成功のみ |
| `1` | 実行した検証・導入コマンドが失敗。子コマンドの終了値も表示 |
| `2` | 引数、不足する前提、所有マーカー、Git基点などの問題 |
| `130` | Ctrl+Cによる中断 |

機械処理には `python tools/dev.py doctor --scope voice --json` を使います。未整備環境では `ok: false` と対処方法を返します。

## EditorConfigとコミット形式

`.editorconfig` はUTF-8、LF、末尾改行を指定します。基本の字下げは空白4個、JSON/YAML/TOML/HTML/CSS/SCSSは2個です。Markdownの末尾空白、patch/diffの空白と末尾改行は意味があるため、一律削除を避けています。適用はエディターで今後編集するファイルが対象です。既存ファイルを一括整形するコマンドは追加していません。[EditorConfigの設定仕様](https://editorconfig.org/)に対応するエディターまたは拡張機能を使います。

CocogittoはConventional Commitsを扱うツールで、コマンド名が `cog` です。例えば `feat(dev): add developer checks` は機能追加、`fix(tts): preserve cancellation state` は不具合修正を表します。形式は[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)に従います。

```sh
# メッセージだけを検証。コミットは作らない
cog verify "feat(dev): add developer checks"

# 基点はローカルに存在するrefを明示する
python tools/dev.py check --scope commits --base origin/develop

# 差分の変更履歴を標準出力で確認する
cog changelog origin/develop..HEAD
```

CLIは指定refとHEADの共通祖先を求め、その後のコミットだけを `cog check` に渡します。基点がない場合は終了コード2で止まり、自動fetchや全履歴への切替はしません。CIでは対象PRのbase/headを取得した状態で実行します。取得深さが足りず共通祖先が見つからない場合も停止します。

既存履歴を遡って形式を直す必要はありません。引数なしの `cog check` は全履歴を調べるため、通常は上記の範囲指定を使います。merge commitは設定で除外し、fixup commitは除外しません。`cog.toml` のchangelogリンク先は `kein5/VRCT-VOX` です。[履歴検証](https://docs.cocogitto.io/guide/check.html)と[changelog](https://docs.cocogitto.io/guide/changelog.html)の公式手順も参照できます。

ローカルhookの自動登録、履歴を書き換える `cog edit`、版・タグを作る `cog bump`、commit/push、公開hookは開発CLIに含めません。既存のpackage.json・Tauri・Pythonの版更新手順をCocogittoへ置き換えていません。

## CIでの利用と再現性

CIでは準備と検証を分けます。例えば、既存CIで依存を導入した後は次のように同じコマンドを呼べます。WindowsではPython実行ファイルを `.venv\Scripts\python.exe` に変更します。

```sh
python tools/dev.py check --scope tooling
python tools/dev.py check --scope voice --python .venv/bin/python
python tools/dev.py check --scope lint --python .venv/bin/python
python tools/dev.py check --scope ui
python tools/dev.py check --scope commits --base origin/develop
```

このCLIはvoice gateのコンパイルを代行しません。Linux CIの `tools/build_voice_gate.py` と必要なOS依存の準備は既存の手順を維持します。ブラウザ試験、ネイティブアプリ、実GPU、マイク、配布物の受け入れ試験も別の明示的な工程です。

新規のLinux checkoutで `check --scope voice` を実行する前には、Cコンパイラー、pkg-config、PipeWire開発ライブラリを用意し、次を実行してください。音声試験用の補助バイナリを `build/` に生成します。これを省くと、Python依存がそろっていてもcaptureなどの試験が失敗します。

検証済みの音声基盤はPipeWire 1.6.10とWirePlumber 0.5.18です。Ubuntu 24.04標準のAPIではcaptureをコンパイルできません。[Linuxビルド手順](voice-stack/linux-build-pipeline.md)の隔離セットアップは、固定ハッシュの公式ソースから必要な版を作ります。ホストの音声サービスは変更しません。Python用の `setup --scope headless` とは別の明示操作です。

```sh
python tools/build_voice_gate.py
python tools/dev.py check --scope voice
```

npmとCargoは既存のlockを使います。Linux backendは完全な依存一覧を使い、headless/browserは直接依存を固定しています。後者の間接依存、Pythonのpatch版、Rust、OSライブラリまではこのCLIで完全固定しません。同じビット列の配布物や全機種での動作を保証するものではありません。検証記録には `doctor --json` の結果、実行scope、commit、OSを併記します。
