# AppImage通常起動の表示欠け修正（2026-10-29）

ユーザー報告は「起動後に画面が消えた状態。マウスオーバーすると要素が見えるようになったり見えなくなったりする」。
インストール済みファイルは初回候補とSHA-256が一致し、NVIDIA用DMA-BUF回避設定も適用済みだった。
画面は点灯しており、以前のDPMS消灯とは別の問題だった。

## 再現と切り分け

専用設定・モデルなしで通常起動し、X11のウィンドウ画像とKDEのウィンドウ撮影を比較した。
どちらでも大部分の表示が欠けた。`WEBKIT_DISABLE_COMPOSITING_MODE=1`だけでは改善せず、
同じAppDir・ライブラリでGUIの`transparent`をfalseにした比較版では正常表示となった。
透明な描画面が再現条件であることは確認したが、WebKit/NVIDIA内部のバッファ更新の根因まで
独自に証明したわけではない。

初回のWebDriver試験はDOMと内部スクリーンショット、フレーム到着を検査していた。
その4件の成功だけでは通常起動時のデスクトップ表示を保証できず、今回の不具合を見逃した。
初回結果を消さず、[結果JSON](appimage-results.json)のprevious_candidateに区別した。

## 修正と回帰試験

LinuxのAppImageでNVIDIA kernel moduleが存在し、`WEBKIT_DISABLE_DMABUF_RENDERER=1`が
適用されている場合に限り、メインウィンドウを不透明にしてから作成する。
共通設定やWindowsの設定は変更せず、明示された描画設定と他のウィンドウを保持する。
この回避策ではデスクトップが透ける透明化と透明な角丸領域を利用できない。
推論バックエンドと音声経路の実装は変更していない。

新しい回帰試験はWebDriverを使わずAppImageを通常起動し、5秒待機後、実ウィンドウを撮影する。
その後ポインターを3か所へ移動して各画像を検査し、終了時にポインターを戻す。
入力・推論開始ボタンは操作せず、専用設定と試験で所有するプロセスだけを使う。

| 確認 | 結果 |
|---|---|
| 旧AppImageで新試験 | FAIL。内側領域の非黒画素率0.0017619464（約0.18%） |
| 修正後、FUSE/展開起動の各4画像 | 非黒画素率1.0、文字・操作部を目視でも確認 |
| 実機suite | 6 PASS / 58.45秒。通常起動2件＋従来GUI/設定/私有経路4件 |
| 関連契約試験 | 78 PASS / 1.51秒 |
| release GUI / AppImage生成・最終展開検査 | PASS |
| 元候補から保持したbackend 2,406 file/link項目 | 更新後候補との内容・モード・リンク先一致 |
| 元LICENSE・試験後AppImage SHA-256 | 一致 |
| ユーザーの通常起動確認 | 「正常に表示される」 |

修正版は567,654,904 bytes、SHA-256
`83e478698809ce6170f0bb7357065bebcf06b9b69e48be568f7c49d80d7b73f4`。
インストール済みAppImageを同じパスで原子的に置換し、旧版は
`build/appimage-rendering/installed-backup/`へ退避した。ユーザー設定と起動中プロセスは変更していない。
凍結バックエンドは保持し、GUIを再ビルドした。Python音声suite959 PASS/18 SKIPは前回の結果であり、
今回のGUI修正後に全体を再実行したものではない。

CIにも通常起動の画素試験と必要なImageMagick/xdotoolを追加し、失敗画像・測定JSONを保存する。
Ubuntu hosted CI、他GPU、Windows、最終ライセンス・セキュリティ監査は未検証のまま。
公開・push・上流への連絡/PRは実施していない。

## imozuru原典と判断

- [Tauri issue #14924](https://github.com/tauri-apps/tauri/issues/14924) と
  [実機報告](https://github.com/tauri-apps/tauri/issues/14924#issuecomment-5446993086)に、
  透明ウィンドウの描画異常と不透明ウィンドウでは出ないという記録がある。
  コメント間の回避策評価は一致しておらず、このアプリでのA/B試験を判断根拠にした。
- リンク先の[PR #16226](https://github.com/tauri-apps/tauri/pull/16226)は起動警告の追加であり、
  今回の透明描画を直す変更ではない。
- [Tauri公式Linux graphics案内](https://v2.tauri.app/develop/debug/linux-graphics/)に沿って
  合成描画無効化も比較したが、この環境では改善しなかった。
- 保存原文・論点・停止判断: `tmp/voice-resume/research/appimage/rendering-map.md`。
  再現スクリプトと画像: `tmp/voice-resume/appimage-rendering/`。
  原典のリンク追跡と制御した比較で修正方針を決め、未確認の上流根因を断定せず調査を区切った。
