# Linux でのチャット読み取り: キャプチャ経路と検出器なしの読み取り

VRCT-VOX の Linux 版 (AppImage、KDE Plasma Wayland、PipeWire、VRChat は Proton) で
チャット読み取り (OCR) を動かすための構成。X11/XWayland のウィンドウを名前で読む経路と、
利用者が共有した Wayland のウィンドウを読む経路がある。

## 全体像

```
VRChat ウィンドウ ──(X11/XWayland: ocr_capture_x11.py)──────────────▶ BGR フレーム
                 └─(共有された Wayland のウィンドウ: ocr_capture_portal.py)─┘
   └─ 設定の読み取り範囲で切り出し (ocr_detection.RegionCandidates)
        └─ RapidOCR + PP-OCR (検出 DB + 認識) ─ 行のボックスとテキスト
             └─ 行を吹き出しへまとめる (groupLines)
                  └─ チャットボックスの見た目で絞る (looksLikeChatbox)
                       └─ 行の連結 → 重複抑制 → 翻訳パイプライン
```

上流の吹き出し検出モデル (`onnx/chatbox_yolox_tiny.onnx`) は使わない。フォークの
ビルドへの同梱・ユーザー向けのダウンロード・出力を使った学習のいずれも許されていない
(`onnx/NOTICE.txt`)。

## VRCT-VOX の検出器 (ocr_chatbox_detector.py)

VRCT-VOX 自身のフレームで学習した YOLOX-Tiny (`tools/chatbox_lab`、MIT) を、カタログの
`vrct-vox-chatbox-detector` から同意を得てダウンロードする。上流と同じ入出力なので
`BubbleDetector` がそのまま動かす。

- 使う条件: ダウンロード済みで、サイズと sha256 がカタログと一致し、Config の
  「チャットボックス検出器を使う」(`OCR_USE_CHATBOX_DETECTOR`、既定オン) がオン。
  どれかが欠ければ下の検出器なしの読み取りになる。切り替えは実行中にも効く。
- 上流モデルを読まないための制約: `BubbleDetector` を作るのは ocr_chatbox_detector.py だけ。
  `ocr_models.resolveArtifact` が検証したパス以外、`vrct_vox_chatbox_yolox_tiny.onnx` 以外の
  名前、同梱の `onnx/` ディレクトリ内のファイルは拒否する。`findModelPath()` は呼ばない
  (`model_path=None` だと上流のファイルへ落ちるため)。ビルドには入らない
  (`tools/distribution_policy.py` が `chatbox_yolox` を含む名前を拒否する)。
- 検出はフレーム全体で行い (学習時と同じ縮尺)、中心が読み取り範囲に入る検出だけを残す。
  検出ごとに切り出して OCR し、1つの吹き出しを1件として送る。チャットボックスの見た目判定は
  切り出しごとに掛ける。chatbox_lab の val (41個) では、検出器は conf 0.7 で 39 個を見つけ、
  余分な検出は 1 件 (ラベルの箱が文字にぴったりで IoU が足りなかった本物の吹き出し)、CPU で 39 ms。
  見た目判定で落ちたのは消えかけて灰色になった吹き出し 1 件だけで、明るいうちに読み終えている。
- 実モデルの確認 (任意): `VRCT_CHATBOX_DETECTOR=<onnx>` を設定して
  `src-python/test/test_ocr_chatbox_detector.py` を実行する。`VRCT_OCR_MODEL_ROOT` も設定すると
  PP-OCR で読んだ文字が送信した文と一致するかも確かめる。

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

## Wayland のウィンドウを共有する経路 (実装済み)

対象: ネイティブ Wayland のウィンドウ (gamescope の中の VRChat、Wine の Wayland ドライバー、
`PROTON_ENABLE_WAYLAND=1`)。X11 からは見えないので、デスクトップの ScreenCast portal で
利用者がウィンドウを選び、PipeWire で届く映像を読む。

```
設定ページの「ウィンドウを共有…」(利用者が押したときだけ)
  └─ Tauri: screencast_start (src-tauri/src/portal_screencast.rs)
       ├─ org.freedesktop.portal.ScreenCast: CreateSession → SelectSources → Start → OpenPipeWireRemote
       └─ vrct-screen-capture (native/screen-capture) を起動。PipeWire の接続は標準入力で渡す
            └─ 最新のフレームを <VRCT_VR_PANEL_DIR>/screen-frame へ書く (最大で毎秒4枚)
                 └─ バックエンド: ocr_capture_portal.SharedWindowCapture が読む
                      └─ OcrCapture が「window」の取り込み元として使う (範囲、検出、認識は X11 と同じ)
```

### 誰が何を持つか

| 部品 | 役割 | 持たないもの |
|---|---|---|
| UI (`OcrSharedWindow.jsx`、`useOcrSharedWindow.js`、`OcrSharedWindowController.jsx`) | ボタン、状態の表示、復元トークンの保存、チャット読み取りをオフにしたときの共有の終了、共有が終わったときのお知らせ | 自動で頼む処理 (起動時、ページを開いたとき、開始時、失敗時のどれでも頼まない) |
| Tauri (`portal_screencast.rs`) | ポータルとのやりとり、ヘルパーの起動と停止、セッションが閉じたことの検出 | 画素 |
| ヘルパー (`native/screen-capture/main.c`) | PipeWire の映像を受け取り、フレームファイルへ書く | ポータル、D-Bus |
| バックエンド (`ocr_capture_portal.py`、`ocr_capture.py`) | フレームファイルを読む。共有が終わったことを状態に出す | 共有を始める・終える処理 |

ポータルを Tauri 側に置いたのは、zbus と、GlobalShortcuts portal で使っている手順 (アプリ ID の登録、
Request の Response 待ち、期限、取り消し、ポータルの再起動の検出) がすでにあるため。Python の依存は
増えない。ヘルパーは既存のネイティブ補助と同じく libpipewire だけを使う。

### ポータルへの頼み方

- `SelectSources`: `types: 2` (ウィンドウだけ。画面全体を選ぶと VRCT-VOX 自身のログも読んでしまう)、
  `multiple: false`、`cursor_mode: 1` (ポインターを映さない。`AvailableCursorModes` にあるときだけ)、
  `persist_mode: 2` と `restore_token` (ポータルの版が 4 以上のときだけ)
- 復元トークンは `OCR_PORTAL_RESTORE_TOKEN` (即時保存、設定画面には出さない)。成功したら返ってきた値で
  置き換える (返らなければ空にする)。トークンを送ったのに選択画面が出て取り消された、または要求が
  拒否されたときは空にする。ポータルへ届く前の失敗 (接続できない、時間切れ、ヘルパーがない) では残す
- 共有中の「別のウィンドウを選ぶ…」はトークンを送らない。送ると同じウィンドウが黙って復元され、
  選び直せないため
- アプリ ID の登録に失敗するポータル (古い版) でも共有はできるので、登録の失敗では止めない

### ヘルパー

- 起動: `vrct-screen-capture <親のPID> <ノードID> <フレームファイル> <間隔ms>`。標準入力が PipeWire の
  接続 (ソケット)、標準出力は Tauri が持っているだけのパイプ、標準エラーは `streaming` と
  `screen_capture_<理由>` の行
- 親との関係: `PR_SET_PDEATHSIG(SIGKILL)` と親 PID の確認に加え、標準出力のパイプを監視する。Tauri が
  パイプを閉じる (通常の停止) か、Tauri が終了する (読み手がいなくなる) と止まる。通常の停止では
  フレームファイルに「終わり」を書いてから消す
- 形式: BGRx / BGRA / RGBx / RGBA。modifier を出さず、バッファーは MemFd / MemPtr だけ (DMA-BUF は
  GPU から読み戻す必要があるので使わない)。`maxFramerate` で毎秒 4 枚までを頼み、それでも明らかに早く
  届いた分 (間隔の 3/4 未満) は捨てる。`SPA_META_VideoCrop` があれば、その範囲だけを画像とする
- 終了: ノードが消えた・ストリームが切れたときは `screen_capture_stream_ended`。読めないバッファーや
  未対応の形式は理由を出して止まる

### フレームファイル

`$XDG_RUNTIME_DIR/vrct-vox/vr-panel-<pid>/screen-frame` (VR 画面の `frame` と同じ、このプロセス専用の
場所)。先頭 64 バイト (リトルエンディアン):

| 位置 | 内容 |
|---|---|
| 0 | `VRCTSCR1` |
| 8 | 通し番号 (u64)。書き換え中は奇数 |
| 16 | 識別番号 (u64)。共有が終わると 0。上位 32 ビットはヘルパーの PID |
| 24, 28, 32, 36 | 幅、高さ、1 行のバイト数、画素の並び (0 BGRx、1 BGRA、2 RGBx、3 RGBA) |
| 40 | フレームの時刻 (CLOCK_MONOTONIC、ナノ秒) |

変化のないウィンドウは新しいフレームを送らない。そのため、フレームが古いことでは共有の終わりを
判断しない。ファイルがない、識別番号が 0、ヘルパーのプロセスがない、のどれかで終わりとみなす
(強制終了されたヘルパーは「終わり」を書けないので、PID を見る)。

### バックエンドでの扱い

- `OcrCapture` は Linux で `SharedWindowCapture` を持ち、tick ごとに共有中かを確かめる (64 バイトを読むだけ)。
  共有中なら X11 の代わりに読み、`backend` は `portal`、`source` は `window` のまま
- 共有されたウィンドウを読んでいた後で共有が終わったら、X11 で名前のウィンドウを探す。見つかれば
  それを読む。見つからなければ `SharedWindowEnded` を取り込みの失敗として記録し、実行状態は
  `retrying` / `capture` / `OCR_DISABLED_CAPTURE_UNAVAILABLE`、`shared_window` は `ended` になる。
  スイッチはオンのままで、もう一度共有されると次の再試行 (1 秒から、上限 30 秒) で読み取りに戻る
- `probeCapture()` は、共有中のウィンドウがあれば X11 を調べずに準備できているとみなす
- 一度も共有されたウィンドウを読んでいなければ、これまでと同じ動きをする (X11 が既定)

### テスト

- Rust (`portal_screencast.rs`): `SelectSources` の組み立て、`Start` の応答の読み取り、トークンの検査、
  ヘルパーの場所と出力行、終わった理由
- Python (`test_ocr_capture_portal.py`): フレームファイルの読み取り、ファサードの選択と復帰、状態、設定キー
- ヘルパー (`tests/voice/test_screen_capture_native.py`): PipeWire なしでバッファーを渡し、書いたファイルを
  バックエンドの読み取りで確かめる。引数と記述子の検査
- UI: `ocrSharedWindow.test.js` (状態とトークン)、`OcrSharedWindow.test.js`、`OcrSharedWindowController.test.js`
- 実機の確認は自動試験に入っていない。KDE のダイアログへの応答が要るため

### 実機での確認 (2026-11-11)

環境: CachyOS、KDE Plasma 6.8 (Wayland)、xdg-desktop-portal-kde、PipeWire 1.6.11、Ryzen 9 9900X (24 論理コア)、
RTX 4080 SUPER、ディスプレイ 1 枚。共有したのは、確認用に自分で作った GTK 3 のネイティブ Wayland
ウィンドウ (640×480、色のわかっている 4 分割)。ダイアログには AT-SPI で応答した。

| 項目 | 結果 |
|---|---|
| 届いたフレーム | 640×508 (KWin のタイトルバー 28 行を含む)、BGRx、1,300,544 バイト。4 分割の色が一致 |
| 30fps で描き直すウィンドウ | 20 秒で 80 枚 (毎秒 4.0 枚)。ヘルパーの CPU は 0.05%、常駐メモリーは 9.6 MB |
| 動かないウィンドウ | 10 秒で 0 枚、ヘルパーの CPU は 0.0% |
| 2 回目の共有 | 選択画面なしで復元 (トークンは同じ値のまま) |
| 共有したウィンドウを閉じる | ヘルパーが `stream_ended` で終了。メイン画面にお知らせ。動作中のバックエンドは取り込みの失敗になり、もう一度共有すると読み取りに戻った |

この値は上の 1 台、この大きさのウィンドウでのもの。大きいウィンドウでは 1 枚のコピーが増える
(4K で約 33 MB)。VRChat の実ウィンドウ、gamescope、GNOME、wlroots 系では確かめていない。

## 未検証

- 実際の VRChat (Proton) のウィンドウからの取得。DXVK/VKD3D の Vulkan スワップチェーンが
  XWayland で直接 Wayland にフリップされると、ウィンドウのピクスマップが空 (黒) のことがある。
  その場合フレームは `isFrameBlank` で捨てられ、何も読まれない。起きたら上の共有の経路を使う
- 共有の経路での実際の VRChat (gamescope、Wine の Wayland ドライバー)、GNOME と wlroots 系のポータル
- 実際のチャットボックスの色・不透明度・フォントでの見た目判定と行のまとめ方。しきい値は
  合成画像で決めたもので、実機のスクリーンショットで見直す必要がある
- Windows のリリースビルドでの起動 (spec の修正とテストのみ。実ビルドはしていない)
