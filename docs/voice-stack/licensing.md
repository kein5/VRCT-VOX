# 配布境界と原典

2026-10-27に提供されたevidence mapと以下の一次資料を参照。
この冒頭表は初期調査時点の記録。後日、ユーザー承認済みの開発用モデル取得とSeed外部worker実装を行った。配布許可とは区別し、各PoC報告と下記追記を参照。

| 対象 | 確認した根拠 | 今回の扱い |
|---|---|---|
| VRCTコード | [LICENSE](../../LICENSE), [NOTICE](../../NOTICE.md) | MIT帰属を維持 |
| upstream OCR検出重み | [モデルライセンス](../../src-python/models/ocr/onnx/LICENSE.txt) | fork成果物から除外。ソース内の開発用ファイルは保持 |
| speech.cpp | [検証済みv0.9.0のMIT](https://github.com/nyosegawa/speech.cpp/blob/v0.9.0/LICENSE) | 2026-10-29承認後、固定CPU/Vulkan実行ファイルと依存通知の配布部品を作成・検証。GUI/アプリ全体への同梱は次工程、未公開。下記追記参照 |
| Irodori v4.1 Small MF | [モデルカード](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small-MF) | 日本語のみ。MIT表示に加え、声の本人の明示同意・なりすまし/誤情報禁止の記載を確認。ユーザー管理のvoiceだけ利用 |
| Irodori Large | [モデル説明](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/irodori-tts.md) | Smallと条件を混同しない。今回は同梱・検証なし |
| Qwen3-TTS | [モデル説明](https://github.com/nyosegawa/speech.cpp/tree/main/docs/models) | ユーザーが選んだ重みの条件・hashを実機導入時に記録。モデル取得なし |
| Seed-VC Realtime | [GPL-3.0](https://github.com/jiaheguo521/seed-vc-realtime/blob/main/LICENSE) | 開発用外部workerを統合。`integrations/seed_vc`の派生コードはGPL-3.0-only表示。承認済みモデルでPoC実施、最終配布条件と対応ソースの整理は未完了 |
| Beatrice | [v1.1 JVS版条件](https://github.com/w-okada/voice-changer/blob/master/server/voice_changer/Beatrice/README.md) | 商用利用禁止・再配布時許諾の記載。これをv2全モデルへ一般化しない。版/モデル別条件はP2ゲート |

CPU/CUDA PyInstallerの展開済みTOCから `chatbox_yolox_tiny.onnx` を除外し、
Tauri buildとZIP作成前にも古い成果物の混入を拒否する。CIでZIP/sidecarを検査。
モデル不在時、既存のOCRチャット吹き出し検出は利用不可（他の音声・翻訳機能は独立）。
`tools/check_voice_distribution.py` は配布物のパスを受け取り、禁止モデルを見つけると失敗する。

Forkの製品名/publisher/更新配布先はP5の未完了ゲート。現行公式リリース用workflowを
forkの公開に使える状態とは主張しない。この作業ではタグ・push・公開を行わない。
ライセンス台帳は同梱許可を与えるものではない。追加モデルは個別に確認する。

## 2026-10-29 fork配布境界の追加検証

冒頭の「P5未完了」記述のうちfork identity/公開先分離は今回実装。
[配布境界報告](fork-distribution-isolation.md)参照。CPU/CUDA specのOCR/rapidocr全体収集を廃止し、
OCR重みを展開済みdatas/binariesのsource/destination両方で除外する。
元LICENSE/NOTICE、OCRモデル通知を明示収集。ZIP/NSIS検査は失敗時に配布処理を止める。
Windows最終実物、Linux製品package、全同梱依存の最終ライセンス監査は未完了。
モデル取得承認を再配布承認へ読み替えない。speech.cpp GUI管理はP5-Bで実装済み、未公開。

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

## RVC追加分（2026-10-29、モデル未取得）

RVC-Project/Retrieval-based-Voice-Conversion-WebUI固定commit
`81eed5e8f68b6bed1789f682fe78cdd324495afc`の推論APIを外部workerから利用する。
`integrations/rvc/blocks.py`のresampling/SOLAとloaderのsynthesizer構築は同commit由来のMITコード。
[MIT原典](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8f68b6bed1789f682fe78cdd324495afc/LICENSE)
と、RVCがSOLA出典として挙げる[DDSP-SVCのMIT](https://github.com/yxlllc/DDSP-SVC/blob/master/LICENSE)の通知を
[LICENSE.upstream](../../integrations/rvc/LICENSE.upstream)に保持する。レビュー再現用の原典抜粋にも帰属を記載。

基礎モデル候補は公式READMEが指す `lj1995/VoiceConversionWebUI` のHuBERT/RMVPE。
[モデルカード](https://huggingface.co/lj1995/VoiceConversionWebUI)はMITを表示するが本文は空である。
固定版・サイズ・hashは[rvc-base-artifacts.proposal.json](rvc-base-artifacts.proposal.json)に記録。
当初は未承認・未取得の候補。その後の承認・取得は下のMia2026追記を参照。
基礎モデルの情報だけで第三者の声の利用許諾を証明しない。
話者モデル・indexは別途利用条件を確認し、同意後に取得する。無断同梱しない。

独立したuv実行環境の依存lockはMia2026検証で作成。各wheelの最終再配布条件は未監査。RVCモデル・エンジンバイナリを
配布物へ同梱したとは主張しない。Seed workerのGPL-3.0-only境界はRVC追加で変わらない。

## Mia2026ローカル検証（2026-10-29）

ユーザー提供Mia2026のZIP同梱規約（RVC girls共通利用規約v1.0、2026-09-04）と、
ユーザーの明示指示により**モデル・index・同梱データを製品へバンドルしない**。
モデル等はGit管理外のprivate検証領域だけで使用。CPU/CUDAの両specと配布guardに
Mia2026.pth/.index/.zip/.pngの除外・拒否を追加した。試験は偽データで実施。

HuBERT/RMVPEの固定4ファイルは今回明示承認され、370,392,700 bytesを取得してhash照合した。
[実機結果と利用境界](rvc-mia-validation-2026-10-29.md)。新しい録音・モデル/音声の公開は行っていない。

実際に導入した`praat-parselmouth==0.4.6`のwheel metadataはGPLv3。RVCソースのMITだけを
実行環境全体へ一般化しない。Torch/torchaudio、FAISS、Transformers、NumPy/SciPy、
librosa、libsndfile等を含む最終runtime配布条件の監査は引き続きP5で必要。

## speech.cpp配布部品（2026-10-29）

固定0.9.0の公式Linux CPU/Vulkan ZIPをサイズ・SHA256で照合し、実行ファイルと通知のみを抽出。
[固定artifact台帳](speechcpp-bundle-artifacts.json)と[実物検証結果](speechcpp-bundle-report.md)。
[通知一式](../../licenses/speech.cpp/NOTICE.md)にspeech.cpp/GGML/cpp-httplibのMIT、
miniaudioの二重ライセンス、静的GCCランタイムのGPLv3＋Runtime Library Exception 3.1を保持する。
実行ファイル全体をspeech.cppのMITだけで説明しない。OSのlibc/Vulkan loader/driverは部品外。
モデル・参照音声・Mia2026・VC runtimeは含まない。ライセンス文の欠落/改ざんを自動検査する。
この部品の確認をアプリ全体・別VCランタイムの配布監査完了とは扱わない。未公開。
