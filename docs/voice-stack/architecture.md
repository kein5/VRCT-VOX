# Voice stack — P0 / P1

要件: `VRCT_cpp_Codex_Implementation_Spec.md`、作業順序:
`VRCT_cpp_CODEX_START.md`。提供ファイルは `/data/projects/VRCT.cpp/` で確認。
基準と作業開始HEADはいずれも `79419a1f2ce78d38993b0f33e273155667eb0b6a`。

## 既存構造と境界

React (`src-ui`) → Tauri 2 (`src-tauri`) → stdin/stdout JSON
(`src-python/mainloop.py`) → `Controller.chatMessage` → `_processMessage`。
翻訳、OSC、overlay、WebSocket、履歴は既存の `MessageDirectionSpec` を維持する。
WebSocketの `SENT` / `CHAT` / `RECEIVED` とトークン認証は変更しない。
既存ASRは確定フレーズ型。OpenAI互換providerの `temperature=0.0` は
speech.cpp RESTで拒否されるので、P3で別adapterを作る。

P1では確定chatだけを音声イベントにし、有界キューへ非同期投入する。
TTSのHTTP・PCM出力は専用workerが所有する。OFFではworkerもデバイスも開かない。
失敗は音声状態へ通知し、既存OSC・翻訳・履歴の成功を変更しない。
Windowsは明示選択したPyAudioWPatch出力、Linux CLIは明示したPipeWire sink。
既定デバイスへのフォールバック・物理マイクcapture・OSC Voice操作は行わない。

## 段階ゲート

| Phase | 実装・検証対象 | 実機ゲート |
|---|---|---|
| P0 | ベースライン、ADR、計測フォーマット、ライセンス | GPU/音声設備の確認 |
| P1 | chat → speech.cpp PCM → output、設定UI、Linux CLI、fake HTTP E2E | Windows UI/仮想ケーブル/VRChatで各1回、Linux CLIの受信 |
| P2 | 独立VC adapter、モード、fail-closed、hotplug | VRChat負荷中のVC候補比較・実入力出力 |
| P3 | 専用REST検証 → realtime partial/final | mic/speaker別セッション、遅延・誤再送なし |
| P4 | final翻訳発声、ducking、double-talk制御 | VC競合・多言語・受信音声ループなし |
| P5 | LinuxネイティブGUI/配布、安定化 | 両OS、30分、故障復帰、配布検査 |

P1の実機ゲート未通過のままP2～P5を完了扱いにしない。
P1の原文/訳文選択はchatに限る。マイク翻訳発声はP4。
