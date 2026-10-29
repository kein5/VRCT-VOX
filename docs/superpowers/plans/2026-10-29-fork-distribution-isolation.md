# VRCT-TTS 配布境界の分離

2026-10-29ユーザーの5項目を実装する。既存の閉ループ実装指示に基づく。
タグ・push・公開・上流への連絡/PRはこの工程で実施しない。

1. [x] CPU/CUDA specでOCRディレクトリ収集を廃止し、展開済みTOCも検査。
   ライセンス通知を保持。古いtree、ZIP、NSISを検査し、読めない成果物は失敗。
2. [x] 本家HF upload/telemetry注入を除去。公開workflowは手動検証専用にする。
   インストーラーと更新先もforkへ変更。組込み更新は配布確認まで無効にする。
3. [x] 製品名、identifier、publisher、実行ファイル、sidecarを独立させる。
   IPC・OSC・設定項目は維持し、本家の著作権を削除しない。
4. [x] READMEをforkの説明/ダウンロード予定先/サポート/謝辞へ書き直す。
   上流還元候補、ライセンス残件、AUR案と公開ゲートを記録する。
5. [x] uvでRED→GREEN、関連回帰、Vite/Tauri/native起動を検証する。

Windows最終ZIP/NSIS実物はこのLinux環境で作成済みではない。
検査器の試験と最終配布物の検査を混同せず、Windows実物検証を公開条件に残す。

実装とLinux試験の結果: [報告](../../voice-stack/fork-distribution-isolation.md)。
最終Windows ZIP/NSIS、Linux製品package、ライセンス/セキュリティ監査は公開前の未完了ゲート。
