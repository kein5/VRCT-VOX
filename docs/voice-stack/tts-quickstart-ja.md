# GUIから日本語テキストを読み上げる

AppImageにはspeech.cppの実行ファイルを同梱している。音声モデルは別途指定する。
まずイヤホンへの出力で確認し、その後VRChat用の仮想マイクへ切り替えられる。
以下は現在の英語GUIの項目名。

1. メイン画面の歯車から **Advanced → Text to voice (speech.cpp)** を開く。
2. **Bundled speech.cpp servers → Japanese TTS** の **Model GGUF path** に
   既存のIrodori GGUFモデルのフルパスを入力する。`~`も利用できる。
   **Voice GGUF path (optional)** は空欄、**Inference device** は **Automatic** にする。
3. **Save server settings** を押した後、Japanese TTSの **Start server** を押す。
   **Ready** になるまで待つ。保存だけではモデルを起動しない。
4. 上側の読み上げ設定を次の値にして **Save voice settings** を押す。

| 項目 | イヤホンで試すときの値 |
|---|---|
| Read aloud | Original text |
| Japanese server | Bundled server |
| Japanese voice name | none（Irodoriの標準音声） |
| Audio route | Existing external cable |
| Virtual cable playback device | 使用中のイヤホン／スピーカー |

出力欄の名前はVirtual cableだが、Linuxでは通常の再生デバイスも選べる。
出力先がなければ **Refresh devices** で更新する。

5. ミュート中なら **Resume voice** を押し、**Voice enabled (confirmed)** を確認する。
6. メイン画面に戻り、**Your Language = Japanese (Japan)** を選ぶ。
   下部の入力欄へ日本語を入れて送信すると読み上げる。

発声の途中停止は **Stop playback and clear queue**。
以後の発声も止める場合は **Mute until resumed**。
アプリ再起動後、同梱サーバーは停止状態に戻るため、必要な枠を再度起動する。

このPCで取得済みの日本語モデルは次の場所にある（2026-10-29確認）。新規取得は不要。

```text
~/.cache/speech.cpp/models/sakasegawa--Irodori-TTS-v4.1-Small-MF-GGUF/e237dc3eefe469b8bba87872beacf12fb7fe00dbdf85767edca8ec04ab910d13/Irodori-TTS-866M-MF-v4.1-F16.gguf
```

## VRChatへ送る場合

先に[管理対象のPipeWire仮想マイク](local-setup-linux.md#常駐する管理対象の仮想マイクb検証後の追加)を
ホストへ設定する。音声サービスの再起動が必要なので、通話等の中断が問題ないタイミングで行う。
AppImageのインストールだけでは、このホスト設定は自動作成されない。

- VRCTの **Audio route** を **Managed virtual microphone (Linux)** にして保存し、**Resume voice**。
- VRChatの入力を **VRCT Managed Virtual Microphone** にする。

2026-10-29の今回の案内時点では、このPC上にVRCT用の仮想sink/sourceは存在しなかった。
上記の確認では設定変更・モデル起動・発声・録音を行っていない。

翻訳結果を読む場合は **Read aloud = Translated text** と対象の **Translation slot** を選ぶ。
発声する言語に対応するサーバーも必要で、日本語以外は多言語枠（Qwen3-TTS等）を使用する。
TTSエンジンと翻訳エンジンの設定は別。
