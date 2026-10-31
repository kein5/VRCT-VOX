# P2: Linux外部入力の接続基盤

2026-10-28。これは明示選択した外部sourceを既存managed VC入力へつなぐ部品の検証。
**実VC、UI統合、Windows対応の完成ではない。** [ADR006](adr-006-external-source-health.md)に境界を記録した。

## 実装

`SourceBridge`は既定停止。選択だけでは音声を流さず、明示startで専用制御threadを作る。
PCMは`pw-loopback`が運ぶ。Pythonはcookie/serial、所有Client、実link、mute、子の生存を検査する。
開始時muteを確認してから、そのstreamのidentityへbindするC gateで開く。
入力/出力消失、同名置換、daemon変更、観測失敗で閉じ、再開は明示操作を要する。
最終仮想マイクやTTS入力の寿命・ミュートは変更しない。

`vrct-source-bridge`は、非leader制御threadが起動前に取得したthread pidfdを継続監視する小さなsupervisor。
停止時は音声childを終了・回収し、supervisor死亡時もchildのPR_SET_PDEATHSIGで閉じる。
PIDFD_THREADが利用可能なLinux 6.9以降を必要とし、利用不可なら開始を拒否する。
Windowsではimport可能だが、このbackendのstartは明示的に未対応エラーとなる。
この部品を呼ぶ本番UIはまだ接続していない。

## 実OS結果

PipeWire 1.6.10、私有daemon＋WirePlumber policy、mono 48kHzの合成音。
入力440Hz、独立TTS880Hz、禁止既定入力1760Hz。各ケースは2秒以上の継続captureで確認した。
3試行×14観測ケース **42/42 PASS**。raw PCMは保存せず、物理マイクやホスト設定も使用・変更していない。

| 操作→条件を満たす最初のsource read | 試行1 ms | 試行2 ms | 試行3 ms |
|---|---:|---:|---:|
| start→440Hz＋880Hz | 172.361 | 169.781 | 172.167 |
| stop→440Hz消失・880Hz継続 | 38.806 | 38.515 | 38.638 |
| 入力削除→440Hz消失・880Hz継続 | 42.352 | 38.343 | 41.524 |
| 明示再選択→440Hz＋880Hz | 150.064 | 152.323 | 154.279 |
| 親プロセス終了→440Hz消失・880Hz継続 | 38.637 | 40.143 | 42.178 |
| 制御thread終了→440Hz消失・880Hz継続 | 124.340 | 126.500 | 167.002 |
| VC sink削除→440Hz消失・880Hz継続 | 82.652 | 81.484 | 84.297 |

境界は操作開始→20msフレームのread完了。確認完了までの2秒や、実VC推論時間、ADC/DAC、
VRChat、ネットワーク、口→耳遅延を表す値ではない。thread故障注入は次の監視tickを待つ時間も含む。
3試行からp95や目標性能達成は主張しない。

全試行で1760Hz検出0、100ms超のcapture欠測0、reader終了/例外0。
最大read間隔は47.831/47.802/47.832ms。同名source再作成後も閉状態を維持し、古い選択は拒否した。
親/制御thread試験ではPython cleanupを意図的に迂回し、native寿命ガードによるstream除去を確認した。
周波数検出には振幅閾値があり、任意の声質や完全な無音を判別する試験ではない。

[共有メタデータ](measurements/2026-10-28-source-bridge.json)。ローカル全記録は
`tmp/voice-resume/source-bridge-os-pidfd/report.json`（最終修正後）。再実行例:

```sh
uv run --no-project --python .venv_linux/bin/python python tools/build_voice_gate.py
uv run --no-project --python .venv_linux/bin/python python tools/source_bridge_acceptance.py --output tmp/source-bridge-new --runs 3
```

## 発見した問題と修正

最初の実OS試行はstartで失敗し、経路が閉じたままだった。偽graphテストが
Node自身に`application.process.id`を置いたため、実graphの構造との違いを検出できなかった。
imozuruでNodeの`client.id`→Clientの認証済み`pipewire.sec.pid`という原典へ追跡した。
自己申告のapplication PIDには格下げしない。正常Clientの拒否と偽装Node PIDの誤受理を
2件のREDで再現し、修正後は関連28件PASS。その後上記実OS試行を実施した。

[NodeのClient ID設定](https://github.com/PipeWire/pipewire/blob/10c6ec62736224f2b6e79133d7ecd02cf4aab545/src/modules/module-client-node/client-node.c#L1798)、
[peer credentialsのPID設定](https://github.com/PipeWire/pipewire/blob/10c6ec62736224f2b6e79133d7ecd02cf4aab545/src/modules/module-protocol-native.c#L655)、
[Client属性の信頼区分](https://docs.pipewire.org/page_man_pipewire-props_7.html)。
installed header/manの契約と実測は一致。upstream固定commit全体がinstalled版と同一とは主張しない。
同じPID namespaceのnative接続を対象とし、PulseAudio proxy、FD転送、悪意あるOS操作を隔離する境界ではない。

調査は2方向のengine調査→実装→OS契約、所有確認失敗→2方向の原典調査を経た。
15query/169hits、原文24本とhash、引用照合済みの`report.html`/`digest.html`は
`tmp/voice-resume/research/p2-vc/`。原文は再配布しない。実VC候補の確定ready APIやモデル許諾は未完。

## 自動試験と残条件

- native23、制御29、受入れharness11（既存gate6と合わせて69 PASS）。親通常終了/SIGKILL/thread終了、identity/class/marker/重複、
  link喪失/誤接続、mute不一致、世代競合、開始待ち中stop、観測不良を含む。
- 関連 `tests/voice tests/platform`: **319 PASS / 7 SKIP**。skipはopt-in実機試験。
- 既定Python suite: **1173 PASS / 16 FAIL / 6 SKIP**。既知16件と失敗名集合が完全一致。
  Windows endpoint4、sample-player3、clipboard7、overlay capture2を未対応のまま明示する。
- 新C helperはMIT表記、OS側既存プログラムを利用。新エンジン・重みは導入していない。
  配布物全体の許諾台帳は後続ゲート。

P2にはmode排他/設定/UI、実VCの変換状態・品質・遅延・ライセンス比較、Windows経路が残る。
P3 ASR、P4 mic翻訳発声、P5配布/混在負荷も未完。全機能の完成や公開条件達成とは扱わない。

## 最終レビューと判断

一回の独立レビューでCritical0、Important1、Minor1。
Importantは「生成threadがprctl前に終了すると、同じprocessの別threadへreparentされgetppidが変わらず、
子が残る」。実launcherをconstructor内でSIGSTOPし、生成thread終了後に再開する試験でREDを確認した。
単なるTID確認は再利用・終了途中の競合を残すため採用せず、上記pidfd継続監視へ修正してGREEN。
補助プロセスのSIGKILLでも音声childが終了すること、機能未対応のkernelでspawnしないことも確認した。
この変更後に表の実OS試験と319件の回帰を再実行した。再レビューは実施していない。

[PIDFD_THREADのv6.9定義](https://github.com/torvalds/linux/blob/v6.9/include/uapi/linux/pidfd.h#L9)、
[pidfd_openの契約](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)。
非leader制御threadを対象とする。leader単独終了時のpoll挙動には版差があり一般化しない。
一部kernelソース取得はHTTP429で中止し、取得済み原典・installed manと実測を根拠にした。

レビューで対象外とされた項目の判断:

- 実VCのready/bypass/品質/モデル許諾/推論時間は後続。経路healthだけで合格させない。
- mode排他・設定・GUIは次の部品。本部品だけでは利用者向けP2機能にならない。
- Windows、物理マイク、host/VRChat/HMDはこの試験の代替にしない。
- 別PID namespace・proxy・FD転送・第三者によるOS配線操作は対象外。native同一namespaceが前提。
- P1のgate以外は過去の独立レビューを維持し、後続の全体受入れで再確認する。
- 上流への連絡・PRは最新指示により自動実行しない。
- 既知16失敗はbaselineと同じと確認したが、P5の未完事項として残す。3試行から性能一般化しない。

採用の費用は、監視用processが1個増え、古いkernelではこの機能を開始できないこと。
Minor M1（英語READMEの文書位置から開いた場合のstatusリンク切れ）はレビュー方針に従い保留した。
