# Realtime音声入力の変換と滞留制限

上位仕様は`docs/voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md`の§5/P3。
既存のbatch/VAD recorderは発話区間を作ってからqueueへ渡すため、そのqueueをRealtimeへ流用すると二重VADと遅延が残る。
この工程は連続PCMの入力境界を作り、既存合成WAV→新境界→実Realtimeの成果物を残す。
物理capture/UIへの接続は次工程。新規録音は行わない。

候補は(1)既存audioop線形変換、(2)PyAV/libswresample、(3)専用python-soxr。
(1)はanti-alias品質を満たす根拠が不足、(2)は既存wheelのFFmpegライセンス監査を拡大する。
(3)の固定1.1.0を採用候補とする。LGPL本体/同梱通知とWindows/Linux wheelの条件を原典で確認後に導入。
python-soxrを選ぶのは実装判断。ユーザーの閉ループ実装指示に従い、方式選択の再承認は求めない。

`Pcm24kStream(rate, channels)`は単一worker所有。s16le mono/stereoを明示downmixし、連続したfloat32 HQ resamplerで24kHz化、clip/roundしてs16leへ戻す。
入力5–100ms、出力最大20ms単位。native出力は可変長/0を許容。stop時はflushせず未送信tailを破棄。
最初のsampleのcapture timestampと入力sample位置を記録し、各出力chunkの先頭timestampへ換算する。
単に変換時刻でtimestampを更新して古い音声を若返らせない。stream内rate/channels変更は再開を必要とする。

`RealtimeIngress`は短い同期pushとasync pumpを持つ。pushは変換せず、最大20チャンクかつ200msの有界queueへ追加する。
250ms超/未来timestamp、非単調timestamp、不正PCM、overflowはqueueを破棄して失敗状態にする。
pumpは5ms以下のpollと直列feed。変換・送信失敗、close/cancelでclientをstopし、resampler tailを破棄する。
入力callbackのtimestampはchunk先頭の単調時計ns。OS callbackで得る時刻が末尾ならdurationを引く必要がある。
読み出すまでのOS buffer遅延はこの部品だけでは証明できない。

試験は44.1/48kHzの1kHz保持・帯域外tone抑制・chunk境界の連続性・stereo headroom・無音・形式変更・停止・キューoverflow/age。
実試験では既存合成音声の24kHz化を新実装に置き換え、2つのserver_vadセッションのpartial/finalと無音を確認。
語頭/語尾の認識精度、物理E2E、Windows実機、長時間負荷は別ゲート。
