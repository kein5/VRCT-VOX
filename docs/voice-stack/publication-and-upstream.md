# VRCT-VOXの公開と上流VRCTとの関係
現在の名称・配布物・識別子は[名称と識別子](project-rename.md)を参照してください。

## 現在の方針

リポジトリは[kein5/VRCT-VOX](https://github.com/kein5/VRCT-VOX)。repository IDは1435087352、default branchはdevelop。
2026-10-31にGitHubのfork networkから外れたため、「forked from misyaguziya/VRCT」とは表示されない。
[misyaguziya/VRCT](https://github.com/misyaguziya/VRCT)をMITライセンスのもとで改変した派生プロジェクトであることは変わらず、
元の[LICENSE](../../LICENSE)、[NOTICE](../../NOTICE.md)、著作権表示、原作者への謝辞を維持する。

- 上流VRCTとの互換性は目標にしない。版も上流の3.xとは別に0.1.0から数える。
- 上流への連絡、取り込みの打診、PR作成（draftを含む）は予定していない。保守担当者から明示的に依頼された場合に限り行う。
- 既存の`VRCT`内部識別子、設定形式、IPC/OSC契約は、名称の変更だけを理由に一括置換しない。
- 提供された仕様原本のファイル名や過去の検証記録は、原本・履歴として残す。

## 公開の状況

2026-10-31に[`v0.1.0-beta.1`](https://github.com/kein5/VRCT-VOX/releases/tag/v0.1.0-beta.1)をプレリリースとして公開した
（developのコミット`ba94359b`）。Linuxのtar.gzとAppImage、WindowsのZIP（標準版・CUDA版）とインストーラーを含む。
ベータ版はdevelopから、正式版は`release/X.Y.Z`ブランチをmainへ統合してから作成する。
手順は[配布候補とリリース下書き](release-candidates.md)を参照。

独自配布物には制限付きのOCRモデルや、許諾のないVC/TTS/ASRの重みを含めない。配布対象ごとの依存と許諾は
[ライセンス台帳](licensing.md)と[配布境界の記録](fork-distribution-isolation.md)で確認する。

## 経緯

- 2026-10-28: 予定機能の完成後に成果を公開する方針とした。上流への取り込み打診は将来の希望として残した。
  同日の追加指示で、上流への連絡・打診・PR作成は全機能が完成しても自動では行わず、ユーザーの明示的な指示を必要とすることにした。
- 2026-10-29: 配布前の条件として、OCR全重みの除外、ZIP/NSIS検査、本家へのupload/telemetryの排除、fork固有の識別子、
  READMEと支援窓口の分離を優先した。[配布境界の記録](fork-distribution-isolation.md)、[AUR案](linux-distribution-proposal.md)、
  上流への差分候補をローカルで作成した（2026-11-01に削除）。この時点で上流への連絡・PRは行っていない。
- 2026-10-31: `v0.1.0-beta.1`を公開し、リポジトリはfork networkから外れた。上流への提案の準備は、上の方針により止めている。
