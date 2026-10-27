# ADR-006: 外部入力の接続確認とVC変換状態を分ける

Status: P2モデル不要の基盤実装として採用。実VCエンジン採用・P2全体受入れは未完了。
Date: 2026-10-28
Related: [ADR004](adr-004-audio-integration-boundaries.md)、[ADR005](adr-005-managed-microphone-lifetime.md)

ユーザーはBの検証、モデル不要の先行検証、全機能までの継続作業を指示した。
以下はその範囲で行う実装担当の選択であり、新しいエンジン・モデルの利用同意ではない。

## 根拠と境界

公開VCClient masterの旧MMVCServerSIO実装では、モデル未選択でもinfoのstatusはOKとなり、
passThroughでは入力をそのまま返す。現行2.xのAPI契約として旧コードを流用しない。
[固定コミットのManager](https://github.com/w-okada/voice-changer/blob/d8ef15799470193f7c8176ef471245753a656626/server/voice_changer/VoiceChangerManager.py#L217)

Seed-VC Realtimeでは入力モニターモードが素通し、推論例外は無音、選択機器が見つからない場合は既定機器を使う。
そのためプロセス生存、音量、開始フラグだけで変換成功を推定しない。
[固定コミットのengine](https://github.com/jiaheguo521/seed-vc-realtime/blob/58d0ca372cc76f60a798d9f84611f053f9029f3a/realtime_vc_engine.py#L505)

両候補に初回の自動重み取得経路がある。現段階では起動・導入・重み取得をしない。
公開コードのVCClient MITとSeed-VC GPL-3.0は、全モデル・バイナリ・依存物の配布許諾を意味しない。
調査原文11本とmanifest、2検索役の9query/87hitsは`tmp/voice-resume/research/p2-vc/`。
実VCのready/bypass/変換成功の確定APIは今回の候補で得られていない。架空のAPIを製品へ追加しない。

## 決定

最初にLinuxの**明示選択したsourceからmanaged VC sinkへの接続**だけを製品部品として作る。
外部エンジンは別の仮想sourceへ出力する想定とし、そのsourceを選ぶ接続経路と物理マイクのpassthroughを
後続のmode制御で切り替える。二つを同時に開かず、engine出力を最終mixへ直結した構成は受入対象にしない。
この部品のhealthは接続・mute・所有processの観測であり、`conversion_verified=false`を維持する。
変換品質やモデル準備状態を確認できるengine固有adapterは別ゲート。

- 開始時にPipeWire cookie＋source/sinkのobject.serialを固定する。名前だけの再接続やOS既定へのfallbackをしない。
- `pw-loopback`のPCM経路を使い、PythonへPCMを持ち込まない。開始時はplayback nodeをmuteにする。
- 同じgraph上の両endpoint・実link・所有streamを検査後、cookie/serialへbindする既存native gateを拡張してそのstreamだけunmuteする。
- source消失、同名置換、daemon epoch変更、process終了、検査失敗は閉じ、明示startなしで復帰しない。TTSと最終仮想sourceの寿命を変更しない。
- 小さなLinux launcherで親終了シグナルを設定し、接続processを親より長く残さない。作成threadの終了にも反応するため、専用の制御threadがprocessを所有する。
- 非Linuxでこのbackendを呼ぶと明示的に未対応を返す。import段階でWindows機能を壊さない。Windows capture/forwardingとUIは後続の独立タスク。

WirePlumber公式は`target.object`とdont-fallback/dont-reconnect/dont-moveの挙動を定義する。
インストール済み`find-defined-target.lua`は数値target.objectをobject.serialへ解決する。
独立graphの合成音試行で、mute開始→無音継続→明示unmute→合成音の到達を確認した。
[linking仕様](https://pipewire.pages.freedesktop.org/wireplumber/policies/linking.html)、
[親終了シグナルの制約](https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html)

## 他案と再検討条件

| 案 | 判断 | 再検討条件 |
|---|---|---|
| processやデバイス存在を変換readyと見なす | 採用しない。素通し・モデル未準備と区別できない | 正式な変換状態契約と実機の故障試験が得られた場合 |
| エンジン出力をmanaged mixへ直結 | 独立停止・passthrough排他を所有できない | エンジン側gateで同じ停止/故障条件を実証できる場合 |
| Pythonでcapture/mix/再生を一括実装 | 最初のLinux接続には不要。新しいqueueやコピーを増やす | Windows共通処理、ducking、単一captureでOS経路の限界が実測された場合 |
| 専用音声daemonへ全面移行 | Bの小さな接続部品を先に検証 | 停止・寿命・混合要件をBで満たせない場合（ADR004のC案） |

## 受入れと制限

独立PipeWireの合成sourceと禁止fallback用の別周波数を使い、通常、停止、source削除・同名再作成、
sink消失、親終了、連続切替を検査する。captureの連続性を確認し、死亡readerを無音と数えない。
この結果は音声変換・実マイク・VRChat・Windowsの完成証拠ではない。
OSを直接操作する別アプリや誤設定された外部VCの原音出力を、接続部品だけで判別できるとは主張しない。
必要なモデル状態がunknownなら後続VC機能の受入れは未確認のまま。実機ゲートをfakeで置き換えない。
