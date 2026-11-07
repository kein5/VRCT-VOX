# VRCT-VOXのビルドとCI

Windows向けのビルド手順と、現在のCIを説明します。Linuxでは[Linuxビルドパイプライン](voice-stack/linux-build-pipeline.md)と[AppImageガイド](voice-stack/appimage.md)を使います。Windows用のバッチコマンドはLinuxでは実行できません。

## Windowsの準備

Node.jsとnpm、Python 3.11、Rust、Git、TauriのWindowsビルドに必要なVisual Studio C++ツールを用意します。CIのNode.jsは22.15.0です。Pythonの依存関係は[uv](https://docs.astral.sh/uv/getting-started/installation/)で管理するため、uvも用意します。依存関係は`package-lock.json`、`pyproject.toml`と`uv.lock`、`src-tauri/Cargo.lock`で管理しています。

```sh
git clone https://github.com/kein5/VRCT-VOX.git
cd VRCT-VOX
npm ci
npm run setup-python
```

`setup-python`は`uv sync --frozen`で`.venv`（標準版）と`.venv_cuda`（`cuda`のextra付き）を`uv.lock`のとおりに同期します。ロックにないパッケージは削除されるため、個別に追加した依存関係があれば先に記録してください。

Windowsの同期とLinux候補のビルドでは、uvが`uv.lock`のハッシュを使って取得したPythonパッケージを照合します。Linuxでは同期前に、各アーカイブのSHA-256とGit依存の完全なcommit SHAがあることも検査し、不足していれば停止します。詳しくは[Linuxビルドパイプライン](voice-stack/linux-build-pipeline.md)を参照してください。音声契約のCIはハッシュ付きの一覧を書き出し、`uv pip sync --require-hashes`で同期します。

CUDA版は対応するNVIDIAドライバーを使います。cuBLAS・cuDNNは`pyproject.toml`の`cuda` extraにある`nvidia-*-cu12`パッケージから同梱するため、CUDA Toolkitを別に入れる必要はありません。モデルの取得と本体のビルドは別の操作です。Windowsのビルドは、`build/speechcpp`がなければ固定版のspeech.cpp（約29 MB）を公式リリースから取得し、ハッシュを確かめてから同梱します。

## 開発時の起動

日常のPython・UI開発では、仮想環境のPythonを直接起動する開発用sidecarを使えます。

```sh
npm run dev-fast
# CUDA版の仮想環境を使う場合
npm run dev-cuda-fast
```

コマンドは`VRCT_DEV_VENV`を設定し、Rustの開発用sidecarをビルドしてからViteとTauriを起動します。選択した仮想環境がなければエラーで止まります。事前のactivateは不要です。

Pythonの変更は再起動で反映されます。配布用の凍結バックエンドとは起動方法が違うため、この起動確認だけで配布物の動作確認を終えたとは扱いません。依存関係や同梱資源を変更した場合は、次の方法でも確認します。

```sh
npm run dev
# CUDA版
npm run dev-cuda
```

こちらは既存のビルド出力を削除し、バージョン情報を同期して、PyInstallerでバックエンドを作り直します。UIだけを再起動する`npm run dev-ui`は、sidecarの準備が済んでいる場合に使います。

## 配布候補の作成

```sh
npm run release
npm run release-cuda
# 両方を順に作成する場合
npm run release-all
```

| 対象 | 出力 |
|---|---|
| Windows標準版 | `VRCT-VOX.zip` |
| Windows CUDA版 | `VRCT-VOX_cuda.zip` |
| Windowsインストーラー | `src-tauri/target/release/bundle/nsis/VRCT-VOX_<version>_x64-setup.exe` |
| Linux | `VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz`と同名の`.AppImage` |

WindowsのZIPには`vrct-vox.exe`、`vrct-vox-sidecar.exe`、依存ファイルの`_internal/`を収めます。Linuxの実行名には`.exe`を付けません。配布物の作成時にはOCR重みなどの禁止資源を検査します。ソースツリー全体をそのまま配布ZIPにしないでください。

個別にビルドするコマンドは次のとおりです。

| 操作 | コマンド | 主な出力先 |
|---|---|---|
| 標準版バックエンド | `npm run build-python` | `src-tauri/bin/` |
| CUDA版バックエンド | `npm run build-python-cuda` | `src-tauri/bin/` |
| フロントエンド | `npm run vite-build` | `dist/` |
| Tauri本体 | `npm run tauri build` | `src-tauri/target/release/` |
| 標準版をまとめてビルド | `npm run build` | 上記の本体と資源 |
| CUDA版をまとめてビルド | `npm run build-cuda` | 上記の本体と資源 |

`VRCT_PYINSTALLER_CLEAN=1`はPyInstallerの解析キャッシュを破棄します。`VRCT_PYINSTALLER_UPX=1`はUPX圧縮を有効にする設定で、初期設定は無効です。

## 配布ビルドでのCSP検証

CSPの定義と許可理由は[外部インターフェース](spec/external-interfaces.md#webviewのcontent-security-policycsp)にある。Viteの開発サーバーや`tauri dev`は`devCsp`を使うため、配布用CSPの確認にはならない。

まず静的検査とフロントエンドのビルドを実行する。最後の単独テストで、そのビルドのJS/CSS/HTMLと依存のstylesheet hashを検査する。以前の`dist/`を検査した結果と混同しない。

```sh
python tools/dev.py check --scope ui
node --test src-ui/logics/common/contentSecurityPolicy.test.js
```

次に、対象OSの配布手順でproductionフロントエンドを埋め込んだrelease binaryを作る。sidecarと配布資源を準備済みなら`npm run tauri build -- --no-bundle`で本体をビルドできる。`cargo check`は設定のparse確認であり、埋め込まれたCSPやWebviewの動作確認ではない。

WindowsのWebView2とLinuxのWebKitGTKで、それぞれ次を実施する。Linuxの実機操作は`tools/display_power_guard.py`の下で行う。OS、Webviewの版、コミット、ビルド設定、操作したウィンドウ、Console/Networkの記録を残す。

1. `main`、`quick_chat`、`vr_panel`それぞれにInspectorを接続する。現在のCargo設定には`devtools`機能があるが、releaseでは自動でInspectorを開かない。必要なら検証専用のローカル変更でmainの`devtools: true`と動的ウィンドウbuilderの`.devtools(true)`を指定し、作成後にRustの`open_devtools()`を呼ぶ。CSPの変更や`tauri dev`への切り替えはしない。VRパネルは画面外にあるため、mainだけを検査して済ませない。この検証用変更は配布しない。
2. Consoleの全レベルとログ保持を有効にして各ページを再読み込みする。NetworkでHTML応答の`Content-Security-Policy`を確認する。設定したdirectiveに加え、Tauriが生成したnonce/hashがある場合も正常。`frame-ancestors`はmetaタグでは効かないため、HTMLにmetaを追加するだけで検証を代替しない。
3. 下表の操作を実施する。`Refused to …`、`Content Security Policy`、`blocked:csp`、`securitypolicyviolation`を探す。動作中の記録には以下のlistenerも使える。listenerをConsoleから登録した場合、それ以前の違反や再読み込み後の違反はこの配列には入らないので、Consoleのブラウザー自身のエラーと併せて確認する。
4. 記録を保存した後、検証用のinline scriptをDOMへ追加すると拒否されることも確かめる。例えば`const s = document.createElement('script'); s.textContent = 'window.__cspProbeExecuted = true'; document.head.append(s)`をInspectorで実行する。`__cspProbeExecuted`が設定されず、`script-src`違反が記録されることを確認する。この意図した違反は通常操作の結果と分けて記録する。

```js
window.__cspViolations = [];
window.addEventListener("securitypolicyviolation", event => {
    const entry = {
        directive: event.effectiveDirective,
        blocked: event.blockedURI,
        source: event.sourceFile,
        line: event.lineNumber,
    };
    window.__cspViolations.push(entry);
    console.error("CSP violation", entry);
});
```

| ウィンドウ/画面 | 操作と確認する資源 |
|---|---|
| mainの起動 | splash、初期化進捗、ダウンロード状態、アプリアイコン、会話ログ、通知。共有JS/CSSと画像が描画される |
| mainの設定 | 全タブ、検索、開閉、保存、通知。言語5種、OSのローカルフォント、倍率、ログ文字サイズ、狭い幅、ドロップダウンとスクロールを確認する |
| About | 全言語のロゴ、開発者/貢献者/謝辞の全画像、リンクボタンの画像。外部リンクはWebview内の資源として読まれない |
| 色選択 | OBSの文字色と縁取り色のpickerを初回に開く。ドラッグ、キー操作、直接入力、保存を確認する。react-colorfulのstyle hashとdata SVG、CSSOMの更新を検査する |
| モデル取得 | TTS/RVC/ASR/OCR、翻訳・文字起こし用の取得確認、ライセンス・容量表示、キャンセル、同意後の進捗と失敗通知。許諾のあるモデルだけで取得を試す。ネットワーク処理はPython側である |
| OCR | window/VRそれぞれの領域スライダー、矩形プレビュー、リセット、モデル準備の案内。画像URLを取得するプレビューではない |
| ログと音声 | 自動ログ保存とフォルダーを開く操作、チャット送信、TTS/RVCと停止/ミュート、音声サーバーの状態表示。blobダウンロードやHTML mediaを必要としない |
| OBS/WebSocket設定 | 設定の保存、オン/オフ、認証URLのコピー。UIからOBSページやWebSocketへ接続しない |
| Quick Chat | mainのボタン/ホットキーで開く、入力、送信、失敗表示、閉じる/再表示、言語・フォント・倍率の追従。専用chunkと共有CSS/JS、IPCを確認する |
| VRパネル | オン/オフと再作成、introのアイコン/背景、launcher、ログ開閉とスクロール、言語/フォントpicker、全設定popup、tooltip、ポインタ/押下表示、透過度/文字サイズ。virtuaの配置とCSSOM、ウィンドウ間IPCを確認する |

通常操作ではCSP違反がなく、画像・通知・色選択のstyleが欠けず、全ウィンドウでIPCが動くことを合格条件とする。Consoleに違反がないだけで、隠れている画面も確認済みとは扱わない。静的検査はブラウザー実装の差やすべての動的な資源読み込みを検証するものではない。依存の更新時も同じ実機確認を繰り返す。

## バージョン管理

バージョンは`package.json`で管理し、次のコマンドで`src-tauri/tauri.conf.json`、`src-python/config.py`、`pyproject.toml`へ同期します。`pyproject.toml`の版が変わったときは`uv lock`も実行して`uv.lock`を更新します。通常のビルドコマンドでも同期処理を実行します。

```sh
npm run update-version
```

版は上流VRCT（3.x）とは別に0.1.0から数えます。`0.1.0-beta.1`のような識別子も使えます。バージョン文字列だけで公開や配布先の切り替えは行いません。ZIP名はバージョンを含まない固定名で、NSIS・Linux候補のファイル名にはバージョンが入ります。

## CIと公開先

[voice-tests.yml](../.github/workflows/voice-tests.yml)はpushとpull requestで回帰試験を実行します。[build-linux.yml](../.github/workflows/build-linux.yml)は対象ファイルのpull requestと手動実行に対応し、Linux候補を作成・検査します。[release.yml](../.github/workflows/release.yml)はWindows候補を作成・検査するワークフローで、手動実行とmain宛てのpull requestで動きます。CPU版とCUDA版は並列のジョブでビルドし、最後のジョブで両方を検査します。[prepare-release.yml](../.github/workflows/prepare-release.yml)は、検査済みの候補からリリースの下書きを作る手動のワークフローです。

ビルド候補はGitHub Actionsの成果物として保存します。これらのワークフローはGitHub ReleasesやHugging Faceへ自動公開しません。タグをpushしても公開処理は始まりません。権限は`contents: read`で、本家の公開用キーやテレメトリー用キーは使いません。

配布先は[kein5/VRCT-VOX Releases](https://github.com/kein5/VRCT-VOX/releases)です。最初の公開版は`v0.1.0-beta.1`（プレリリース、developから作成）です。WindowsのNSISインストーラーは、このリポジトリのリリースから`VRCT-VOX.zip`または`VRCT-VOX_cuda.zip`を取得します。候補をビルドしただけでは、そのURLにファイルは存在しません。アプリ内更新は無効です。

Windowsの更新は、インストール先の`.upd`内で取得済みパッケージを検証・展開してから、アプリのファイルだけを置き換えます。取得・展開失敗では旧版を保持し、置き換え失敗では退避した旧ファイルを戻します。設定・モデル・ログは置き換えません。中断からの復旧、復元に失敗したときの扱い、実際のNSISを使うWindows試験は[配布候補の手順](voice-stack/release-candidates.md#windowsのwebview2とインストール時の通信)を参照してください。

公開前に[配布検査](voice-stack/fork-distribution-isolation.md)とライセンス監査を行います。ローカルで作った候補と公開済みリリースは区別します。上流への連絡やPRの扱いは[公開方針](voice-stack/publication-and-upstream.md)を参照してください。

## ビルド出力の削除と診断

`npm run clean`は`build/`、`dist/`、`src-tauri/bin/`、`src-tauri/target/`を削除します。保持したい試験成果物が`build/`にある場合は、先に退避してください。`npm run clean-soft`では`src-tauri/target/`だけを残します。

`npm run task-kill`は実行中の`vrct-vox-sidecar.exe`を強制終了します。保存や変換の途中で実行しないでください。

Python依存の問題は、選択した仮想環境が`uv.lock`と一致しているかを確認します。`npm run setup-python`で同期し直せます。Tauriの失敗はRust・C++ツールとsidecarの配置、画面だけの失敗は`npm run vite-build`の出力を確認します。CUDAの失敗では、ドライバーとCUDA版の仮想環境を確認してください。ビルド用のスペックファイルは`spec/backend.spec`、`spec/backend_cuda.spec`、`spec/backend_linux.spec`です。

設定保存先とアプリIDは[名称と識別子](voice-stack/project-rename.md)を参照してください。元の[LICENSE](../LICENSE)と[NOTICE](../NOTICE.md)を保持し、同梱ライブラリとモデルの条件はそれぞれ確認します。

## 共通の開発コマンドと下書き作成

環境診断と検査の入口は[開発ガイド](development.md)にまとめています。`npm run check`で軽い検査、`npm run test:voice`でモデル不要の音声契約、`npm run test:ui`でNodeテストとViteビルドを実行します。

候補の検査後は[配布手順](voice-stack/release-candidates.md)に従い、同じコミットのLinux・Windows成果物からリリース下書きを作成できます。公開は別途行います。
