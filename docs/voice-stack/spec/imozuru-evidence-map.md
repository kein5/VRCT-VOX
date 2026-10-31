# imozuru式調査記録 — VRCT-VOX低遅延音声統合

対象: 2026-10-27 / 質問: 「フォークしたVRCT-VOXにTTS・リアルタイムASR・翻訳・VCを追加し、直接音声チャットでもVCを利用できる低遅延システムを作るには、どの実装境界と技術を選ぶべきか」

## 調査の論点（6つ）

- [x] 1. **知見はどこに集まっているか**: VRCT本体とVRCT-TTSのREADME/コード、speech.cpp実装/ドキュメント、VCClient/Seed-VC作者README、PipeWire/VRChat公式仕様。原典の場所を下表に記載。
- [x] 2. **既存VRCTの拡張点と壊しやすい箇所**: `message_pipeline.py#L81-L178`、`controller.py#L967-L1215`、`transcription_providers.py#L182-L250`、`transcription_transcriber.py#L1-L30`。RESTの互換性が完全でないことをソースから確認。
- [x] 3. **speech.cppは何をでき、できないか／音声・認識の遅延特性はどうか**: `docs/server.md#L69-L110`/`#L224-L310`、`docs/models/irodori-tts.md#L1-L40`/`#L180-L199`。TTFAは作者ベンチであってVRCT E2Eではない。VC非対応。
- [x] 4. **リアルタイムVCのプラットフォーム・ライセンス・遅延制約は何か**: w-okada README対応表 `#L53-L68`、Seed-VC Realtime README `#L11-L20`/`#L90-L150`、LICENSE `#L1`。実機でのエンジン採用評価は未実施につき、実装ゲートを残す。
- [x] 5. **OS/VRChatの音声経路とチャット・マイク制約は何か**: PipeWire公式 `libpipewire-module-loopback`、VRChat公式OSC `chatbox/input`,`input/Voice`。逆OSC読み出し、トグル制御を前提としない。
- [x] 6. **ライセンスや配布・安全性でどこが危険か**: フォーク `NOTICE.md#L12-L50`（制限付きOCR学習済みモデル）、VC GPL-3.0、speech.cppモデルカード・無認証localhost API。独立プロセス連携とビルド除外を設計に反映。

## 用語

- `Realtime ASR`: 音声バッファを送信し、認識途中の`delta`と確定`completed`を返す形式。
- `TTFA`: 入力テキスト受付から最初の音声出力まで。E2Eの仮想マイク到達時間とは異なる。
- `VC`: 入力音声→別の声の音声へのリアルタイム変換。TTSとは独立したモデル。
- `OSC Chatbox`: VRChatへ文字送信する一方向インターフェース。
- `virtual microphone`: OSの仮想オーディオ入力。TTS/VC音声をVRChatへ流す経路。
- `PipeWire loopback`: Linux仮想ソース/シンクを構成するための仕組み。
- `PCM stream`: 音声のチャンク化ストリーミング。サンプルレート・チャンネル/形式指定が必須。

## 調査した原典（読んだファイルと行）

| 種別 | 原典 | 関連論点と所在 |
|---|---|---|
| 〔公式〕 | [フォークVRCT pipeline](https://github.com/kein5/VRCT-VOX/blob/develop/src-python/models/message_pipeline.py#L81-L178) | 2: MIC/SPEAKER/CHAT spec |
| 〔公式〕 | [フォークVRCT controller](https://github.com/kein5/VRCT-VOX/blob/develop/src-python/controller.py#L967-L1215) | 2: `_processMessage` |
| 〔公式〕 | [フォークVRCT ASR provider](https://github.com/kein5/VRCT-VOX/blob/develop/src-python/models/transcription/transcription_providers.py#L182-L250) | 2: REST引数・戻り値 |
| 〔公式〕 | [フォークVRCT ASR pipeline](https://github.com/kein5/VRCT-VOX/blob/develop/src-python/models/transcription/transcription_transcriber.py#L1-L30) | 2: 暫定結果方式の違い |
| 〔公式〕 | [VRCT-TTS](https://github.com/misyaguziya/VRCT-TTS/blob/master/README.md) | 1, 2: WebSocket→音声出力の先行実装 |
| 〔公式〕 | [speech.cpp API](https://github.com/nyosegawa/speech.cpp/blob/main/docs/server.md#L69-L110) | 3: TTS, PCM stream, concurrency |
| 〔公式〕 | [speech.cpp realtime ASR](https://github.com/nyosegawa/speech.cpp/blob/main/docs/server.md#L224-L310) | 3: session, VAD, delta/completed |
| 〔本人〕〔測定あり〕 | [speech.cpp Irodoriベンチ](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/irodori-tts.md#L180-L199) | 3: TTFA/RTFx参考 |
| 〔公式〕 | [w-okada VCClient](https://github.com/w-okada/voice-changer/blob/master/README.md#L53-L68) | 4: OS別対応表 |
| 〔本人〕〔測定あり〕 | [Seed-VC Realtime](https://github.com/jiaheguo521/seed-vc-realtime/blob/main/README.md) | 4: 実測430〜690msの例、OS |
| 〔公式〕 | [Seed-VC LICENSE](https://github.com/jiaheguo521/seed-vc-realtime/blob/main/LICENSE) | 4, 6: GPL-3.0 |
| 〔公式〕 | [PipeWire loopback](https://docs.pipewire.org/page_module_loopback.html) | 5: virtual sink/source |
| 〔公式〕 | [VRChat OSC](https://docs.vrchat.com/docs/osc-as-input-controller) | 5: chatbox/input, input/Voice |
| 〔公式〕 | [フォークNOTICE](https://github.com/kein5/VRCT-VOX/blob/develop/NOTICE.md#L12-L50) | 6: OCR学習済みモデル配布制限 |
| 〔公式〕 | [imozuru SKILL](https://github.com/MaryCache/imozuru/blob/main/skills/imozuru/SKILL.md) | 調査方式 |

## たどった経路（imozuru）

- **0周: 分野の地図**。探し方A「フォークされたVRCTの現存するメッセージ/ASR/UI/サイドカー実装」と、探し方B「現行のリアルタイムTTS/ASR/VCのモデル・サーバ/オーディオルーティング」を分離。中心人物/実装の一次資料がGitHubリポジトリと公式docsに集中することを確認。
- **1周: フォークとspeech.cppの原文をたどる**。VRCT README→`message_pipeline.py`/`controller.py`/`transcription_providers.py`/`websocket_server.py`へ。既存VRCT-TTSのリンクからREADME→`audio_player.py`へ。speech.cpp README→`docs/server.md`、`docs/models/irodori-tts.md`へ。`speech.cpp`とVRCT既存STTのAPI引数差異を特定。
- **2周: VCとOS・配布条件を追う**。w-okada README→版別RVC/Beatrice対応を確認。Seed-VC Realtime README→測定条件→LICENSEを確認。PipeWire公式とVRChat公式OSCを照合。VRCT NOTICEからOCRモデル制限を確認。

## 終了理由／残る実験

6論点に原典の場所が付き、これ以上のWeb探索より**実機PoC/計測**が必要となったため、実装計画を作成する段階へ進む。主な未確定事項はVC engineの実測、GPU競合時p95、WindowsおよびLinuxでの仮想マイクE2E、個別VCモデル重みのライセンス。すべて実装ゲートとして計画へ残した。

※本環境ではimozuruの`fetch.py`/`report.py`による原文全文のローカル保存・HTMLダッシュボード生成は行っていない。原典はGitHub連携と公式Webで直接読み、上記のURLと行位置を記録した。imozuruの**探索・証拠確認・停止判断の手順を適用**した資料索引であり、スクリプト生成の完全な研究アーカイブとは区別する。
