# VRCT-VOXのビルドとCI

Windows向けのビルド手順と、現在のCIを説明します。Linuxでは[Linuxビルドパイプライン](voice-stack/linux-build-pipeline.md)と[AppImageガイド](voice-stack/appimage.md)を使います。Windows用のバッチコマンドはLinuxでは実行できません。

## Windowsの準備

Node.jsとnpm、Python 3.11、Rust、Git、TauriのWindowsビルドに必要なVisual Studio C++ツールを用意します。CIのNode.jsは22.15.0です。依存関係は`package-lock.json`、`requirements.txt`、`requirements_cuda.txt`、`src-tauri/Cargo.lock`で管理しています。

```sh
git clone https://github.com/kein5/VRCT-VOX.git
cd VRCT-VOX
npm ci
npm run setup-python
```

`setup-python`は`.venv`と`.venv_cuda`を作り直し、標準版とCUDA版の依存関係を入れます。既存の同名環境も削除するため、個別に追加した依存関係があれば先に記録してください。

CUDA版は対応するNVIDIAドライバーを使います。cuBLAS・cuDNNは`requirements_cuda.txt`の`nvidia-*-cu12`パッケージから同梱するため、CUDA Toolkitを別に入れる必要はありません。モデルの取得と本体のビルドは別の操作です。

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

## バージョン管理

バージョンは`package.json`で管理し、次のコマンドで`src-tauri/tauri.conf.json`と`src-python/config.py`へ同期します。通常のビルドコマンドでも同期処理を実行します。

```sh
npm run update-version
```

`3.6.0-beta.1`のような識別子も使えます。バージョン文字列だけで公開や配布先の切り替えは行いません。ZIP名はバージョンを含まない固定名で、NSIS・Linux候補のファイル名にはバージョンが入ります。

## CIと公開先

[voice-tests.yml](../.github/workflows/voice-tests.yml)はpushとpull requestで回帰試験を実行します。[build-linux.yml](../.github/workflows/build-linux.yml)は対象ファイルのpull requestと手動実行に対応し、Linux候補を作成・検査します。[release.yml](../.github/workflows/release.yml)は手動でWindows候補を作成・検査するワークフローです。

ビルド候補はGitHub Actionsの成果物として保存します。これらのワークフローはGitHub ReleasesやHugging Faceへ自動公開しません。タグをpushしても公開処理は始まりません。権限は`contents: read`で、本家の公開用キーやテレメトリー用キーは使いません。

配布先は[kein5/VRCT-VOX Releases](https://github.com/kein5/VRCT-VOX/releases)です。WindowsのNSISインストーラーは、このリポジトリのリリースから`VRCT-VOX.zip`または`VRCT-VOX_cuda.zip`を取得します。候補をビルドしただけでは、そのURLにファイルは存在しません。アプリ内更新は無効です。

公開前に[配布検査](voice-stack/fork-distribution-isolation.md)とライセンス監査を行います。ローカルで作った候補と公開済みリリースは区別します。上流への連絡やPRの扱いは[公開方針](voice-stack/publication-and-upstream.md)を参照してください。

## ビルド出力の削除と診断

`npm run clean`は`build/`、`dist/`、`src-tauri/bin/`、`src-tauri/target/`を削除します。保持したい試験成果物が`build/`にある場合は、先に退避してください。`npm run clean-soft`では`src-tauri/target/`だけを残します。

`npm run task-kill`は実行中の`vrct-vox-sidecar.exe`を強制終了します。保存や変換の途中で実行しないでください。

Python依存の問題は、選択した仮想環境とrequirementsの対応から確認します。Tauriの失敗はRust・C++ツールとsidecarの配置、画面だけの失敗は`npm run vite-build`の出力を確認します。CUDAの失敗では、ドライバーとCUDA版の仮想環境を確認してください。ビルド用のスペックファイルは`spec/backend.spec`、`spec/backend_cuda.spec`、`spec/backend_linux.spec`です。

設定保存先とアプリIDは[名称と識別子](voice-stack/project-rename.md)を参照してください。元の[LICENSE](../LICENSE)と[NOTICE](../NOTICE.md)を保持し、同梱ライブラリとモデルの条件はそれぞれ確認します。

## 共通の開発コマンドと下書き作成

環境診断と検査の入口は[開発ガイド](development.md)にまとめています。`npm run check`で軽い検査、`npm run test:voice`でモデル不要の音声契約、`npm run test:ui`でNodeテストとViteビルドを実行します。

候補の検査後は[配布手順](voice-stack/release-candidates.md)に従い、同じコミットのLinux・Windows成果物からリリース下書きを作成できます。公開は別途行います。
