# ADR 001: 外部speech.cppと独立した音声worker

Status: accepted for P1, 2026-10-27.

speech.cppのHTTPストリームを標準ライブラリで扱う。VRCTへ推論ライブラリ・
torch・モデル重みは追加しない。ローカルHTTPのみ、proxy/redirectは使わない。
API根拠: [speech.cpp server](https://github.com/nyosegawa/speech.cpp/blob/main/docs/server.md)。
`audio/pcm`、mono s16le、`X-Sample-Rate`を検証し、未対応形式は停止する。
全WAVを待たず、PCMのサンプル境界を保って再生する。

日本語はIrodori、他言語は別ポートのQwen3-TTSへ。未設定・未対応言語は
無音とエラーにする。明示した翻訳先1つのみを読み上げ、訳文欠落時に原文へ戻さない。
要求の自動再送は途中からの二重発声を招くので行わない。

## ADR 002: 出力と寿命

HTTP、デバイスopen/write/closeはworker上。設定変更と停止はcancel信号を送り、
キューを破棄。出力は短いPCMブロックに分割し、OSのresamplerに実際のrateを渡す。
ヘッダだけ書き換える疑似resamplingは行わない。Windowsはデバイス名とhost APIを
照合し、再接続後のindex再利用で別デバイスへ流さない。Linuxはtargetと
`node.dont-fallback` / `node.dont-reconnect` を指定する。

## ADR 003: VCは選定保留

speech.cppには生音声VC機能はない。P2は外部プロセス/仮想デバイス契約から始める。
[VCClient](https://github.com/w-okada/voice-changer)のWindows CUDA/ONNX RVCと
[Seed-VC Realtime](https://github.com/jiaheguo521/seed-vc-realtime)を候補にする。
Linux標準VCClientのRVC対応は確約しない。Seedの作者測定は自環境の達成値ではない。
GPU/VRChat環境でp50/p95、ドロップ、品質、VRAM、OS、モデル許諾を比較してから選定する。
VC本体やモデルは同梱しない。P1終了前にVC/ASRの大改造を行わない。

## 提案中の再評価

[ADR 004: 外部推論と音声経路の境界を条件付きで選ぶ](adr-004-audio-integration-boundaries.md)
は2026-10-27の設計評価による提案。001〜003の履歴を置換せず、3案の比較、
採用を覆す条件、未実施のPoCを記録する。新しい実装や採用承認を意味しない。
