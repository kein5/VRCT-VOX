# P1 Linux / CachyOS / WiVRn

ヘッドレスCLIはWindowsのPyAudioWPatch/pycaw/windows-captureをimportしない。
Pythonは標準ライブラリだけで発声でき、`pw-cat` / `pw-dump` が必要。
VRCT全GUIのLinux互換化はP5。以下は実機確認用手順で、実VRChatで未検証。

## 一時的な仮想マイク

既存の音声設定を置換せず、端末で一時loopbackを起動する。
[PipeWire loopback原典](https://docs.pipewire.org/page_module_loopback.html)のsink/source構成を使う。

```sh
pw-loopback --capture-props='media.class=Audio/Sink node.name=vrct.voice.sink node.description="VRCT Voice Input" audio.position=[MONO]' --playback-props='media.class=Audio/Source node.name=vrct.voice.source node.description="VRCT Virtual Microphone" audio.position=[MONO] node.passive=true'
```

`pw-dump` / `pw-link -l` / `wpctl status` でsink/sourceが作られたことを確認。
VRChatのマイクを **VRCT Virtual Microphone** に指定する。
物理マイク、ゲーム出力、WiVRn音声をこのsinkへ直接リンクしない。
終了時はloopback端末でCtrl-C。一時ノードだけが消える。

## speech.cpp→仮想マイク

ユーザーが許諾確認して用意済みのローカルモデルで起動（以下はパス例）。
参照音声を使わない場合は `none`。使う場合は本人同意済みのvoice.ggufを登録。

```sh
speech serve /path/to/Irodori-TTS-866M-MF-v4.1-F16.gguf --host 127.0.0.1 --port 8080
uv run --no-project python tools/voice_cli.py doctor
uv run --no-project python tools/voice_cli.py devices
uv run --no-project python tools/voice_cli.py speak --device vrct.voice.sink --language ja --text 'こんにちは'
```

CLIは`X-Sample-Rate`の実rateを[pw-cat](https://docs.pipewire.org/page_man_pw-cat_1.html)へ渡し、
必要なrate変換はPipeWireが行う。OS既定出力は使わない。
`measurement_boundary=event_to_first_pcm_write` は仮想マイク到達の測定ではない。
終了コード0はPCM出力処理の完了であり、VRChatの聞こえを保証しない。

## 手動受入とP2入口

- VRChatのマイクテストで1回だけ聞こえるか。停止/Ctrl-C後に音声が残らないか。
- loopbackを削除→エラー、物理スピーカーへのfallbackなし。復元→明示再選択後に新しい文で再試行。
- WiVRn入力/出力を図示し、ゲーム音声・TTS monitorを将来のASR入力から除外する。
- P2外部VC: 別ソフトの入力を物理マイク、出力を**変換専用sink**へ設定して単体確認。
  生マイクの自動fallbackがない設定を確認するまでVRChatへつながない。
  VC停止時の無音、モデル/OS/版、遅延、VRAM、利用条件を記録して採用判断する。
  P1のTTS sinkへ直接混ぜる操作はP2 routerの検証後に行う。
