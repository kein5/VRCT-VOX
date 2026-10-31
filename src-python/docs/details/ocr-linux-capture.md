# Linux でのチャット読み取り: キャプチャ経路と検出器なしの読み取り

VRCT-VOX の Linux 版 (AppImage、KDE Plasma Wayland、PipeWire、VRChat は Proton) で
チャット読み取り (OCR) を動かすための構成と、未実装の Wayland portal 経路の計画。

## 全体像

```
VRChat ウィンドウ ──(X11/XWayland: ocr_capture_x11.py)──▶ BGR フレーム
   └─ 設定の読み取り範囲で切り出し (ocr_detection.RegionCandidates)
        └─ RapidOCR + PP-OCR (検出 DB + 認識) ─ 行のボックスとテキスト
             └─ 行を吹き出しへまとめる (groupLines)
                  └─ チャットボックスの見た目で絞る (looksLikeChatbox)
                       └─ 行の連結 → 重複抑制 → 翻訳パイプライン
```

上流の吹き出し検出モデル (`onnx/chatbox_yolox_tiny.onnx`) は使わない。フォークの
ビルドへの同梱・ユーザー向けのダウンロード・出力を使った学習のいずれも許されていない
(`onnx/NOTICE.txt`)。将来 VRCT-VOX 独自の検出器ができたら `OcrPipeline(detector=...)`
へ渡す (`isAvailable()` / `loadModel()` / `detect(frame) -> [(bbox, crop)]`)。

## 検出器なしの読み取り (ocr_detection.py)

| 段階 | 内容 | 根拠 |
|---|---|---|
| 範囲 | `OCR_CAPTURE_REGION` (ウィンドウ比 0..1、既定は全体)。長辺 2560px を超えたら縮小 | 4K 全体を CPU で読むと 1 tick 1 秒超 |
| 行検出 | PP-OCR 自身の DB 検出 (RapidOCR が範囲ごと実行) | 追加モデル不要 |
| 吹き出しへのまとめ | 横に 30% 以上重なり、縦の隙間が行高の 0.6 倍未満の行を同じ吹き出しとする | VRChat は行を中央揃え・詰めて描き、吹き出しごとに余白がある |
| 見た目の確認 | 行ボックス内の画素を Otsu で二分し、明るい側 (文字) が 165 以上で無彩色、暗い側 (板) が 110 以下、差 90 以上、文字の画素が 6 割未満 | チャットボックスは半透明の黒い板に白文字。看板・ポスター・色付き文字を落とす |

見た目の確認は `OCR_CHATBOX_FILTER` で切れる。色・輪郭で吹き出しそのものを探す方法は上流で
実機により反証済み (ワールドの UI パネルや岩・木目を吹き出しと誤認) なので、形の判定は
PP-OCR が文字と認めたものを絞るだけに使い、領域の提案には使わない。

合成画像 (PIL で描いた吹き出しと看板、`src-python/test/ocr_synthetic.py`) での実測、
CPU、`ocr_onnx_threads()` 準拠:

| フレーム | 1 tick | 結果 |
|---|---|---|
| 1280x720、日英中の吹き出し 3 つ + 看板 | 118 ms | 3 つとも正しく読み、看板は除外 |
| 1920x1080、日英の吹き出し 3 つ + 看板 | 274 ms | 同上 |
| 1920x1080、韓国語 (PP-OCRv5 korean) | 253 ms | 正しく読む |

実際の VRChat の画面では未検証 (下記「未検証」)。

## モデル (同意を得たダウンロードのみ)

RapidOCR はパスを渡されないモデルを自分でダウンロードする (固定されていない URL から、
パッケージのフォルダへ、同意なしに)。そのため `ocr_models.resolveModelFiles` が
カタログ (`models/model_downloads/catalog.py` の OCR ブロック) のダウンロード先から
det / rec / 文字リストのパスを決め、サイズと sha256 を確かめてから渡す。向き分類器は
使わない (`use_cls=False`) が RapidOCR 3.9.2 はセッションだけ作るので検出モデルを指す。
RapidOCR の `DownloadFile.run` は例外を投げるものに差し替えてある。

| カタログ id | 中身 | 出典 (Hugging Face、固定リビジョン) | ライセンス |
|---|---|---|---|
| `ppocrv6-small` | PP-OCRv6 small det + rec (日英中・ラテン) | `PaddlePaddle/PP-OCRv6_small_det_onnx`, `PaddlePaddle/PP-OCRv6_small_rec_onnx` | Apache-2.0 |
| `ppocrv5-korean` 他 4 つ | PP-OCRv5 mobile rec (韓・キリル・タイ・アラビア・デーヴァナーガリー) | `PaddlePaddle/<script>_PP-OCRv5_mobile_rec_onnx` | Apache-2.0 |

保存先は `config.json` の隣の `downloaded_models/<id>/<revision>/`。PaddleOCR は認識モデルの
文字リストを `inference.yml` に持つので、`downloaded_models/.ocr-keys/` に 1 行 1 文字の
ファイルへ変換して RapidOCR に渡す。ビルドには含めない (`tools/distribution_policy.py`)。

## X11 / XWayland キャプチャ (実装済み、ocr_capture_x11.py)

- Proton の VRChat は X11 クライアントなので、Plasma Wayland では XWayland のウィンドウになる。
  rootless XWayland はトップレベルを全てオフスクリーンへリダイレクトしているので、ウィンドウに
  対する `XGetImage` は上に重なったウィンドウ (VRCT-VOX 自身など) に影響されない
- ウィンドウ探し: `_NET_CLIENT_LIST` (無ければツリーを 3 段まで) → タイトル完全一致 →
  部分一致 → `WM_CLASS` / `_NET_WM_PID` のプロセス名 (`vrchat.exe`)
- 依存: システムの `libX11` を ctypes で使う。X11/XWayland のセッションには必ずあり、UI
  (GTK/WebKit) も読み込んでいるので AppImage に追加するものは無い
- Xlib の既定エラーハンドラは `exit()` するので、呼び出しのたびに記録用ハンドラを入れて
  `XSync` で回収する。libX11 1.7 以降なら `XSetIOErrorExitHandler` で X サーバー喪失時も
  終了しない
- 構造体の配置は、確認用に自分で作った画面外の override-redirect ウィンドウだけを読んで
  実機の XWayland で確かめた (他のウィンドウは列挙も読み取りもしていない)

起動時に `probeCapture()` が「X に繋がるか」「ウィンドウがあるか」を確かめ、だめなら
`OCR_DISABLED_CAPTURE_UNAVAILABLE` / `OCR_DISABLED_WINDOW_NOT_FOUND` でトグルを戻す。

## Wayland portal (ScreenCast) 経路: 未実装、計画

対象: ネイティブ Wayland のウィンドウ (`PROTON_ENABLE_WAYLAND=1` の Proton、将来の Wayland
クライアント)、および XWayland でも中身が取れない場合 (下記「未検証」)。

### 実装しなかった理由

- PipeWire の映像ストリームを受け取る部品が今の依存に無い。Python から直接やるには
  libpipewire を ctypes で叩いて SPA の pod を組む必要があり、GStreamer の `pipewiresrc` は
  AppImage に入っていない
- 初回はユーザーが KDE のダイアログでウィンドウを選ぶ必要があり、無人の検証ができない

### 手順 (xdg-desktop-portal 1.x)

1. `org.freedesktop.portal.Desktop` / `/org/freedesktop/portal/desktop` の
   `org.freedesktop.portal.ScreenCast` を使う。各メソッドは Request オブジェクトを返し、
   結果は `org.freedesktop.portal.Request.Response` シグナルで届く (response 0 = 成功、
   1 = ユーザーが取り消し、2 = その他)。`handle_token` を自分で決めて、呼ぶ前に
   `/org/freedesktop/portal/desktop/request/<sender>/<token>` のシグナルを購読する
2. `CreateSession({handle_token, session_handle_token})` → `session_handle`
3. `SelectSources(session, {types: u 2 (WINDOW), multiple: false, cursor_mode: u 1 (非表示),
   persist_mode: u 2 (取り消されるまで), restore_token: s (保存済みなら)})`
4. `Start(session, parent_window "", {handle_token})` → `streams: a(ua{sv})` (PipeWire ノード id、
   size、source_type) と新しい `restore_token`。トークンは 1 回使うと無効になるので、毎回
   返ってきたものを保存し直す (`OCR_PORTAL_RESTORE_TOKEN`、設定画面には出さない、
   response が 0 以外なら消す)
5. `OpenPipeWireRemote(session, {})` → PipeWire への fd (`h`)
6. その fd とノード id で映像を受け取る。`native/asr-capture` (C、libpipewire、
   `tools/build_linux.py` でビルド) と同じ形で `native/screen-capture/main.c` を作る:
   - `pw_context_connect_fd(fd)` → `pw_stream_connect(PW_DIRECTION_INPUT, node_id,
     AUTOCONNECT | MAP_BUFFERS)`
   - EnumFormat は `SPA_VIDEO_FORMAT_BGRx` / `BGRA` / `RGBx`、modifier なし。
     `SPA_PARAM_Buffers` の dataType を `MemFd | MemPtr` に限って DMA-BUF を避ける
     (KWin は modifier を出さなければ MemFd を返す)
   - 最新フレームだけを保持し、Python から 1 バイト要求が来たら幅・高さ・stride と画素を
     パイプへ書く (読み取り間隔は 750 ms なので転送量は問題にならない)
   - fd はプロセス起動時に `pass_fds` で渡す
7. Python 側は `ocr_capture_portal.PortalWindowCapture` を作り、`OcrCapture` で X11 と同じ
   位置に置く。選び方: `WAYLAND_DISPLAY` があり、X11 でウィンドウが見つからないとき
   (または設定で明示したとき)
8. D-Bus は `jeepney` (純 Python、MIT、依存なし) を `pyproject.toml` に足すか、C 側で
   libdbus/sd-bus を使う。前者の方が Python 側でトークン保存とエラー処理を持てる

### テスト

- portal: 偽の `org.freedesktop.portal.ScreenCast` をセッションバス (`dbus-run-session`) 上に
  立て、Response の各値・トークンの更新・取り消しを確かめる
- PipeWire: CI の PipeWire (`tools/ci/setup_pipewire.sh`) に既知の色の映像ノードを流し
  (例: `gst-launch-1.0 videotestsrc pattern=solid-color ! pipewiresink`)、その色のフレームが
  届くことを確かめる
- 実機: Plasma 6 で初回にウィンドウ選択ダイアログ、2 回目以降は出ないこと

## 未検証

- 実際の VRChat (Proton) のウィンドウからの取得。DXVK/VKD3D の Vulkan スワップチェーンが
  XWayland で直接 Wayland にフリップされると、ウィンドウのピクスマップが空 (黒) のことがある。
  その場合フレームは `isFrameBlank` で捨てられ、何も読まれない。起きたら上の portal 経路が要る
- 実際のチャットボックスの色・不透明度・フォントでの見た目判定と行のまとめ方。しきい値は
  合成画像で決めたもので、実機のスクリーンショットで見直す必要がある
- Windows のリリースビルドでの起動 (spec の修正とテストのみ。実ビルドはしていない)
