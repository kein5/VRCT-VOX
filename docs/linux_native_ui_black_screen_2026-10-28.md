# Linux で Tauri が黒画面のまま止まる件 — 調査と対処（2026-10-28）

- 対象: 2026-10-27 の Linux 受入れ試験で「実 Tauri の描画が停止した」として中断された件（`frail-walrus` ブランチ `docs/voice-stack/native-ui-report.md`）
- 環境: CachyOS / KDE Plasma 6 Wayland、WebKitGTK 2.54.2、Tauri 2.5.1、NVIDIA RTX 4080 SUPER (615.78.08)
- 調査方式: imozuru の手順（論点→原典→ファイルと行で記録）。記録一式は `~/research/vrct-tauri-black-screen/`（map.md / log.md / sources / tools）

## 結論

同端末の再現実験では、DPMS Offで黒画面・描画停止が生じ、Onへ戻すとアプリの再起動なしで復帰した。
10/27の停止時にはDPMSを記録していなかったため、当時も同じ原因だったという判断は症状の一致に基づく推定である。
この結果だけでアプリの描画不具合を一般に否定するものではない。
以下の再現調査はユーザー提供のClaude Fableによる`unkempt-bird`の成果を取り込んだもの。

1. 出力が消灯すると KWin はその出力のサーフェスにフレームコールバックを送らない。Wayland 仕様: 「A server should avoid signaling the frame callbacks if the surface is not visible in any way」（wl_surface::frame）。
2. GTK / WebKitGTK はフレームコールバックを待って次を描くため、描画が止まる。JS と DOM は動くので WebDriver の `execute/sync` は応答し、`document.visibilityState` も `visible` のまま。
3. `requestAnimationFrame` は表示更新に同期するので呼ばれない。ウィンドウのリサイズ（450x220 → 870x654）も新しいバッファの commit を要するので反映されない。
4. 撮影は一度も描かれていないサーフェスを写すので全画素が透明（前回の `compositor.png` は 450x220、全 99,000 画素が (0,0,0,0)）。ビューアによっては黒に見える。
5. 点灯すれば 5 秒以内に rAF が再開し、リサイズも反映される。アプリの再起動は不要。

前回試した `WEBKIT_DISABLE_DMABUF_RENDERER` / `__NV_DISABLE_EXPLICIT_SYNC` / `WEBKIT_DISABLE_COMPOSITING_MODE` は、Tauri 公式 "Linux Graphics Issues" がクラッシュと `Error 71` 向けに挙げるもので、本件（クラッシュなし・stderr 空）には関係しない。

## 症状の照合

| 項目 | 10/27 の報告 | 今回: 画面消灯中 | 今回: 画面点灯中 |
|---|---|---|---|
| DOM（textarea） | 応答 | 応答 | 応答 |
| `document.visibilityState` | visible | visible | visible |
| requestAnimationFrame | 5 秒以内に来ない | 1 秒で 1 回 | 1 秒で 64 回 |
| ウィンドウの大きさ | 画像が 450x220 | 450x220 のまま | 870x654 にリサイズ |
| ウィンドウ撮影 | 黒（実体は全画素透明） | 全画素黒 1 色 | 正常（1461 色） |
| WebDriver screenshot | timeout | timeout | 成功 |

点灯中は、直接起動（ダミー sidecar / 実バックエンド）でも tauri-driver 経由でも正常に描画した。消灯中だけ前回と同じ署名になる。測定値は `~/research/vrct-tauri-black-screen/sources/local-*.json`。

## 再現と復帰（同一機）

```sh
kscreen-doctor --dpms off      # 無人の消灯を模擬する
# ここで実 Tauri を起動して rAF / 撮影を確認すると前回と同じ結果になる
kscreen-doctor --dpms on       # 数秒で rAF とリサイズが復帰する
```

`kscreen-doctor --dpms on` だけでは無操作時間が戻らないため、数分で再び消灯した。試験中は消灯を抑止する必要がある。

## 対処

### 1. GUI 受入れ試験は消灯抑止と点灯確認の下で実行する

`tools/display_power_guard.py`を取り込んだ。D-Bus inhibitにはPyGObject/Gioを使うため、
デスクトップのsystem Pythonでガードを起動し、子コマンドには別のuv環境を指定できる。
KDEの消灯を抑止できると未確認の`systemd-inhibit --what=idle`への自動切替は除いた。
抑止を取得できない場合はコマンドを起動せず失敗する。実行中と終了時にDPMSを確認し、
消灯・状態不明が一度でも観測された試験は終了コード2で無効とする（既定1秒間隔の観測）。

```sh
uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py --check
VRCT_TEST_NATIVE_GUI=1 uv run --no-project --python /usr/bin/python3 python tools/display_power_guard.py -- \
  uv run --no-project --python .venv_linux/bin/python python -m pytest -q tests/platform/test_native_ui.py
```

提供された自己テスト`--hold 200`では、`dbus:org.freedesktop.ScreenSaver`により両出力が200秒間Onを維持した。
frail-walrusでもこのinhibitorの取得と点灯状態を確認し、通常configで再ビルドした実Tauriの描画・保存復元試験を実行した。

`tests/platform/native_webdriver.py`は起動前・rAFと画像の判定前後に`check_displays_on()`を呼ぶ。
途中の消灯を起こしてから点灯し直して隠さず、試験の前提条件エラーとして区別する。

```python
from tools.display_power_guard import check_displays_on
check_displays_on()   # 消灯・状態不明なら失敗。点灯と抑止は外側のguardが担当。
```

### 2. Linux ビルドを壊していた import を修正

`unkempt-bird`では`src-ui/views/app/others/window_title_bar/WindowTitleBar.jsx`のimportを実ファイル名`VRCT.svg`に合わせた。
大文字小文字を区別する環境でのbuildエラーを修正するもの。`frail-walrus`には55196e14で適用済みで、今回は追加変更していない。

## 前回報告の訂正

- `native-ui-report.md`の10/27の実測は履歴として残し、今回の再現・復帰とガード付き再試験を追記した。描画依存版の変更は今回の再開に不要だった。
- 「画面はロックされておらず、KWin の compositor は有効だった」は消灯を否定しない。消灯は `/sys/class/drm/card*-*/dpms` で確認する。
- KDE は消灯をジャーナルに残さないため、10/27 22:18–22:36 の消灯そのものの記録は無い。症状の完全一致と、無人の夜間実行（直前の操作から 20 分超）からの推定である。

## 原典

- Wayland protocol, wl_surface::frame — https://wayland.freedesktop.org/docs/html/apa.html
- Tauri, Linux Graphics Issues — https://v2.tauri.app/develop/debug/linux-graphics/
- WebKitGTK 2.54.2 が認識する環境変数（`/usr/lib/libwebkit2gtk-4.1.so.0` の文字列）— `~/research/vrct-tauri-black-screen/sources/libwebkit2gtk-4.1-2.54.2-render-env-vars.txt`
- 前回の報告・画像・ログ — `frail-walrus` の `docs/voice-stack/native-ui-report.md`、`tmp/voice-completion/snapshot-focused/compositor.png`、`tmp/voice-completion/native-render-blocker.log`
- 再現スクリプト — `~/research/vrct-tauri-black-screen/tools/`（直接起動の撮影、tauri-driver 経由の rAF 計測、消灯→点灯の復帰計測）
