# GUIから日本語テキストを読み上げる

AppImageにはspeech.cppの実行ファイルを同梱している。音声モデルは別途指定する。
まずイヤホンへの出力で確認し、その後VRChat用の仮想マイクへ切り替えられる。
以下は現在の英語GUIの項目名。

1. メイン画面の歯車から **TTS** を開く。RVCは隣の専用ページ、共通の音声経路は **Device** にある。
2. **Bundled speech.cpp servers → Japanese TTS** の **Model GGUF path** に
   既存のIrodori GGUFモデルのフルパスを入力する。`~`も利用できる。
   **Voice GGUF path (optional)** は空欄、**Inference device** は **Automatic** にする。
3. **Save server settings** を押した後、Japanese TTSの **Start server** を押す。
   **Ready** になるまで待つ。保存だけではモデルを起動しない。
4. 上側の読み上げ設定を次の値にして **Save voice settings** を押す。

| 項目 | イヤホンで試すときの値 |
|---|---|
| Chat voice | Original text |
| Japanese server | Bundled server |
| Japanese voice name | none（Irodoriの標準音声） |
| Audio route（Deviceページ） | Existing external cable |
| Output device | 使用中のイヤホン／スピーカー |

Linuxでは通常の再生デバイスも選べる。
出力先がなければ **Refresh devices** で更新する。

5. ミュート中なら **Device → Resume voice** を押し、**Voice enabled (confirmed)** を確認する。
6. メイン画面に戻り、**Your Language = Japanese (Japan)** を選んで **TTS** をONにする。
   下部の入力欄へ日本語を入れて送信すると読み上げる。

トップの **TTS OFF** は読み上げ受付・再生・待ち行列を止める。直接入力・RVC・翻訳・OSCは継続する。
TTSページの **Stop playback and clear queue** は現在の発声と待ち行列だけを止める。
Deviceページの **Mute until resumed** は共通経路全体のミュートなので、TTS OFFとは用途が異なる。
アプリ再起動後はTTS受付と同梱サーバーがOFFに戻る。必要な枠を起動してからTTSをONにする。

各言語枠の **Seed mode** は既定でランダム。**Specify a value** では0を含む整数を指定できる。
**Instruction** は声の出し方の指示で、読み上げ本文とは別に送信する。モデルの対応状況を確認し、
非対応の場合は値を空にして通常のTTSを使う。保存だけではモデル・マイク・発声を開始しない。

RVCは **RVC** ページでモデルとランタイムを保存し、入力マイクを選んでトップの **RVC** をONにする。
開始待ちもOFFで取り消せる。原音やSeed-VCが動作中なら、その設定ページで先に停止する。
入力の選択はページ移動では保持するが、再起動やデバイス再接続後は明示的に選び直す。

このPCで取得済みの日本語モデルは次の場所にある（2026-10-29確認）。新規取得は不要。

```text
~/.cache/speech.cpp/models/sakasegawa--Irodori-TTS-v4.1-Small-MF-GGUF/e237dc3eefe469b8bba87872beacf12fb7fe00dbdf85767edca8ec04ab910d13/Irodori-TTS-866M-MF-v4.1-F16.gguf
```

## VRChatへ送る場合

先に[管理対象のPipeWire仮想マイク](local-setup-linux.md#常駐する管理対象の仮想マイクb検証後の追加)を
ホストへ設定する。音声サービスの再起動が必要なので、通話等の中断が問題ないタイミングで行う。
AppImageのインストールだけでは、このホスト設定は自動作成されない。

- VRCTの **Device → Audio route** を **Managed virtual microphone (Linux)** にして保存し、**Resume voice**。
- VRChatの入力を **VRCT Managed Virtual Microphone** にする。

2026-10-29の今回の案内時点では、このPC上にVRCT用の仮想sink/sourceは存在しなかった。
上記の確認では設定変更・モデル起動・発声・録音を行っていない。

翻訳結果を読む場合は **Chat voice = Translated text** と対象の **Translation slot** を選ぶ。
発声する言語に対応するサーバーも必要で、日本語以外は多言語枠（Qwen3-TTS等）を使用する。
TTSエンジンと翻訳エンジンの設定は別。
