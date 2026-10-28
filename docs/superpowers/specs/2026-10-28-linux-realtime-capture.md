# Linux Realtime capture boundary

上位仕様§5/P3と設計Bを継続。推論は外部speech.cpp、音声取得はOS経路。実装判断として、
raw pw-cat stdoutでは失われる取得cycle時刻を保持する小さなlibpipewire capture helperを選ぶ。
既存の音声転送helperとlegacy recorderは維持する。Windows captureは別adapterで後続検証する。

候補比較: raw pw-catは小さいが古いPCMの時刻を復元できない。PortAudio既存wrapperはWindows向きだがLinuxの明示PipeWire endpoint/monitor選択を代替しない。
libpipewire直結はnative codeが増えるが、buffer固有のcycle時刻と同じ接続のnode identityを保てる。

選択はCore.cookie、Node.serial/name/classで固定。micはAudio/Source、speakerはAudio/Sink monitor。
node.dont-fallback/dont-reconnect/dont-move、node.linger=false。削除・別リンク・切断では終了し、同名を再検索しない。
ヘルパーはcreator-thread pidfdとparent-deathを監視する。OS default/物理device設定は変更しない。

時刻はpw_buffer.timeとSPA capture latency最大値、stream buffered framesから保守的に推定する。
SPA_IO_Position clock.durationがgraph quantum。pw_time.sizeをQとして誤用しない。
clock前後copyとpw_time now/rate一致を有限回確認し、不整合/未知latency、clock/rate/Q/latency/formatのepoch変化は終了する。
この照合は公式のatomic snapshot保証ではない。値はPipeWire報告に依存し、真の物理ADC時刻を保証しない。
raw pipeのread時刻でcapture timestampを作り直さない。

mainloop process callback（RT_PROCESSなし）で上限付きcopyとO_NONBLOCK writeを行う。
header+PCMをPIPE_BUF以下に制限し、EAGAIN/short/EPIPEで継続せず終了する。
packetはlittle-endian `VCA1`,sequence u32,cycle_ns u64,first_sample_bound_ns u64,rate u32,frames u32、mono s16le payload。
1packet最大960frames、rate48000。親側はsequence/サイズ/形式/時刻を検査し、20msへ組み直してRealtimeIngressへ渡す。
停止後はpending packet/PCMを破棄。生PCM/本文をログや共有docsに残さない。

テストは私有PipeWireの合成source/sinkのみ。ホストmicを開かず、正しい選択・default decoy排除・source削除・再作成・停止・親/thread終了・backpressureを確認する。
実ASR試験も既存合成ファイルをこのprivate graphへ流す。物理E2E/VRChat/Windowsは未検証として残す。
