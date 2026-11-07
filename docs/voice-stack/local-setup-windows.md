# Windowsで音声機能を使う

Windowsでは、TTS、同梱のspeech.cppサーバー、リアルタイム字幕、RVCを使えます。Linuxと違い、アプリは仮想マイクを作れません。VRChatへ声を届けるには、別途インストールした仮想ケーブルを使います。

この手順の実機確認の記録は[Windows音声の検証記録](windows-voice-report.md)にあります。実マイク、VRChatの画面、実機のケーブル製品での確認はまだ終わっていません。

## 必要なもの

- GPUドライバー。同梱のspeech.cppはVulkan版で、ドライバーが入れる`vulkan-1.dll`を使います。ないとサーバーは起動しません。
- 仮想ケーブル。VB-CABLEなど、再生側と録音側の組になった製品を手動で入れます。アプリは入れません。
- モデル。音声モデルは設定画面の取得欄から、ライセンスとサイズを確認して取得します。

## 音声の経路

1. 設定の「TTS」で、出力デバイスにケーブルの**再生側**（例: CABLE Input）を選びます。
2. VRChatのマイクに、ケーブルの**録音側**（例: CABLE Output）を選びます。

TTSとRVCは、どちらもこの出力デバイスに書き込みます。Windowsの音声エンジンが2つの音を混ぜます。物理マイクをケーブルへ直接つながないでください。入力にケーブルの録音側を選ぶと、声が自分に戻るので開始を拒否します（`vc_feedback_blocked`）。

ミュートは、TTSと、出力デバイスへ送る声の両方に効きます。OS側に遮断の仕組みがないので、アプリが無音に置き換えて書き込みます。ストリームは動き続けます。

## TTS

設定の「TTS」でモデルを取得し、サーバーに「同梱」を選びます。メイン画面のTTSスイッチをオンにすると、サーバーが起動します。外部で動かすspeech.cppサーバーのURLを指定することもできます。

## リアルタイム字幕

設定の「音声認識」→「リアルタイム字幕」で、サーバーに「同梱」を選び、ASRとVADのモデルを設定します。すると、メイン画面のマイクと聞き取りのスイッチがこの経路を使います。「外部」のままなら、スイッチは従来の録音（WhisperとGoogle）を使います。リアルタイム字幕の設定画面の開始ボタンは、どちらの選択でも使えます。

聞き取りはWASAPIのループバックで、選んだスピーカーに流れる音を読みます。何も再生していない間は、無音として扱います。

## RVC

RVCの実行環境はアプリに含みません。次の構成のフォルダーを用意し、RVCの設定で指定します。NVIDIAのGPUが必要です。CPUでは実時間に間に合いません。

```text
runtime\
  venv\Scripts\python.exe
  engine\                 RVC本体のGitチェックアウト（コミット固定）
  assets\hubert_base\     config.json、preprocessor_config.json、pytorch_model.bin
  assets\rmvpe\rmvpe.pt
```

依存はハッシュ固定のWindows用ロックから、アプリのvenvとは別のvenvへ入れます。

```powershell
uv venv --python 3.12 runtime\venv
uv pip install --python runtime\venv\Scripts\python.exe --require-hashes `
  --index-url https://download.pytorch.org/whl/cu128 -r integrations\rvc\requirements-cuda-windows.lock
uv pip install --python runtime\venv\Scripts\python.exe --require-hashes `
  -r integrations\rvc\requirements-windows.lock
```

RVC本体は[README](../../integrations/rvc/README.md)のコミットで取得します。作業ツリーの検証に`git`が必要で、改行を変えないよう`core.autocrlf=false`で取得してください。

```powershell
git init runtime\engine
git -C runtime\engine remote add origin https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git
git -C runtime\engine config core.autocrlf false
git -C runtime\engine fetch --depth 1 origin 81eed5e8f68b6bed1789f682fe78cdd324495afc
git -C runtime\engine checkout FETCH_HEAD
```

基礎モデルと声のモデルは、権利を確認してから用意します。起動にはTorchの読み込みで数十秒から数分かかるので、開始直後は準備中のままになります（上限は180秒です）。

RVCを止めている間も声を届けたいときは、入力の転送を使います。マイクの音をそのまま出力デバイスへ送ります。Seed-VCはWindowsでは使えません。

変換の速さはGPUと負荷に左右されます。ワーカーは起動時に実測し、80 msのブロックに余裕を持って収まるよう、参照する過去の音声の長さを2秒から1秒、0.5秒へ縮めます。それでも追いつかないときは、入力のあふれ（`vc_capture_overrun`）か期限切れ（`vc_block_expired`）で停止します。声の代わりに原音を流すことはありません。

## モデル不要のテスト

```powershell
python tools/dev.py setup --scope headless
python tools/dev.py check --scope voice
```

Windowsの実デバイスへ接続する場合はPyAudioWPatchが必要です。`npm run setup-python`（`uv sync`）で作る`.venv`には入りますが、`headless`のvenvには入りません。
