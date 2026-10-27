# Linux本番起動と描画受入れ（2026-10-27、10-28追記）

## 10/28: 描画ゲートを通過して再開

ユーザー提供のDPMS調査と`unkempt-bird`の消灯防止ガードを取り込み、実機で照合した。
提供された同端末の消灯→点灯実験では描画が復帰し、こちらでもガード下で前回のrAF試験が1 PASS。
通常configのdebug binaryを再ビルドし、3フレームのrAF、WebDriver画像（870×654、alpha 255、色分散あり）を確認した。
画面描画の依存版・GPU環境変数は変更していない。10/27時点のDPMSは未記録なので、当時の原因は推定として扱う。
[調査とガードの実行手順](../linux_native_ui_black_screen_2026-10-28.md)。

次に本番UIを実クリックして音声設定を保存し、実アプリの終了ボタンから閉じて再起動した。
日本語voice名・原文モード・managed経路・訳文slotの復元、終了前に再開した仮想マイクが終了後と再起動後に
ミュートとなることを独立PipeWireで確認した。描画試験と合わせて **2 PASS / 15.35秒**。
ガード単体は消灯・復帰・状態不明・抑止不可・子コマンド失敗を含む **6 PASS**。

raw: `tmp/voice-resume/original-guard.log`、`native-build.log`、`native-settings-complete.log`、
同`native-settings-complete/`の画像・描画判定・設定・driverログ。
これはVRChat、実VC、ASR、Windowsの受入れではなく、P1/Native Task 3全体はまだ未完了。
後続の[本番UI→仮想マイク試験](native-voice-report.md)では、fixture・実Irodoriともに9ケースが通過した。

WebDriver終了時と通常操作中に接続切断を観測した。imozuruでW3Cのsession終了契約と、導入版tauri-driver 2.1.0の
転送実装、CPython 3.11.17、RFC 9110 §7.6.1を照合した。urllibが強制する`Connection: close`を
tauri-driverが除去せず、poolを使うnative driverへの要求へ転送することを確認。
初回の短い比較では両クライアントが成功したが、反復を増やすとurllibは最初の画像取得後のDOM参照で切断した。
このヘッダーを付けないhttp.clientでは **1,000回のDOM参照・10画像・正常終了が成功**。
試験クライアントを後者へ変更した。native側のRST発生順序までは追跡しておらず、libsoup内部の根本原因は未確定。
接続切断を成功として握りつぶす処理や、送信済みか不明な要求の再試行は追加していない。
受入れでは実UIの終了ボタンを押し、所有するアプリPIDの消滅を確認してからdriver群を回収する。
失敗時のcleanupエラーが本来の試験エラーを隠さないよう別記録する。
調査原文・比較ログは`tmp/voice-resume/research/`と`transport-{urllib,httpclient}-1000.log`。

自動操作で見つかった通知・開閉アニメーション・コンパクト表示のクリック条件は試験側へ反映した。
WebDriverが操作未配送と返した場合だけ待機し、設定保存や送信の通信エラーを無条件に再試行しない。

## 10/27時点の報告（履歴）

**実装ループを中断。** 本番バックエンドの起動・設定復元は確認できたが、実Tauriの描画が停止した。
imozuruで原典と関連事例を調べ、試験プロセス内で回避候補を比較しても解消しなかったため、ユーザー指定の停止条件を適用した。
Task 3とP1の実Tauri→VRChat受入れは未完了。P2〜P5の完了を意味しない。

## 確認できた修正

- Linux側の実依存はuv/CPython 3.11.17で分離し、Windows限定importを修正。本番Main/Controller/Modelが初期化する。
- モデル取得は設定で明示選択。既定OFFでも、取得済みモデルと外部エンジンは使える。
- モデル不足でUI全体をSplashに固定していた条件を除いた。バックエンドのreadyを待ってテキスト入力・設定を表示する。
  モデル不足は一時的な案内とし、古い「自動でダウンロードする」という説明を更新した。
- Python warningはcategory・message・場所を1行のJSON診断としてstderrへ出す。複数行メッセージを保持し、
  後続の実例外はエラーのまま通知する。全warning/全stderrを無視する修正ではない。
- `VRCT_CONFIG_DIR`の設定・診断ログを分離。process/errorとcrash/freeze traceも指定先に入り、従来の未指定時の保存先は維持する。

Pythonの標準warning書式は改行とsource行を含みうる。Tauriの行イベントを1行ずつfatal判定していたため、
`warnings.warn(message, FutureWarning)`という続きの行が誤ってエラー表示になっていた。
[Python warnings仕様](https://docs.python.org/3.11/library/warnings.html#warnings.formatwarning)と実際の出力を照合した。

## 試験結果と判定境界

| 試験 | 結果 | 意味 |
|---|---|---|
| Task 2最終選択回帰 | 266 PASS / 5 warnings | 実Main/Modelの2回起動、保存復元、voice、UI endpoint、既存transcriber |
| Task 3修正後の選択回帰 | 280 PASS / 1 SKIP / 5 warnings | 上記にwarning/log/stdout契約を追加。SKIPは明示実行が必要なGUI試験 |
| Node診断分類 | 2 PASS | 改行を含むwarningを識別し、例外・未知stderrをエラーとして保持 |
| Vite / Linux Tauri build | PASS | Tauri 2.5.1、native sidecar、実依存。配布版の完成ではない |
| 実TauriのDOMまでの接続 | 1 PASS | textareaが生成され、偽のfatal通知がない。表示の正常性は示さない |
| 実Tauriの描画を含む受入れ | **1 FAIL** | rAF callbackが5秒以内に来ない。画像取得もtimeout |
| 全体Python suite（Task 2時点） | 1173 PASS / 16 FAIL / 6 SKIP | 16件は同環境で修正前後同じWindows専用処理の失敗。全体合格ではない |

入力DOMとバックエンドが応答しても、WebDriverの画像取得は別の境界となる。
[W3C WebDriverの画面取得仕様](https://www.w3.org/TR/webdriver/#screen-capture)はフレームの画像取得を扱う。
今回は`document.visibilityState == visible`でも`requestAnimationFrame`が動かず、PIDを照合した実ウィンドウの
compositor画像は黒かった。DOMの成功だけを根拠に先へ進むと、見えない画面を合格にしてしまう。

## 調査と実試験

環境: CachyOS/KDE Wayland、WebKitGTK 2.54.2、Tauri 2.5.1、tauri-driver 2.1.0、NVIDIA 615.78.08 / RTX 4080 SUPER。
画面はロックされておらず、KWinのcompositorは有効だった。

| 試験プロセスだけで変えた条件 | 観測 |
|---|---|
| 既定 | DOM応答、rAF停止、screenshot timeout |
| `WEBKIT_DISABLE_DMABUF_RENDERER=1` | 解消せず |
| `__NV_DISABLE_EXPLICIT_SYNC=1` | 解消せず |
| `WEBKIT_DISABLE_COMPOSITING_MODE=1` | 解消せず |
| `GDK_BACKEND=x11` | hidden判定、rAF停止、screenshot timeout |
| テストconfigでDevTools無効 | 解消せず |
| KWinで対象PID・正確なtitleをAND検索し、PID再確認後に前面化 | 対象画像は黒、rAF停止 |

3つの描画環境変数は[Tauri公式のLinux Graphics Issues](https://v2.tauri.app/develop/debug/linux-graphics/)に基づく候補。
今回の症状に有効とは断定せず、OS全体・製品の既定値へは適用しなかった。
関連するWebKit main実装と対象2.54.2の一致は未検証。GPU、WebKitGTK、Tauri/Wry、automationのどこが原因かは未確定。

最初の前面化試験はkdotoolの既定OR検索で別ウィンドウを選んでしまったため、画像を受入証拠から除外した。
AND条件・PID再照合を入れた再試験だけを上の判定に使用した。画像・ログはローカルに保持し、外部へ送っていない。

## 再現と再開条件

まず[Linux環境手順](local-setup-linux.md)の依存とsidecarを用意する。
`tauri-driver`は公式の[manual setup](https://v2.tauri.app/develop/tests/webdriver/manual-setup/)に従い、試験用ディレクトリへ導入した。

```sh
cargo install tauri-driver --version 2.1.0 --locked --root tmp/voice-completion/tauri-driver
npm run vite-build
# CARGO_TARGET_DIRを設定する場合、CLIがcwdを変えるので絶対pathを使う。
npm run tauri -- build --debug --no-bundle -- --locked
VRCT_TEST_NATIVE_GUI=1 VRCT_TEST_APP="$PWD/src-tauri/target/debug/VRCT" \
  uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py -- \
  uv run --no-project --python .venv_linux/bin/python python -m pytest -q tests/platform/test_native_ui.py
```

こちらの試験binaryは`src-tauri/build/native-cargo/debug/VRCT`、最後のbuildはDevTools無効のテストconfigを使用。
既定configでも同じ停止を観測済み。試験は自分が起動したprocess groupだけを終了する。
OS音声経路、既定音声デバイス、VRChat/WiVRn設定は今回変更していない。

再開時は別の描画依存版・環境、または原因を限定できる追加traceを用意し、同じ試験でrAFと実画像が正常になることを先に確認する。
依存版変更が有効だという証拠はまだない。その後に実画面で設定保存・再起動・mute、実TTS→仮想マイク→VRChatの順で受入れを再開する。
現時点ではUI起点の発声遅延、Windows実機、HMD、VC/ASR/翻訳発声の混在負荷は未検証。

## ローカル証拠

- `tmp/voice-completion/native-render-blocker.log` — 最後の描画FAIL。
- 同`native-ui-{red,green}.log` — UI全体がSplashになる問題のRED→DOMのみGREEN。
- 同`task3-final-{selected,node,ruff}.log` — 完成部分の回帰。
- 同`snapshot-*.log` / `snapshot-focused/compositor.png` — 描画比較。最初の無guard画像は除外。
- 同`research/native-ui/` — 18 query、原典、hash、引用照合済み`report.html` / `digest.html`。

Tauri検索役のqueryとhit対応はbatch結果から関連付けたもので、厳密な検索engineの履歴ではないことを記録した。
Task 3は未完了のため、計画全体の最終レビューも未実施。修正・試験・未解決事項をローカルコミットに保存して中断する。
