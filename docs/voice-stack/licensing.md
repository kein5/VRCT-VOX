# 配布境界と原典

2026-10-27に提供されたevidence mapと以下の一次資料を参照。
音声エンジン・モデル・参照音声は取得/同梱していない。

| 対象 | 確認した根拠 | 今回の扱い |
|---|---|---|
| VRCTコード | [LICENSE](../../LICENSE), [NOTICE](../../NOTICE.md) | MIT帰属を維持 |
| upstream OCR検出重み | [モデルライセンス](../../src-python/models/ocr/onnx/LICENSE.txt) | fork成果物から除外。ソース内の開発用ファイルは保持 |
| speech.cpp | [検証済みv0.9.0のMIT](https://github.com/nyosegawa/speech.cpp/blob/v0.9.0/LICENSE) | 現在は外部localhost HTTP。2026-10-29ユーザー承認によりP5で本体を同梱する方針。配布版・hash・依存物の条件と通知を確定してから同梱し、モデル条件は別に確認。未同梱 |
| Irodori v4.1 Small MF | [モデルカード](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small-MF) | 日本語のみ。MIT表示に加え、声の本人の明示同意・なりすまし/誤情報禁止の記載を確認。ユーザー管理のvoiceだけ利用 |
| Irodori Large | [モデル説明](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/irodori-tts.md) | Smallと条件を混同しない。今回は同梱・検証なし |
| Qwen3-TTS | [モデル説明](https://github.com/nyosegawa/speech.cpp/tree/main/docs/models) | ユーザーが選んだ重みの条件・hashを実機導入時に記録。モデル取得なし |
| Seed-VC Realtime | [GPL-3.0](https://github.com/jiaheguo521/seed-vc-realtime/blob/main/LICENSE) | 採用保留。コードコピー・リンク・バイナリ同梱なし |
| Beatrice | [v1.1 JVS版条件](https://github.com/w-okada/voice-changer/blob/master/server/voice_changer/Beatrice/README.md) | 商用利用禁止・再配布時許諾の記載。これをv2全モデルへ一般化しない。版/モデル別条件はP2ゲート |

CPU/CUDA PyInstallerの展開済みTOCから `chatbox_yolox_tiny.onnx` を除外し、
Tauri buildとZIP作成前にも古い成果物の混入を拒否する。CIでZIP/sidecarを検査。
モデル不在時、既存のOCRチャット吹き出し検出は利用不可（他の音声・翻訳機能は独立）。
`tools/check_voice_distribution.py` は配布物のパスを受け取り、禁止モデルを見つけると失敗する。

Forkの製品名/publisher/更新配布先はP5の未完了ゲート。現行公式リリース用workflowを
forkの公開に使える状態とは主張しない。この作業ではタグ・push・公開を行わない。
ライセンス台帳は同梱許可を与えるものではない。追加モデルは個別に確認する。

## Managed route追加分（2026-10-27）

制御helper `native/voice-gate/main.c` はMITの新規コード。system `libpipewire-0.3` に動的リンクし、
音声推論コード・モデル・独自音声daemonを同梱しない。
PipeWireの [COPYING](https://github.com/PipeWire/pipewire/blob/master/COPYING) と
[公開header](https://github.com/PipeWire/pipewire/blob/master/src/pipewire/pipewire.h) のMIT表示を確認。
今回はソースcheckoutとsystemライブラリでの検証で、helperのバイナリ配布は未整備。
バイナリ配布時はPipeWire/SPA header由来のコードを含め、利用版の著作権・許諾表示を同梱する。
VCモデルの採用条件はこの追加によって変わらない。

## Realtime ASR用resampler（2026-10-28）

`soxr==1.1.0`を明示依存に追加。Python wrapper固定commit
`91479780e687fa994daabcff074e5960dc0bd4e2`、同梱modified libsoxr固定commit
`a66f3eeeeb62a32403ff143b756eed92b1ec6b62`。双方LGPL-2.1-or-later。
PFFFTは付属BSD系noticeを保持する。PyAV/FFmpegをこの変換処理に追加利用しない。

Python3.11実wheelのsha256:

- Linux x64 manylinux2.27/2.28: `3da87e3ffa3e41823d873b051c7ecb2acebd8d1b6b46b752f5facf10a0d84ab9`。
- Windows x64: `ae30c48ac795378cf23ba3c7c640b8ff794af714ac388b9fd6b31a40b39e6e86`。

Linux固定wheelはuvでhash照合して導入。両wheelに`COPYING.LGPL`、`LICENSE.txt`、
`LICENSE-libsoxr.txt`、`LICENSE-PFFFT.txt`が実在することを調査で確認した。
Windowsはartifact検査のみ、実行試験ではない。numpy1.26.4との実行はLinuxで確認。

[固定LICENSE](https://github.com/dofuuz/python-soxr/blob/91479780e687fa994daabcff074e5960dc0bd4e2/LICENSE.txt)、
[固定build](https://github.com/dofuuz/python-soxr/blob/91479780e687fa994daabcff074e5960dc0bd4e2/CMakeLists.txt)、
[PyPI固定配布](https://pypi.org/project/soxr/1.1.0/)。native libsoxrは拡張へ静的組込み。
**バイナリ配布前の残件:** LGPL§4/§6に沿った対応ソース/置換・再リンク方法、nanobindの実ビルド版と通知の網羅性を確認する。
noticeが入っているだけで最終配布条件を満たすとは判断しない。現段階は開発環境への導入で、配布物は作成していない。
既存transitive PyAVのwheelについても最終bundle監査の対象として保持する。
