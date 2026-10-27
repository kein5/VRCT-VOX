# 入力転送の本番UIと私有音声経路の検証

2026-10-28、明示した入力の選択・開始・停止を、本番Controller・stdio IPC・設定画面へ接続した。
実Tauriアプリから私有PipeWire仮想マイクまで**16ケースPASS**。
これはLinuxのpassthrough制御であり、外部エンジンによる実VCの成功・P2全体の完成ではない。
[接続基盤](source-bridge-report.md)と[実装計画](../superpowers/plans/2026-10-28-p2-source-controls.md)を前提にする。

## 使用方法と契約

設定のAdvancedにある音声設定で、経路を「管理対象の仮想マイク」にして保存する。
入力転送の一覧で入力を選び、開始する。選択だけでは開かず、開始しても全体ミュートは解除しない。
入力の停止はTTSを止めず、TTSの停止は入力を止めない。全体ミュートは仮想マイク全体を閉じる。
外部経路への設定変更、アプリ終了、入力喪失では転送を停止する。再起動時は自動再開しない。

入力identityはPipeWire core cookie・64bit serial・name・classをまとめて保持する。
cookie/serialは十進文字列でIPCを通す。同名デバイスが再作成されても選択を移さず、再選択を必要とする。
開始要求には受信時点のbackend世代を付ける。停止は通常queueを迂回して世代を無効化するため、
queueに残った以前の開始要求を後から実行しない。状態応答は同じlockで付けた単調observation_idで整列する。

Linux 6.9以降のthread pidfd機能とPipeWire/native helperが必要。Windowsの新入力転送は未対応を返す。
TTSの既存Windows出力契約は変更しない。新しい設定の自動開始・常駐推論・PCM Python処理は追加していない。
UIは「入力をそのまま転送」と表示し、`conversion_verified`はfalseのまま。

## 実測範囲と結果

本番Tauri・全Model初期化・Controller・HTTP PCM client・scheduler・OS経路を使用した。
モデル自動取得をOFFにした隔離config、DPMSガード、私有PipeWireを使用。
440Hzが選択入力、880HzがHTTPからTTS経路を通した合成PCM、1760Hzが誤った既定入力。
音声波形は保存せず、仮想マイクで20msフレームを読み、各条件を2秒以上継続確認した。
実マイク・ホスト音声設定・VRChat・WiVRn・実変換モデルは使用していない。

| 観測 | 結果 |
|---|---|
| 選択のみ／ミュート中の開始 | 無音を維持 |
| 明示解除／開始 | 選択した440Hzのみ |
| TTS併用 | 440＋880Hz |
| 入力停止 | 880Hzを維持、440Hz消失 |
| TTS停止 | 440Hzを維持、880Hz消失 |
| 全体mute／resume | 無音／選択入力を復帰 |
| source喪失／同名再作成 | 停止を維持、明示再選択後だけ復帰 |
| external設定への変更 | 入力停止 |
| アプリ終了／再起動 | 無音、source bridgeなし、選択初期値は空 |

全16観測で禁止1760Hzは検出0、100ms超のcapture gapは0、EOF/errorなし。
最大read gapは42.594ms。UI画像は870×654、alpha255、DPMS両出力On。
私有graphと試験所有processの終了を確認した。

初回実測では、UI操作呼出し→最初の適合仮想マイクreadが入力停止155.380ms、TTS停止80.778ms、
全体mute41.589ms、source喪失41.684ms、再選択開始180.035msだった。
WebDriver往復や画面操作を含み、推論、物理ADC/DAC、VRChat受信、口元から耳元までの遅延ではない。
各1観測からp50/p95/p99や一般的性能を算出しない。[全測定JSON](measurements/2026-10-28-native-direct-controls.json)。

## 自動試験と再現

- 新identity/APIのRED31→関連100PASS。旧gate/native supervisorも含む。
- Controller/receiverのRED11→関連22PASS。停止とqueued start、設定切替、TTS独立、再起動、Windows拒否。
- 本番React/hook/routesのブラウザー試験1PASS。IPCのみ置換し、同名置換・遅延応答・明示操作を確認。
- 実native旧バイナリでは入力欄が存在せずRED。再ビルド後に16観測PASS（45.32s）。
- 音声・platform回帰361PASS・9SKIP・既存警告1。skipは任意実機試験。
- Node7ファイルPASS、Vite/native build PASS。Viteの既存chunk-size警告は残る。
- 既定Python suite1173PASS・16既知FAIL・6SKIP。失敗名集合は変更前と同じ。
  endpoint tracker4、sample-player3、clipboard7、overlay capture2。全件名をraw logに保持する。

```sh
VRCT_TEST_NATIVE_DIRECT=1 UV_CACHE_DIR=/tmp/vrct-uv-cache \
uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py -- \
uv run --no-project --python .venv_linux/bin/python python -m pytest \
  tests/platform/test_native_direct_voice.py -q
```

事前にLinux sidecar・native helper・更新済みUIを含むTauri binaryが必要。
rawは`tmp/voice-resume/native-direct-{red,green}/`、`source-controls-*.log`。
ブラウザー試験は既存の`tmp/vrct-entry-validation/venv`とChromiumを使用し、新規依存は導入していない。

ブラウザーのラベル検索の不一致はimozuruで公式仕様とinstalled sourceを照合した。
[role locator](https://playwright.dev/python/docs/locators#locate-by-role)でアクセシブル名を指定するよう試験だけを修正。
1query/12hits、原文2ファイルとhash、引用4件の照合済みreport/digestは
`tmp/voice-resume/research/p2-source-controls/`。実UIの不具合とテストの照合仕様を区別した。

## 残条件

実VCのモデル準備・変換ON/bypass/推論失敗の識別、品質・遅延・実artifact許諾、convertedとの排他は未完。
P3 ASR、P4 mic翻訳発声、P5 Windows実機・両OS配布・GPU混在負荷も未完。
この変更は既存MITコード内の制御/UIのみ。新エンジンや重みを同梱していない。
上流への連絡・打診・PRは最新ユーザー指示により自動実行しない。公開条件の達成とも扱わない。
