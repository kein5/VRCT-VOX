# Realtime字幕・翻訳の接続設計

上位仕様P3と設計Bを継続する。現在の部品はREST/WS reducer/PCM ingress/Linux captureまで。
既存legacy `_AudioDeviceSession`は発話単位のVAD/energy共有を持つので、連続PCMの供給源に置き換えない。
Controllerの既存確定メッセージ処理は翻訳中にブロックし得る。新しいprotocol loopでは呼ばない。

## 構成の比較と選択

A: 既存AudioDeviceSessionへSpeechCpp分岐を加える。UIは少なくなるが、phrase/VAD/energy/pause契約を広く変更する。
B: Realtime専用sessionを追加し、Controllerで確定翻訳の共通処理へ接続。同じsourceのlegacy transcriptとは排他。
C: 別字幕widgetへ翻訳処理も複製。分離は容易だが、既存翻訳設定・formatter・overlayが二重管理になる。

Bを採る。既存engineは維持し、新しいRealtime設定と明示開始/停止で選ぶ。代償は設定UIとライフサイクルが増えること。
新機能は再起動時OFF、入力は明示endpoint identity、モデルと言語は既存speech.cppの公開metadataで検証する。
ユーザーは閉ループ実装を指示しているため、可逆な実装判断は記録して進め、設計承認を繰り返し求めない。

## 境界

- mic/speakerごとに別session/namespace。capture→Ingress→WSは同じloop内で管理、停止時は結果公開を即無効化する。
- 同期のUI/translation処理はWS loopと分離。partialは最新revisionへ置換し、finalは有界queueで一度だけ処理。
- 起動/停止/設定変更を世代番号で守る。IPC受信時にstartの世代を付け、stopを重いstart/翻訳より先に受理する。
- 非協調な翻訳呼出しは強制終了せず、戻り値が返っても無効namespace/期限切れなら副作用を発生させない。
- legacyのSENT/RECEIVED/CHAT形式は維持。Realtimeは別の通知を追加し、source/namespace/item_id/revisionでUI行を更新する。
- partialはOSC/TTS/clipboard/本文logger/historyへ渡さない。final翻訳は同じ字幕行の更新とし、追加行を生成しない。
- Realtime speakerはOSC/TTSへ送らない。legacyの他人音声送信オプションがONでも新しいspeaker経路には適用しない。
- overlayはpartialのたびにhistory追加しない。現在のpending表示と確定historyを分け、停止・discardでpendingを消す。
- 設定にはモデル/URL/言語/明示端点を保持してよいが、稼働状態を保存して自動再録音しない。本文保存は既存の明示logger設定と仕様の同意条件を尊重する。

## 互換性と制限

同一sourceでRealtime開始時はlegacy transcriptを停止、legacy開始時はRealtimeを無効化してから開始。
legacy energy meterの録音共有は後続実装時に調整し、Realtimeと重複captureしない。
Windows captureは別adapterで後続検証し、現段階でLinux専用表示を明記する。
相手音声はゲーム専用sinkを選ぶ。managed virtual mic/TTS経路を候補から除き、共有sinkをVRChat専用とは偽らない。
この計画の実試験もprivate synthetic source/sinkで行う。新規host録音を行わない。

## 検証

mock: 起動中stop、遅い翻訳後stop、古い世代start、重複final、partial逆順、session切断、queue上限、speaker再送防止。
UI: 同じitemのpartial→final→翻訳が1行、stop/再起動で古いnamespace拒否、legacyappend契約維持、実設定保存復元OFF。
実試験: 私有PipeWireの合成fixture→承認済みspeech.cpp/ReazonSpeech/Silero→実backend/UI。字幕置換、finalだけ翻訳、停止後無配信。
物理発話終端→字幕/翻訳のp95、VRChat/HMD混在負荷、Windows実機は別gateで未検証とする。
