# P1 Windows手動試験

これは手順書であり、Windows/VRChat実機の合格記録ではない。
Python依存管理にはuvを使用する。Windowsのビルド依存と手順は
[ビルドガイド](../readme_build.md)も参照。

1. ユーザーが許諾を確認してspeech.cppと日本語モデルを別途用意する。
   実行バイナリcommit/hash、モデルID/hash、GPU/driverを[計測記録](benchmarks.md)に残す。
   以降は取得済みのローカルGGUFパスを使う（コマンドからモデルを自動取得しない）。
2. 手動で仮想ケーブルをインストール。VRCTの出力は **CABLE Input（再生側）**、
   VRChatのマイクは **CABLE Output（録音側）** を選ぶ。物理マイクをケーブルへ直接つながない。
3. 声を使う許可がある場合に一度だけ変換し、キャッシュしたvoiceをserveへ登録する。

```powershell
speech voice C:\models\Irodori-TTS-866M-MF-v4.1-F16.gguf C:\voices\consented.wav C:\voices\me.voice.gguf
speech serve C:\models\Irodori-TTS-866M-MF-v4.1-F16.gguf --host 127.0.0.1 --port 8080 --add-voice me=C:\voices\me.voice.gguf
```

参照音声なしは `--add-voice` を省略し、UIの声名を `none` にする。
他言語は別端末・8081等でローカルQwen3-TTS GGUFをserveし、そのURLと登録声名を設定する。

4. VRCT-VOXの設定の「TTS」ページで出力先を明示し、原文・声名・URLを保存。
   VRCT側の自分の言語を日本語にし、「こんにちは」を1回送信。
5. OSC Chatbox表示1回、VRChatマイクへの声1回、旧WebSocket payload形式を確認。
   上流作者のVRCT-TTSなど、同じCHATを読み上げる外部クライアントは停止する。
6. 訳文モードは有効な翻訳先の番号を1つ選ぶ。英語をIrodoriだけに送る場合は無音＋エラー。
7. OFFで既存と同じ送信。再生中に停止→キュー0、音声停止、次送信で再開。
8. サーバ停止/ケーブル削除/差し直しでUIが動き続け、スピーカー等への自動fallbackがない。
   デバイス一覧を更新して明示再選択。OS内の残留バッファ停止時間を実測する。

モデル不要テスト:

```powershell
python tools/dev.py setup --scope headless
python tools/dev.py check --scope voice
```

Windows CLIを実デバイスへ接続する場合はPyAudioWPatchが必要。`npm run setup-python`（`uv sync`）で作る`.venv`には入るが、`headless`のvenvには入らない。
ASRやVCはP1では有効化されない。通常のVRChatマイクミュートはゲーム内で操作する。
