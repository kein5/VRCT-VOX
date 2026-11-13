# Windowsの実機試験

`tools/windows_field/`には、通常の`check`に含めない実機の試験があります。結果の記録は[Windows音声の検証記録](windows-voice-report.md)にあります。ここには手順だけを書きます。

どの試験も音声を保存しません。出力の確認は、音量の数値だけを残します。

Linuxで入れた変更のうち、Windowsの実機でまだ確かめていないものは、[Windowsで未確認の変更](windows-pending-checks.md)にあります。

## 準備

- `.venv`にアプリの依存を入れ、`build/speechcpp`に`speech.exe`を置きます（`npm run setup-python`）。
- 同意して取得したモデルを`build/model-test/win-voice/`に置きます。RVCの実行環境は`build/rvc-runtime`です。
- 英語の試験音声をWindowsの音声合成で作ります。音声ファイルはリポジトリに入れません。

```powershell
.venv\Scripts\python.exe tools\windows_field\make_speech.py
```

別の場所にあるチェックアウトの`build/`を使うときは、環境変数`VOX_FIELD_ROOT`にそのフォルダーを指定します。SteamVRの場所が既定と違うときは`VOX_STEAMVR`を指定します。

## 長時間の運転

```powershell
.venv\Scripts\python.exe tools\windows_field\win_soak_full.py 1800 run-name realtime Vulkan1
```

引数は、秒数、結果のフォルダー名（`build/model-test/`の下）、`realtime`または`whisper`、speech.cppの装置です。実物のSteamVRをnullドライバーで起動します。設定とログは`VR_CONFIG_PATH`と`VR_LOG_PATH`で一時フォルダーへ逃がすので、普段の設定は変わりません。マイクは試験用のフックで開けないようにします。開こうとした回数は`mic-guard.log`に残ります。

音声は、無音の仮想出力`Speakers (Steam Streaming Microphone)`へ流し、そのループバックを入力にします。Steam Remote Playの仮想デバイスが要ります。

VRChatと同時に試すときは、VRChatを`--no-vr`で起動してから、環境変数`VOX_NO_OSC_LISTENER=1`を付けて実行します。VRChatがOSCのポートを持っているからです。

変換の既定はRVCです。Seed-VCを試すときは、`VOX_VC_ENGINE=seed-vc`に加えて、実行環境のフォルダーを`VOX_SEED_RUNTIME`に、参照音声のWAVを`VOX_SEED_REFERENCE`に指定します。

ブロックの処理時間は、ふだんは変換が止まったときにしかログに残りません。`VOX_VC_PROBE`にファイルのパスを指定すると、直近75ブロックの往復時間、ブロックの遅れ、遅れたブロックの数を5秒ごとに書き足します。

GPUのキャッシュが空の状態を試すときは、`VOX_SHADER_CACHE`に空のフォルダーを指定します。RTXでは効きますが、Iris Xeで効くかは確かめていません。

結果は`summary.json`、`samples.csv`、`gpu-memory.json`、`results.jsonl`に残ります。

## 実マイク

利用者がPCの前にいるときだけ行います。凍結したサイドカーを`build/frozen-mic2/`に置いてから実行します。

```powershell
.venv\Scripts\python.exe tools\windows_field\win_mic_full.py
```

Windowsのマイクの確認は、利用者が答えます。試験の側から確認の画面を閉じたり、`PickerHost`を止めたりしてはいけません。答えないまま終わると、そのexeは次から確認なしで拒否されます。確認の画面を閉じるとファイアウォールのブロック規則が残ることもあります。

ターミナルに「話してください」と出たら、1文ごとに間をあけて読みます。`norvc`を付けるとRVCを省きます。`classic`を付けると従来の録音経路だけを試します。認識した文を含む`stdout.log`は、終了時に消します。

使うマイクは名前の一部（既定は`Surface`）で選びます。別のマイクを使うときは`VOX_MIC_LABEL`を指定します。`build/`の下の別のフォルダーにある凍結物を使うときは、`VOX_FROZEN`にフォルダー名を指定します。

従来の録音経路の閾値は、毎回、既定の300に設定します。`low`を付けると40にします。
