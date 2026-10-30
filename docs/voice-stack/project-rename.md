# VRCT-VOXへの改名と互換性

2026-10-30の依頼に合わせて、プロジェクトとリポジトリの名称をVRCT-VOXへ統一しました。旧名はVRCT.cpp、VRCT-TTSです。上流の[misyaguziya/VRCT](https://github.com/misyaguziya/VRCT)と、別プロジェクトのVRCT-TTSの名称は変更しません。

## 変更する名称

| 対象 | 名称 |
|---|---|
| プロジェクト・画面表示 | `VRCT-VOX` |
| GitHubリポジトリ | `kein5/VRCT-VOX` |
| npm・Cargoパッケージ、本体の実行名 | `vrct-vox` |
| Pythonバックエンドの実行名 | `vrct-vox-sidecar` |
| Linuxの配布物 | `VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz`、同名の`.AppImage` |
| Windowsの配布物 | `VRCT-VOX.zip`、`VRCT-VOX_cuda.zip`、`VRCT-VOX_<version>_x64-setup.exe` |
| Linuxデスクトップエントリー | `vrct-vox.desktop` |

Windowsの実行ファイルには`.exe`が付きます。CIの成果物名、sidecarの呼び出しと権限、配布物の検査、サポート先と更新先のURLも新しい名称に合わせました。バージョンは改名だけでは変更しません。

## 引き継ぐ設定と識別子

設定やモデルを再作成せずに使えるよう、次の識別子は維持します。

| 対象 | 維持する値 |
|---|---|
| TauriアプリID | `io.github.kein5.vrct-tts` |
| Linuxの設定保存先 | `$XDG_CONFIG_HOME/vrct-tts`、既定は`~/.config/vrct-tts` |
| Linuxのデータ保存先 | `$XDG_DATA_HOME/vrct-tts`、既定は`~/.local/share/vrct-tts` |
| Linuxのキャッシュ保存先 | `$XDG_CACHE_HOME/vrct-tts`、既定は`~/.cache/vrct-tts` |
| 環境変数 | `VRCT_CONFIG_DIR`、`VRCT_DATA_DIR`、`VRCT_CACHE_DIR`などの`VRCT_*` |
| Windowsのインストール先を記録するキー | `VRCT-TTS` |
| 音声経路と仮想マイク | 既存の`vrct.*`ノード、サービス、所有者識別子、デバイス表示名 |
| モデル取得とビルド作業領域の所有マーカー | 既存の値 |

保存先の変更を指定していなければ、旧版と同じ設定・取得済みモデルを読みます。アプリを起動するスクリプトや独自のショートカットで実行ファイル名を固定している場合は、`vrct-vox`へ変更してください。外部のRVC実行環境やモデルのパスはそのまま使います。

WindowsのNSISテンプレートは旧レジストリキーからインストール先を読み、表示名にはVRCT-VOXを使います。旧版が動いていれば停止を求め、新しい本体を展開できた後に旧実行ファイルを削除します。Windowsでのインストール・更新の実機試験は別途必要です。

## 履歴と公開

過去の試験報告、測定値、配布物名、SHA-256は書き換えません。古い名前が記載された結果は、その配布物を試験した記録です。改名後のバイナリの性能を再測定した意味にはなりません。

作業ディレクトリ名とGitの履歴は維持します。GitHubの改名ではリポジトリID、ブランチ、公開範囲を変えません。ローカルの`origin`は新しいURLへ更新し、`upstream`は本家のURLを維持します。リリースの公開は改名・developへの統合と別の操作です。

CIは[ビルドガイド](../readme_build.md)のとおり、試験と配布候補の作成を行います。GitHub Releasesの下書きは[手動の検証ゲート](release-candidates.md)から作成できます。自動公開とHugging Faceへのアップロードは無効のままです。元のライセンス・著作権・謝辞は維持します。
