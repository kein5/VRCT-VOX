# 接続受付監視の修正後にVRChatで再試験する

2026-10-27。**実speech.cpp→managed仮想マイク→VRChatの通常発声・停止・mute・故障復旧の11ケースがPASS。**
サーバー強制終了から仮想マイクの無音化まで、3回とも79〜84msだった。
対象は[接続受付監視の修正](tts-listener-failure-report.md)を含むcommit `98017be8`。
今回は製品コード・試験runnerを変更せず、ホストでの測定と記録を追加した。P1全体・B全体の採用確定ではない。

## 条件と結果

speech.cpp 0.9.0、既存Irodori-TTS-866M-MF-v4.1-F16、Vulkan0 / RTX 4080 SUPER、voice=`none`、48kHz mono s16le。
binaryとmodelのSHA-256を再確認し、前回と同一だった。起動ごとにserver標準warmupを有効にした。
VRChatはdesktop `--no-vr`、日本語UI、ノイズ抑制OFF、マイク音量75%、閾値10%。
実VoiceEventBusへ要求を投入し、その要求でHTTPから届いたPCMを基準に照合する。

| ケース | 結果 |
|---|---|
| 通常発声3回 | 仮想マイク・VRChat内蔵マイクテストのデジタル再生で各1回。再生包絡相関0.9952 / 0.9681 / 0.9969 |
| 発声中のTTS取消 | 操作開始→連続無音の最初のreadまで78.843ms。その後も無音を維持、全体gateは解除状態を維持 |
| 発声中の保持mute | 同81.266ms。新TTSを拒否して推論要求数も増えず、約23.989秒のマイク録音は全sample 0 |
| mute中のVRChatマイクテスト | 既知の発声音声の検出0回。メニュー音があるため、再生側の全sample 0は要求しない |
| サーバー強制終了3回 | 無音化79.399 / 83.632 / 84.037ms。いずれも`server_unavailable`、個別条件250ms以内を満たす |
| サーバー停止中の新要求3回 | `transport_error`、新たな音声なし |
| 再起動後の新発話3回 | マイク・VRChat再生で各1回。再生包絡相関0.9990 / 0.9822 / 0.9986 |

source identity `(636532002, 44)` とVRChatの入出力先は、開始時・全11ケース終了時で一致した。
全時点のgraph監視ではない。連続音声観測は11,118 frame、100ms超read間隔0、最大61.273ms。
マイクと専用再生sinkの計14ファイルで、sample数・read間隔・終端時刻・process生存の検査がすべて通った。
readerの停止を無音として扱っていない。

muteのraw結果にある`replay.verdict: fail`は、共通の「1回再生」比較関数が検出0回に返す値。
このケースの条件は検出0回であり、runnerはその値を判定している。raw記録を`pass`へ書き換えていない。

## 測定境界と判断の限界

初音の始点はハーネスでの`SpeechMessageEvent`生成。同じmonotonic clockを使用する。

| 試行 | event→最初のHTTP PCM | event→最初の非ゼロwrite | event→仮想マイク音検出 |
|---|---:|---:|---:|
| 通常1 | 69.353ms | 81.552ms | 146.165ms |
| 通常2 | 59.885ms | 71.660ms | 149.148ms |
| 通常3 | 59.842ms | 71.013ms | 318.183ms |
| 復旧1 | 62.669ms | 75.172ms | 362.081ms |
| 復旧2 | 59.487ms | 72.248ms | 108.913ms |
| 復旧3 | 67.076ms | 79.613ms | 322.883ms |

HTTPの最初のframeはゼロ値を含み得る。writeは非ゼロsample、sourceは20ms frame内のpeak >64/32768を検出したread時刻。
生成音声の先頭無音、閾値、OS schedulingを含むため、列の差をすべてOS経路の遅延とはしない。
小数桁は計算上の桁数であり物理精度ではない。通常3回と復旧3回は分け、p95/p99や上限保証を出さない。

停止の始点はcancel/mute呼出またはserver killの直前、終点は2秒以上続く無音区間の最初のread。
**取消・故障停止の値は、VRChatが接続した仮想マイクでの値である。** 途中で切った長文をVRChatマイクテストで
別途録音・再生して停止時間を測った値ではない。通常・復旧の各発声とmute中の無音入力はVRChat再生も照合した。
VRCTのGUI入力、一般dispatch、翻訳、物理ADC/DAC、ネットワーク、別プレイヤー受信は含まない。

[修正前ホスト](live-tts-vrchat-report.md)では故障後約5.1秒の音声が残った。
今回はその故障シナリオが250ms条件を満たしたが、seed・背景負荷を統制した対応比較ではなく、改善倍率は出さない。
独立PipeWireの30反復とも統合しない。今回の故障n=3はp95≤100msの証拠には使わない。
FPS、xrun、CPU/GPU/VRAMの連続負荷・30分継続・知覚音質は未測定。

## 再実行と証拠

[既存runner](../../tools/live_tts_acceptance.py)を使用する。Linux、既存モデル、speech binary、native gate、
managed経路、専用ydotooldとVRChat再生sink、現在の画面から採ったready/recording画像が必要。
[ホスト経路の準備](local-setup-linux.md#常駐する管理対象の仮想マイクb検証後の追加)と
[GUI準備](vrchat-gui-poc-report.md#再実行)を済ませ、native sourceをmuteにして実行する。

```sh
uv run --no-project python tools/live_tts_acceptance.py \
  --model /path/to/existing-Irodori-MF-F16.gguf \
  --samples 3 --crash-repeats 3 --output /tmp/tts-fixed-host-new \
  --window '<VRChat UUID>' --socket /tmp/<専用ydotool socket> \
  --replay-sink <VRChat専用sink> \
  --ready-image /path/to/ready.png --recording-image /path/to/recording.png
uv run --no-project python -m pytest -q tests/voice
```

runnerはホスト設定配置・アプリ起動・メニュー探索・後片付けを行わない。
今回は初期設定を画面確認しながら行い、準備後の11ケースを自動実行した。受入れシーケンスは1試行で完走した。
準備ではKWinのactive windowとXWayland入力focusが不一致で、対象PIDを照合してfocusを修正した。
一度のpointer不収束はclick前に停止し、同じwindowの最小化・再表示で解消した。入力・画面・経路のguardは緩めていない。
準備時の問題は音声送信前であり、受入れ試行の失敗と混同しない。

音声suiteは**180 PASS**。最初のsandbox実行はsocket作成拒否で39 FAIL / 141 PASS。
全39件が同じ`PermissionError`であることを確認し、localhost socketを許可した環境で再実行した。
全体pytestは従来と同じ80ファイルで依存不足のcollection error。全体合格とはしない。
製品・テストコードに変更がないため、Ruffは再実行していない。

[全ケース・hash・回帰試験・復元結果](measurements/2026-10-27-tts-fixed-vrchat.json)に測定値を保存した。
raw PCM/WAV、画面画像、serverログはgitignore対象の`tmp/tts-fixed-vrchat/`に保持し、配布しない。
既存モデルの使用のみで追加取得・外部コードの取り込み・binary同梱はない。
[ライセンス台帳](licensing.md)の境界を維持する。

終了時はVRChat入力をP1、ノイズ抑制をONへ戻し、今回起動したVRChat・ydotooldとspeech server 4 processを終了した。
一時drop-inとmanaged/replayノードを除去し、旧P1を元と同じ引数のuser service
`vrct-p1-restored-1793102109`で再作成した。既定sink/source、音声3サービス、残留ストリームなしを確認。
元から起動していたWiVRn processは維持した。後片付け時のpactl JSON形式差と未対応の版表示による
記録処理の中断も測定JSONに残し、実際の形式に合わせて復元確認を完了した。

## 次に検証する範囲

次は実VRCT UI/APIから原文を送信し、既存dispatchを通る経路を検証する。
OSC・履歴・翻訳との互換性、音声OFF、UIからの取消・全体mute、復旧時に古い発話を再送しないことを確認する。

listenerが開いたままのモデル停止・HTTP接続単独故障・port即時再利用は今回の早期検出範囲外。
Windows、実VC、ASR/翻訳とのGPU混在、ノイズ抑制ON、WiVRn/HMD、物理イヤホン、別プレイヤー受信も未検証。
これらを満たす前にBの製品採用やP1全体の完了へ変更しない。
