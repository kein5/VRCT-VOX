# VRCT-VOXの配布候補とリリース下書き

配布候補の作成と公開を分けています。最初の公開版は2026-10-31の`v0.1.0-beta.1`（developからのプレリリース）です。Linux・Windowsの候補を同じブランチの同じコミットから作り、検査後にGitHub Releasesの下書きへまとめます。公開は保守担当者が下書きを確認して行います。

## ブランチとチャンネル

| ブランチ | チャンネル | 版の形式 | GitHub Releases |
|---|---|---|---|
| `main` | 正式版 | `X.Y.Z`（例: `0.1.0`） | 通常のリリース。最新版として表示 |
| `develop` | ベータ版 | `X.Y.Z-beta.N`（例: `0.2.0-beta.1`） | プレリリース。最新版にはしない |

ブランチと版の形式が一致しない場合、下書きは作成しません。アプリ内のリリースチャンネル判定も版の`-beta`で行います。正式版は、developから`release/X.Y.Z`ブランチを切って版だけを`X.Y.Z`に変え（`utils/update_version.py`）、mainへのPRで統合してから作成します。mainは保護されていて、必須チェックに通ったPRでしか変更できません。公開後はmainをdevelopへ統合し、developを次の`-beta.N`へ進めます。

## 候補を作る

1. `package.json`の版をリリースするブランチの形式にし、`npm run update-version`で`src-tauri/tauri.conf.json`、`src-python/config.py`、`pyproject.toml`、`uv.lock`へ反映します。
2. GitHub Actionsの「VRCT-VOX Linux candidate (no publication)」を`main`（正式版）または`develop`（ベータ版）で手動実行します。Vulkan版かCPU版を選びます。
3. 「Validate VRCT-VOX distribution」を同じコミットで手動実行し、Windows候補を作ります。このワークフローはmain宛てのPRでも動きますが、下書きに使えるのは手動実行の結果だけです。
4. 両方の実行が成功したら、run IDを控えます。候補の保存期間は7日です。

Linuxでは再配置したアーカイブとAppImageのGUI試験、WindowsではZIP・NSIS内の配布禁止ファイル検査が成功した後に、候補を保存します。各候補の`candidate-manifest.json`にはリポジトリ、コミット、版、ファイル名、容量、SHA-256を記録します。`SHA256SUMS`と、各配布物の`.sha256`も同梱します。インストーラー用の`.sha256`は改行なしの64 ASCII文字で保存します。

## 下書きを作る

「Prepare verified VRCT-VOX release draft」を同じブランチの同じコミットで手動実行し、Linux・Windowsのrun IDを指定します。別のコミットへ進んだ場合は、そのコミットで候補を作り直してください。

この処理は成功した手動ビルドだけを受け付け、元のリポジトリ、ワークフロー、ブランチ、コミット、ブランチと版の形式の対応を確認します。取得した候補についても版・ファイル集合・容量・SHA-256を照合し、差異があれば終了します。ダウンロードしたコードは実行しません。

作成するのは`v<version>`の下書きです。既存の同名タグがある場合は、対象コミットが同じでも停止します。新しい版を選んでください。タグ照会の失敗も続行せず、既存リリースの上書きや自動公開は行いません。下書きの説明を実際の変更内容に置き換え、Windowsのインストール・旧版からの更新・アンインストールを確認してから公開してください。ビルド成功だけではWindowsのTTS/RVC実機動作まで確認したことになりません。確認の手順は[Windowsの音声機能](local-setup-windows.md)にあります。

Windowsのsetupは、下書きへまとめる際に`VRCT-VOX_setup.exe`へコピーします。インストーラーが取得する`VRCT-VOX.zip`と`VRCT-VOX_cuda.zip`の名前も維持してください。アプリの自動更新は引き続き無効です。

## 公開前にWindowsのパッケージを起動して確かめる

候補のビルドはパッケージの中身（配布してはいけないファイル、容量、SHA-256）を検査し、パッケージしたバックエンドを`--self-check`で起動します。`--self-check`は機能をオンにしたときに初めて読み込むライブラリ（翻訳のtokenizer、CTranslate2、faster-whisper）を読み込めるかだけを確かめます。画面と、モデルを使う動作は確かめません。

0.1.0-beta.7までのWindowsのパッケージでは、ローカル翻訳を一度もオンにできませんでした。PyInstallerのアーカイブの中ではTransformersが自分のフォルダーの一覧を読めず、tokenizerを組み立てられなかったためです。開発用のビルドでは起きないので、パッケージを起動して「翻訳」を押すまで分かりませんでした。公開の前に、下書きの`VRCT-VOX.zip`を作業用のフォルダーへ展開して起動してください。インストール済みのVRCT-VOXには触れません。

```powershell
# 下書きのパッケージを取得し、SHA-256を確かめて、作業用のフォルダーへ展開する
$d = "build\release-check\<version>"
gh release download v<version> -R kein5/VRCT-VOX -p "VRCT-VOX.zip" -p "VRCT-VOX.zip.sha256" -D "$d\dl"
(Get-FileHash "$d\dl\VRCT-VOX.zip" -Algorithm SHA256).Hash.ToLower() -eq (Get-Content "$d\dl\VRCT-VOX.zip.sha256" -Raw).Trim()
New-Item -ItemType Directory -Force "$d\app", "$d\state", "$d\webview" | Out-Null
tar -xf "$d\dl\VRCT-VOX.zip" -C "$d\app"

# 設定とWebView2のデータを作業用のフォルダーへ分けて起動する（どちらも絶対パス）
$env:VRCT_CONFIG_DIR = (Resolve-Path "$d\state").Path
$env:WEBVIEW2_USER_DATA_FOLDER = (Resolve-Path "$d\webview").Path
& "$d\app\vrct-vox.exe"
```

- `VRCT_CONFIG_DIR`を指定すると、設定とログがそのフォルダーに入り、インストール済みのアプリが動いていても別に起動します。モデルと`telemetry_state.json`は展開した`app`フォルダーの中に入ります。
- OSCの送信先がこのPC（既定）だと、バックエンドがmDNSのためにポートを開き、新しい場所の実行ファイルにはWindowsのファイアウォールの確認が出ます。確認を出さずに見るときは、`state\config.json`に`"OSC_IP_ADDRESS": "127.0.0.2"`と`"SEND_MESSAGE_TO_VRC": false`を書いてから起動します。
- 利用状況のお知らせで「送信する」を選ぶと、実際の受信サーバーへ1件送ります。送らずに見るときは`VRCT_TELEMETRY`に`off`を入れます。
- 少なくとも次を確かめます。起動して版が表示されること。「翻訳」を押すと取得の確認画面が開き、同意して取得が終わると翻訳がオンになって訳文が出ること。設定の各ページが開くこと。閉じるとバックエンドのプロセスも終わること。`state\logs\error.log`に、翻訳モデルがない状態で「翻訳」を押したときの記録（`MissingCTranslate2Tokenizer`）のほかが出ていないこと。この記録は取得の確認画面を開くときに毎回残ります。

## 公開前にLinuxのデスクトップで確かめる

候補のビルドは、AppImageの起動、描画、設定画面の操作までを自動で確かめます。音声経路、音声認識、VRChatを使う試験は、PipeWireとWirePlumber 0.5、モデル、GPU、VRChatが要るので、CIでは実行しません。CIに含まれない試験は、画面を変えたあとに気づかないまま古くなります。0.1.0-beta.6では、公開の直前に補助コードが今の画面と合っていないことが分かり、一部を確かめないまま公開しました。その後に流し直すと、設定画面で音声認識サーバーを止めても、閉じると再開する不具合が見つかっています。公開の前に、下書きのAppImageをLinuxのデスクトップで実行してください。

```bash
# 下書きのAppImageを取得し、SHA-256を確かめる
mkdir -p ~/.cache/vrct-vox-release-check/<version> && cd ~/.cache/vrct-vox-release-check/<version>
gh release download v<version> -R kein5/VRCT-VOX -p '*.AppImage' -p 'SHA256SUMS-linux'
sha256sum -c --ignore-missing SHA256SUMS-linux
cd <リポジトリ>

# モデルの要らない試験だけ
python tools/native_acceptance.py --appimage <AppImageの絶対パス>

# 音声認識、読み上げ、VRChatの往復、モデルの取得も含める
python tools/native_acceptance.py --appimage <AppImageの絶対パス> --fetch-models --vrchat --downloads

# RVCとSeed-VCの実行環境、実際の音声経路でのVRChatも含める
python tools/native_acceptance.py --appimage <AppImageの絶対パス> --fetch-models --fetch-runtimes \
  --vrchat --vrchat-voice --downloads

# VR UI（開発ビルドだけ）
python tools/native_acceptance.py --app src-tauri/target/debug/vrct-vox --only vr-ui
```

`tools/native_acceptance.py`は、試験のグループごとにpytestを起動し、成功、失敗、スキップの件数を表示します。結果は`build/native-acceptance/summary.json`、各グループのログは同じフォルダーの`<グループ>/pytest.log`です。試験は実際のアプリを画面に開きます。音声は試験専用のPipeWireグラフを通すため、実際のマイクやスピーカーには触れません。`tauri-driver` 2.1.0の場所は`--driver`か`VRCT_TEST_DRIVER`で指定します。

| グループ | 確かめること | 要るもの |
|---|---|---|
| `appimage` | FUSEと展開の両方式での起動、描画、終了、設定画面の操作、再起動後のミュート | AppImage |
| `ui` | 基本画面と設定画面（表示倍率100%と150%） | なし |
| `voice` | 読み上げが仮想マイクへちょうど1回届くこと、停止とミュート、直接入力、TTSの独立動作、バックエンドの起動 | なし（固定の音声） |
| `tts-model` | 低遅延の待機、遅延の計測 | Irodori、GPU |
| `asr` | リアルタイム字幕、内蔵の音声サーバー、音声翻訳 | Qwen3-ASR、Silero VAD、Qwen3-TTS、GPU |
| `downloads` | 同意の画面、実際の取得（約336 MB）、SHA-256、適用、再起動後の保持 | `--downloads` |
| `rvc` | アプリから起動した実際のRVCの変換、ミュート中の無音、停止 | RVCの実行環境とモデル、GPU |
| `seed-vc` | アプリから起動した実際のSeed-VCの変換、停止、入力の消失 | Seed-VCの実行環境、GPU |
| `vrchat` | アプリで入力した文が実際のVRChatの吹き出しに出て、チャット読み取りで読み戻せること | `--vrchat`、OCRのモデル |
| `vrchat-voice` | 同じ送信で吹き出しと読み上げが1回ずつ届くこと、読み上げがVRChatのマイクに届いてVRChatの再生で1回だけ確認できること | `--vrchat-voice`、Irodori、GPU |
| `vr-ui` | VR UIの表示と操作（偽のSteamVR） | 開発ビルド |

モデルは、製品のカタログ（`src-python/models/model_downloads/catalog.py`）に載っているものだけです。`--fetch-models`を付けたときだけ、足りないモデルを製品と同じダウンローダーで`~/.cache/vrct-vox-acceptance`へ取得し、容量とSHA-256を照合します。取得する量は、全部で約3.6 GBです。付けなければ何も取得せず、モデルが足りないグループは、足りないものの名前を示してスキップします。音声認識の試験が聞く音声は、製品のTTSで合成するので、人の録音は要りません。

`--fetch-runtimes`は、RVCとSeed-VCの実行環境を、製品の設定画面と同じ仕組みで同じフォルダーへ用意します。取得は約11 GB、ディスクは約17 GBです。uv、Pythonのパッケージ、ソース、モデルは、固定した版とハッシュで照合します。モデルの読み込みは、任意のコードを実行しない方式（`weights_only=True`）です。

`--vrchat`は、チャットボックスのラボのVRChatを2つ、このPCの中だけの非公開のインスタンスで起動し、往復の試験を流してから終了します。VRChatのアカウントは、このPCでサインイン済みのものです。

`--vrchat-voice`だけは、試験専用のPipeWireグラフではなく、このPCの実際の音声経路を使います。`tools/vrchat_voice_host.py`が次の準備をして、終わったら元へ戻します。

- VRChatの再生だけが入る出力先（`vrct.native.replay`）を作り、VRChatの再生をそこへ移す。VRChatのマイクは、管理対象の仮想マイクのまま
- 管理対象の経路をミュートにする
- VRChatのメニューを専用のydotooldで操作し、「オーディオと声」のマイクテストを開く。試験の間だけ「ノイズを抑制」をオフにする（合成音声の一部を削るため）

メニューの操作は位置で行い、手順ごとに画面を見本画像と照合する方式です。合わないときは、見えた画面を保存して止まります。VRChatの版や表示言語が変わったら、`python tools/vrchat_voice_host.py calibrate`で見本を撮り直してください。

ストリームを移すと、WirePlumberはVRChatの出力先を覚えます。復元ではそれを消し、VRChatが既定の出力に従う状態へ戻します。試験が途中で止まったときは、`python tools/vrchat_voice_host.py restore`を実行してください。

実行した試験と実行しなかった試験を、リリースノートの「既知の制限」に書いてください。

操作できなかった部品があるときは、試験の出力先の`blocked-<操作>.json`を見てください。何が覆っていたかと、開いていたダイアログを記録してあります。

## WindowsのWebView2とインストール時の通信

現在のビルドでは、`src-tauri/tauri.conf.json`の`bundle.windows.webviewInstallMode`を省略しているため、Tauriの既定の`downloadBootstrapper`（`silent: true`）を使います。ローカルの`@tauri-apps/cli/config.schema.json`とビルド設定で確認した動作です。今回、このモードは変更していません。

NSISインストーラーは、HKLMとHKCUのレジストリにWebView2 Runtimeのバージョンが見つからない場合、Microsoftの`https://go.microsoft.com/fwlink/p/?LinkId=2124703`からブートストラッパーを取得して実行します。ブートストラッパーもMicrosoftへ接続し、WebView2 Runtimeを取得します。Microsoftとリダイレクト先にはIPアドレスや要求の情報が伝わります。`embedBootstrapper`を選ぶビルドでも、同梱するのはオンライン取得用のプログラムなので、実行時の通信は残ります。既存Runtimeを検出した場合、この取得・実行は省きます。

この経路はWindowsへのインストール時の通信で、無効にしているアプリ内更新や、同意が必要なモデル取得とは別です。現在のテンプレートでは、ブートストラッパーの版・SHA-256を固定せず、アプリ独自の署名検証や実行時間の上限も設けていません。ブートストラッパーが実際に使う追加の接続先と送信内容、Windowsでの実行は未検証です。公開前のWindows実機検証では、Runtimeがある場合とない場合の両方を確認してください。

アプリ本体はGitHub Releasesから取得し、SHA-256を照合してから展開します。パッケージ容量を調べるcurlのHEAD要求には、接続10秒・1試行全体30秒の上限を設けています。再試行は最大2回で、開始できる期間も30秒に制限しています。最後の試行はその期間を越えて続く場合がありますが、その試行にも30秒の上限が適用されます。容量を取得できない場合は、既存の1ストリームでの取得に進みます。SHA-256ファイルの取得上限は30秒で、大きなアーカイブの転送には別の監視処理があります。

Windowsの更新では、既定の「アンインストールしてからインストール」を選んでも、取得前に旧版を削除しません。`$INSTDIR\.upd\new`へ展開し、tarの成功、実行ファイル、`_internal`フォルダーを確認してから、アプリが動いていないかをもう一度調べます。新規インストールと、`/S`・`/P`でも同じ段階的な置き換えを使います。同じ版の「アプリをアンインストール」は、明示的な削除操作なので従来どおりその場で実行します。

インストーラーとアンインストーラーは、動いているアプリを調べるときに`vrct-vox.exe`と`vrct-vox-sidecar.exe`の両方を探します。`vrct-vox.exe`を強制終了するとサイドカーは自分の監視が止めるまで1〜2分残り、実行ファイルを消せず、終了時に`config.json`を書き直すことがあるため、サイドカーも終了させます。

tarは引数をANSIコードページで受け取るので、ユーザー名などにその外の文字があると、引数に書いたパスのアーカイブも展開先も開けません。作業ディレクトリは引数ではなく、Unicodeのまま扱われます。そこでtarの作業ディレクトリを`$INSTDIR\.upd\new`にし、`$TEMP`のアーカイブを隣の`$INSTDIR\.upd`へ移してから、ASCIIだけの相対パス（`..\VRCT-VOX.zip`）を渡します。8.3形式の名前には依存しないので、8.3形式の名前がないボリュームでも同じように動きます。展開に失敗したアーカイブは`$TEMP`へ戻し、再取得と`.bad`の保存に使います。`$TEMP`とインストール先が別のドライブなら、この移動でアーカイブをコピーするので、その時間がかかります。インストール先のドライブの容量検査にもアーカイブの分を足しています。

置き換え中は`.upd\committing`を残し、旧アプリの各項目を`.upd\old`へ退避します。新しく追加する項目は`.upd\add`に記録します。`_internal`はフォルダーごと置き換えるため、旧版だけの依存ファイルは残りません。`config.json`、`weights`、`logs`、`telemetry_state.json`、利用者のログはそのまま保持します。旧版と展開済みの新版が同時に存在するため、容量の検査は既存ファイルに加えて必要になる空き容量を調べます。

置き換えに失敗したら追加分を`.upd\discard`へ移し、退避した旧ファイルを戻します。次回の実行時にもマーカーを調べ、中断した置き換えを先に戻します。復元できないファイルがあれば、旧ファイルとマーカーを削除せず、保存場所を表示して停止します。この場合は使用中のアプリを閉じて再実行し、`.upd`を手動で削除しないでください。復元が完了した後の作業フォルダーの削除に失敗しても、次回に残りを削除できます。転送の失敗・再試行では、パッケージの通信を停止し、終了を待ってから一時ファイルを削除します。最終的な展開失敗時の`.bad`アーカイブは診断用に残します。

WiXからの移行では検証・展開の後に旧アンインストーラーを実行します。NSISの旧版と同じ場所に更新する場合、旧アンインストーラーは実行しません。別の場所への移行では、新版の配置が成功してから旧版を削除し、その後にレジストリを更新します。旧版の削除失敗は警告として扱います。ファイルの置き換えが完了したマーカーは、別の場所の旧版削除やレジストリ更新より前に消します。マーカーを消せない場合でも、旧版を戻せる状態で停止するためです。

アンインストールでアプリのデータの削除を選んだ場合は、`config.json`の隣に置くデータ（`config.json`、読めなかった設定の退避ファイル、`voice_mute_state.json`、`downloaded_models`、ログ、`weights`、`telemetry_state.json`）も消します。この項目は既定では選ばれておらず、選ばなければこれらは残ります。

回帰試験は[installer-update-tests.yml](../../.github/workflows/installer-update-tests.yml)で実行します。手動実行と、NSIS・試験スクリプト・同ワークフローを変更するPRが対象です。Windowsジョブのcheckout内だけで取得先をローカルHTTPサーバーに書き換え、軽いダミーのペイロードを実際のNSISインストーラーで取得・展開します。サイレント試験では成功時のファイル置き換えと利用者データの保持、ANSIコードページの外の文字を含むフォルダーへのインストール、各失敗時のパス・ハッシュの一致、ロールバック、中断からの復旧、Range失敗時の単一接続への切り替えを調べます。インストーラーを作らずに実際のtarだけを確かめるときは、`python tests/installer/windows_update_scenarios.py --mode tar`を使います。GUIの既定選択はpywinautoを使う別ステップで確認します。これは実際の音声処理や配布用ペイロードの動作試験ではありません。

## ローカル検査

```bash
python tools/release_candidate.py verify path/to/candidate \
  --platform linux --commit <40桁のコミットSHA> --version 0.1.0
python tools/dev.py check --scope voice
```

このハッシュ照合は、記録した候補が転送中に変わっていないことを調べるものです。電子署名やコードの安全性認証ではありません。GitHubのartifactダイジェスト不一致は警告になるため、別途この検査で失敗させています。[GitHub公式の説明](https://docs.github.com/en/actions/tutorials/store-and-share-data#validating-artifacts)
