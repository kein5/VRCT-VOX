# VRCT-VOXの名称と識別子

VRCT-VOXは[misyaguziya/VRCT](https://github.com/misyaguziya/VRCT)を基にした派生プロジェクトです（MIT）。2026-10-31にGitHubのfork networkから外れましたが、元のライセンスと帰属表示は維持します。上流のVRCTと、上流の作者による別プロジェクト[VRCT-TTS](https://github.com/misyaguziya/VRCT-TTS)の名称は変更しません。

## 名称

| 対象 | 名称 |
|---|---|
| プロジェクト・画面表示 | `VRCT-VOX` |
| GitHubリポジトリ | `kein5/VRCT-VOX` |
| npm・Cargoパッケージ、本体の実行名 | `vrct-vox` |
| Pythonバックエンドの実行名 | `vrct-vox-sidecar` |
| Linuxの配布物 | `VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz`、同名の`.AppImage` |
| Windowsの配布物 | `VRCT-VOX.zip`、`VRCT-VOX_cuda.zip`、`VRCT-VOX_<version>_x64-setup.exe` |
| Linuxデスクトップエントリー | `vrct-vox.desktop` |

Windowsの実行ファイルには`.exe`が付きます。

## 識別子と保存先

次の値は設定・データの保存先やOSとの連携に使います。変更すると既存の設定や連携を引き継げなくなるため、変える場合は移行処理を伴わせてください。

| 対象 | 値 |
|---|---|
| TauriアプリID | `io.github.kein5.vrct-vox` |
| Linuxの設定保存先 | `$XDG_CONFIG_HOME/vrct-vox`、既定は`~/.config/vrct-vox` |
| Linuxのデータ保存先 | `$XDG_DATA_HOME/vrct-vox`、既定は`~/.local/share/vrct-vox` |
| Linuxのキャッシュ保存先 | `$XDG_CACHE_HOME/vrct-vox`、既定は`~/.cache/vrct-vox` |
| 環境変数 | `VRCT_CONFIG_DIR`、`VRCT_DATA_DIR`、`VRCT_CACHE_DIR`などの`VRCT_*` |
| Windowsのインストール先を記録するキー | `VRCT-VOX` |
| 音声経路と仮想マイク | `vrct.managed.*`ノード、`vrct-managed-*.service`、所有者識別子`vrct-vox-service-v1` |
| モデル取得の所有マーカー | `VRCT-VOX-model-download-v1` |
| Linuxビルド作業領域の所有マーカー | `VRCT-VOX Linux staging v1` |
| Waylandのショートカット登録 | portalのアプリID`io.github.kein5.vrct-vox`、`~/.local/share/applications/io.github.kein5.vrct-vox.desktop` |

WindowsのNSISテンプレートは上記のレジストリキーから前回のインストール先を読み、表示名にはVRCT-VOXを使います。Windowsでのインストール・更新の実機試験は別途必要です。

## 公開

CIは[ビルドガイド](../readme_build.md)のとおり、試験と配布候補の作成を行います。GitHub Releasesの下書きは[手動の検証ゲート](release-candidates.md)から作成し、保守担当者が確認して公開します。最初の公開版は`v0.1.0-beta.1`（プレリリース）です。版は上流VRCT（3.x）とは別に0.1.0から数えます。自動公開とHugging Faceへのアップロードは無効のままです。元のライセンス・著作権・謝辞は維持します。
