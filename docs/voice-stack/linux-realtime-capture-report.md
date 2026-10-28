# Linux Realtime ASR capture検証（2026-10-28）

Linuxの明示入力を、取得時刻を保持して既存RealtimeIngressとspeech.cppへ接続した。
`native/asr-capture/main.c`→`capture_packets.py`→`capture_pipewire.py`→既存Ingress/Realtime producerの構成。
legacy recorder/providerや既存UIの入力選択は変更していない。P3全体の完成ではない。

## 確認できた動作

- 私有PipeWireの合成マイク（Audio/Source）と出力モニター（Audio/Sink）を別ASR sessionへ接続。
- 実speech.cpp0.9.0、既存ReazonSpeech、承認済みSilero v6.2で、両sessionともpartial7回/final2回。本文と取得PCMは共有結果へ保存しない。
- 発話前1.2秒のOS無音で認識更新なし。停止後はhelperが消え、clientがclosedになり、未配信結果も取得できない。
- Core.cookieとNode.serial/name/classで固定。誤identity・入力削除・同名再作成・default decoyへfallbackしない。
- 親の通常終了/強制終了/作成thread終了、pipe backpressure、consumer拒否で取得終了。pending PCMを停止後にflushしない。

実モデルを含む取得・変換・protocol試験 **97 PASS（19.93秒）**。
音声機能回帰 **480 PASS / 12 opt-in SKIP / 2 warnings（24.61秒）**。
新しいcapture実試験のSKIPはモデル環境変数なしの通常runだけで、上の97件では実行した。
既定suite **1173 PASS / 16既知FAIL / 6 SKIP / 46 warnings（13.93秒）**。
失敗名集合は[既知失敗一覧](seed-vc-runtime-report.md#unchanged-default-suite-failures)と同一。
Ruff、native3helperの-Werrorビルド、diff検査も通過。

## 時刻・バッファの境界

生PCMだけのpw-cat stdoutでは元の取得時刻を復元できないため、小さなnative helperを追加した。
mainloop callback（RT_PROCESSなし）で最大100msの入力を処理し、1packet最大20ms、PIPE_BUF以下でnonblocking write。
短いwrite/EAGAIN/EPIPEでは継続せず停止する。Pythonは20ms/48kHz monoへ再構成し、既存soxr ingressで24kHz化する。

`pw_buffer.time`のcycle時刻から、報告された最大path latencyとconverter buffered frames、
さらに1buffer分の安全幅を引いた値を先頭sampleの保守的な時刻境界として持つ。
read時刻で付け直さず、native/parser/ingressで250ms超過を拒否する。
clockの前後copyとpw_timeを照合するが、公開APIに全positionのatomic snapshot保証は確認できていない。
clock id/rate/graph quantum/latency/formatの変更や不整合では停止する。
`clock.cycle`はbufferごとに進むので、同じsnapshot内の照合にだけ使い、別buffer間の不変条件にはしない。

[実測JSON](linux-realtime-capture-results.json)の今回1実行では、報告capture境界→feed呼出しのp95は
mic **72.24ms**、speaker **67.25ms**。最大は75.92ms/71.86ms。
これはOS報告に依存する音声入力→送信直前の値で、真のADC時刻、ASR確定、翻訳、UI表示、VRChatを含むE2E遅延ではない。
負荷試験の代表値や30分継続動作の合格として扱わない。

## 途中停止の調査と判断

最初の実試験はcapture開始後に再生streamを新設し、micのOUTPUT latencyが1Q→2Qへ変わって停止した。
rate/nsは不変。これはgraphの処理quantum自体の変更とは区別する。
原典では新link時のlatency再計算とasync linkの+1Qが確認でき、観測と整合する。
どのlinkが実際に1Qを加算したかは未確定で、この観測だけでtimestamp式全体を証明するものでもない。

試験はproducerを先に作成し、同じstreamで無音→既存合成fixture→無音を継続供給するよう修正した。
安全停止条件は維持し、新規producer追加時に停止する別の回帰試験も通した。
実運用でも選択経路のlatency条件が変わった場合は停止・再選択が必要になる。透明な自動再接続は行わない。
古いbufferと新latencyのepoch対応がatomicに保証されないため、値だけ入れ替えて継続する方式は採らない。

主な原典:

- [PipeWire1.6.10 stream.h](https://github.com/PipeWire/pipewire/blob/1.6.10/src/pipewire/stream.h): buffer.time、RT callback制約。
- [固定latency.h](https://github.com/PipeWire/pipewire/blob/1.6.10/spa/include/spa/param/latency.h): capture latencyの意味。
- [固定impl-node.c](https://github.com/PipeWire/pipewire/blob/1.6.10/src/pipewire/impl-node.c#L2212): cycle更新。
- [Latency support](https://docs.pipewire.org/page_latency.html)、[固定impl-port.c](https://github.com/PipeWire/pipewire/blob/1.6.10/src/pipewire/impl-port.c#L1869): async linkのlatency伝播。
- [固定stream.c](https://github.com/PipeWire/pipewire/blob/1.6.10/src/pipewire/stream.c#L2466): time snapshotと現在latencyの合成。
- [pipe(7)](https://man7.org/linux/man-pages/man7/pipe.7.html): PIPE_BUFとnonblocking write。

imozuru記録: `tmp/voice-resume/research/asr-capture-timestamps/`。
生の診断・試験結果: `tmp/voice-resume/capture-task2-acceptance/`ほか。共有JSONには本文・音声・個人パスを含めない。

## 残条件と実装上の選択

- 物理mic録音・Windows実機・VRChat・UI字幕・既存翻訳へのfinal接続は未検証/未接続。
- Linuxの検証環境はPipeWire1.6.10。owner-thread監視はLinux6.9以降のPIDFD_THREADが必要。未対応時にdefault入力へ退避しない。
- callbackは短時間で戻る契約。callbackが詰まってもstopはnative helperを終了するが、Python callbackが残る場合は`consumer_busy`を返し、停止完了と偽らない。
- stop完了後の再利用は不可。新しいsession/namespace/ownerを作り直す。UI側の停止操作では結果公開namespaceも即時無効化する必要がある。
- native helperはMIT。新しい推論モデル/音声の取得・録音は行っていない。soxrを含む最終配布の対応source・通知・置換条件は[ライセンス台帳](licensing.md)のゲートを維持する。
