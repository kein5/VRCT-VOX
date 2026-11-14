# vrct-speech-server

同梱の speech.cpp サーバ（TTS 用2つと ASR 用1つ）のプロセスを所有する Rust クレートです。起動、停止、再起動、死活監視を受け持ちます。Issue #276 の範囲で、`src-python/models/speech_server/` の置き換え先です。

speech.cpp の実行ファイルは従来どおり別プロセスです。このクレートが持つのは管理層だけで、推論はしません。

## 現在の状態

- ライブラリとして完成しており、試験も通っています。**アプリにはまだ組み込んでいません。** 動作中のアプリでサーバを所有しているのは、今も Python 側（`models/speech_server/runtime.py`）です。同じサーバを2か所から所有しないよう、Tauri 側の配線は、Python 側の呼び出しを置き換えるとき（#278 と協調）に行います。
- `src-tauri` はこのクレートに依存していません。

## Python 版との対応

| Python（`models/speech_server/`） | Rust |
|---|---|
| `settings.py`（`normalize_settings`、`start_options`） | `settings` |
| `runtime.py` の `bundled_binary` | `bundle::bundled_binary` |
| `runtime.py` の `parse_devices`、`preferred_gpu`、`resolve_device`、`list_gpus` | `devices` |
| `runtime.py` の `SpeechServer` | `server::SpeechServer` |
| `runtime.py` の `SpeechServers` | `servers::SpeechServers` |
| `warmup.py` | `warmup` |
| `low_latency.py` | `standby::LowLatencyStandby` |

設定ファイルの形、状態名（`stopped`、`preparing`、`ready`、`stopping`、`failed`）、エラーコードの文字列は Python 版と同じです。エラーコードは `codes` にまとめてあります。

## Python 版と違う点

- **Linux での所有の仕組み**。Python 版は補助プログラム `vrct-vc-worker` を挟み、起動したスレッドの pidfd を監視させていました。Rust 版は補助プログラムを使わず、子プロセスに `PR_SET_PDEATHSIG(SIGKILL)` を設定します。このシグナルは、子を起動したスレッド（サーバごとの監視スレッド）が終わったときに届きます。アプリが異常終了したときにサーバが残らない、という約束は同じです。
- **Windows での所有の仕組み**は同じです。子を停止状態で作り、閉じると終了するジョブに入れてから再開します。省電力による速度制限を外す指定も同じです。
- **音声出力の監視との連携**。Python 版は TTS 用サーバの待ち受けポートを `listener_monitors` に直接登録していました。Rust 版は `Hooks::on_listener` で呼び出し側に知らせます。
- **失敗の通知**。Python 版の `report_failure` に当たるものは `Hooks::on_failure` です。利用状況イベントへの送信そのものは、このクレートにはありません。
- **ウォームアップ用の雑音**。長さ（6秒）と大きさは同じですが、乱数の列は Python 版と一致しません。結果は捨てるので、動作には影響しません。
- **低遅延スタンバイ**。Python 版は、最初にモデルが `seed` を受け付けるかを問い合わせていました。Rust 版は問い合わせず、`seed` を付けた要求が 200 以外で返ったらスタンバイを失敗にします。

## ログとデータ

サーバが出力した行、モデルのパス、文章、音声は、ログにも戻り値にも入れません。サーバの標準エラー出力から読み取るのは、待ち受けポートの行と、`out_of_memory`・`device` の2種類の失敗分類だけです。

## 試験

```sh
cargo test --locked --manifest-path native/speech-server/Cargo.toml
# または
python tools/dev.py check --scope rust
```

試験は、speech.cpp の代わりをする小さな実行ファイル（`tests/fixture/fake_speech.rs`）を実際に起動して、プロセスの起動から終了までを確かめます。モデルも GPU も使いません。この実行ファイルはアプリのビルドには含まれません。

実物の speech.cpp とモデルで確かめるときは、環境変数を指定します。指定がなければ、この試験は何もせずに通ります。

```sh
VRCT_SPEECHCPP_BUNDLE=<build/speechcpp のフォルダ> \
VRCT_SPEECH_MODEL=<TTS モデルの .gguf> \
VRCT_SPEECH_DEVICE=cpu \
cargo test --manifest-path native/speech-server/Cargo.toml --test real --test devices -- --nocapture
```
