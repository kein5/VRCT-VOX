# 配布境界と原典

2026-10-27に提供されたevidence mapと以下の一次資料を参照。
音声エンジン・モデル・参照音声は取得/同梱していない。

| 対象 | 確認した根拠 | 今回の扱い |
|---|---|---|
| VRCTコード | [LICENSE](../../LICENSE), [NOTICE](../../NOTICE.md) | MIT帰属を維持 |
| upstream OCR検出重み | [モデルライセンス](../../src-python/models/ocr/onnx/LICENSE.txt) | fork成果物から除外。ソース内の開発用ファイルは保持 |
| speech.cpp | [MIT](https://github.com/nyosegawa/speech.cpp/blob/main/LICENSE) | 外部localhost HTTPのみ |
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
