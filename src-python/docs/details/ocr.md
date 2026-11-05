# ocr - VRChatチャット吹き出し OCR パイプライン

## 概要

VRChatの画面上に浮かぶチャット吹き出し（他プレイヤーのテキストチャット）を光学文字認識で読み取り、既存の翻訳パイプラインに流し込むためのモジュール群です。音声はマイク／スピーカーで文字起こしされていましたが、**画面に描画される他人のチャットは翻訳できない** という穴を埋めるための実装です。

出力先はメインメッセージログと SteamVR オーバーレイの2系統。VRChatの OSC チャットボックス（`/chatbox/input`）へは**送信しません**（他人の発言を自分のチャットボックスに垂れ流すのはユーザー体験・コミュニティ規範の両面で不適切なため、初版で明示的に封印）。

> **VRCT-VOX:** 上流の吹き出し検出モデル (`onnx/chatbox_yolox_tiny.onnx`) は使わない。
> 代わりに VRCT-VOX 独自の検出器 (`vrct_vox_chatbox_yolox_tiny.onnx`、MIT、任意のダウンロード) を
> ocr_bubble_detector.py の `BubbleDetector` で動かす。構築は ocr_chatbox_detector.py だけが行い、
> ハッシュ検証済みのダウンロードのパスしか渡さない。検出器なしで読む方法 (読み取り範囲 + PP-OCR の
> 行検出 + チャットボックスの見た目判定)、Linux の X11/XWayland キャプチャ、同意を得たモデルの
> ダウンロード、未実装の Wayland portal 経路の計画は [ocr-linux-capture.md](ocr-linux-capture.md) を参照。

## 主要コンポーネント

`src-python/models/ocr/` 配下に配置されており、既存の `models/transcription/` の構造（recorder → transcriber → pipeline）を踏襲しています。

### ocr_capture_hwnd.py — HWND ウィンドウキャプチャ
- Win32 API (`ctypes`、`user32.PrintWindow`/`PW_RENDERFULLCONTENT`) で対象ウィンドウの
  クライアント領域を直接レンダリングし BGR ndarray として取得。`mss` 等の画面座標
  グラブは使っていない — VRCT自身が画面上でVRChatウィンドウに重なっている場合、
  座標ベースのグラブだと最前面(=VRCT側)を誤って撮ってしまうため、ウィンドウ自身の
  サーフェスから直接描画させる `PrintWindow` を採用している
- 対象ウィンドウはタイトルの部分一致(大文字小文字を区別しない)で検索する。既定は
  "VRChat" だが `config.OCR_WINDOW_TITLE` で変更可能(改造版ランチャー等で
  ウィンドウタイトルが異なるクライアントに対応するため)
- 最小化時（`IsIconic`）や空フレームは None を返してスキップ

### ocr_capture_openvr.py — OpenVR ミラーテクスチャキャプチャ
- `IVRCompositor::GetMirrorTextureD3D11(Eye_Left)` で HMD 左目の画像を取得し、CPU 用の staging テクスチャへコピーして読み出す
  （読み出し本体は `ocr_capture_d3d11.py`。収集ツール `tools/` と同じ実装を共有し、ツールはパス指定で読み込む）
- 実測（Meta Quest 3 / Virtual Desktop + SteamVR）: 3012x3284、BGR 変換込みで約100ms/枚。VRChat のウィンドウを最小化していても取れる
- OpenGL 版（`GetMirrorTextureGL`）は使えない。SteamVR が自分の D3D11 テクスチャを GL へ取り込めず（`GL_INVALID_OPERATION ... Invalid format.`）
  常に `CompositorError_InvalidTexture` を返す既知の不具合（ValveSoftware/openvr#178, #1410）。2026-09-27 に実機で再現を確認し D3D11 へ置き換えた
- OpenVR のセッションは Overlay / Clipboard と同じく `models/openvr_session.py`（参照カウント）経由で取得・解放する
- 読み出し前に、SteamVR が表示中のアプリが VRChat かを確認する（`getLastFrameRenderer()` と
  `getCurrentSceneFocusProcess()` が一致し、そのプロセスが `vrchat.exe`）。SteamVR Home 等なら None を返す。
  判定は収集ツール（`tools/ocr_capture_source.py`）で実機確認済みの方法と同じ

### ocr_capture.py — バックエンド選択ファサード
- SteamVR 起動状態を 5 秒間隔でリチェックし、backend を自動切り替え
  - **SteamVR 起動中** → OpenVR ミラーテクスチャ。VR 側で何も取れなければ（VRChat がシーンでない、
    読み出し失敗）、次のリチェックまで HWND キャプチャへ切り替える
  - **SteamVR 非起動** → HWND キャプチャ
- ログ `OCR capture backend -> ...` は、実際にフレームが取れた経路が変わったときだけ出す
- 切り替えの理由: VR プレイヤーは負荷軽減のため VRChat のデスクトップミラーウィンドウを最小化することが多く、その場合 HWND では黒フレームしか取れないため

### 取り込み元ごとの読み取り範囲

WindowsのデスクトップウィンドウとSteamVRのヘッドセット映像では、同じ割合の矩形でも指す場所が異なる。そのため`OCR_CAPTURE_REGION`をウィンドウ用として維持し、`OCR_VR_CAPTURE_REGION`をVRの左目側の映像用に追加した。旧設定はウィンドウ側に残し、VR側が未保存なら全体を補う。LinuxはX11/XWaylandのウィンドウだけを読む。保存形式と検証は[データ形式と保存](../../../docs/spec/data-and-persistence.md#チャット読み取りの範囲)を参照。

`OcrCapture.source`は`get()`が返した画像の元を`window`か`vr`で示す。画像がない場合は`None`。VRで取得できず同じ呼び出しの中でウィンドウへ戻った場合も、返した画像に合わせて更新する。`RegionCandidates.region`はこの値から範囲を選ぶ。範囲の切り取りと検出器の中心点による絞り込みは同じプロパティを使い、設定時点の取り込み元に固定しない。画像の再利用にも選択後の範囲が含まれる。取り込み元が不明な場合は、別の画面で指定した部分範囲を適用しない。

`Model.startOCRCapture()`は両方の範囲を`regions: {window, vr}`として開始前に予約し、ワーカーが最初のtickより前に適用する。設定変更は`Model.updateOCRCaptureSettings()`で開始・停止と共通のロックを取り、保存値の読み出しから検出器の選択、`applyConfig()`への予約までを直列化する。エンドポイントごとのロックだけでは、先に作った広い範囲のスナップショットが後から予約されるためである。ワーカーは`_applyPending()`で範囲をまとめて更新する。旧形式の`region`だけの内部更新も、ウィンドウ用として扱う。

設定ページは`/get/data/ocr_capture_status`だけを1秒ごとに取得し、現在の取り込み元と実行状態を1つの欄に表示する。範囲の編集欄もこの応答の`available_sources`を使い、別にポーリングしない。取得は状態の読み出しだけで、キャプチャを開始しない。Windowsでは両方の範囲をスライダーと模式図で編集でき、Linuxではウィンドウ側だけを表示する。編集によって取り込み元を切り替えたり、OCRをオンにしたりはしない。

### ocr_bubble_detector.py — 吹き出し検出（YOLOX-Tiny / ONNX）
- 推論に失敗したら `OcrDetectorError` を投げる。候補がない場合の空リストとは区別し、パイプライン側でログの重複抑止、再試行、UIの失敗表示を行う。
- 収集したVRChatのスクリーンショットで学習した検出モデルで、吹き出しの矩形を直接得る
- 推論は onnxruntime のみ（faster-whisper が Silero VAD 用に既に依存しているので追加依存なし）。
  YOLOX も torch も推論には不要。grid/stride のデコードはエクスポート時にグラフへ
  入れてあるので、このモジュールがやるのは letterbox・閾値・NMS・元画像座標への戻しだけ
- モデルは `src-python/models/ocr/onnx/chatbox_yolox_tiny.onnx`（約5.5MB、INT8）を同梱。
  `findModelPath()` が凍結時は `_internal/ocr_onnx/`、ソース実行時はパッケージ内を見る。
  最初の `detect()` まで読み込まないので、OCRを使わない起動ではメモリも時間も使わない
- **入力サイズは可変**。VRChatのウィンドウはユーザーがリサイズできるのでアスペクト比が
  一定ではない。`_letterbox()` は長辺を `DEFAULT_IMAGE_SIZE`(1280) に合わせ、短辺を32の
  倍数（FPNのstrideが8/16/32）へ切り上げた大きさでキャンバスを作る。余白は左上寄せなので
  座標の戻しは `scale` で割るだけ。正方形に固定すると16:9で4割強を余白の推論に使う
- 前処理は YOLOX の `preproc` と同じで、BGRのまま・0-255のまま・余白色114。
  YOLOv8n のときの「RGB変換して255で割る・中央寄せ」とは違うので、モデルを
  差し替えるときはここも合わせる
- NMS は `nonMaxSuppression()` が numpy で行う（YOLOXの実装は torchvision.ops に依存して
  いてONNXへ落ちない）。おかげで閾値が `BubbleDetector(confidence=...)` 一箇所になった。
  YOLOv8n のときはエクスポート時のconfがNMSへ焼き込まれ、実行時に下げても候補が増えなかった
- ライセンス: この .onnx だけはリポジトリの MIT ではなく **VRCT 専用の利用許諾**。
  同ディレクトリの `LICENSE.txt` / `LICENSE.en.txt` / `NOTICE.txt` がそのまま配布物の
  表記になるので消さない。経緯は `docs/ocr_model_license.md`
- 結果は信頼度の降順（NMSが強い順に残すので、この時点で降順になっている）。
  `MAX_CANDIDATES_PER_TICK` で上位数件のみOCRに回す
- 実行時の閾値は `BubbleDetector(confidence=...)`（既定0.7）。2026-10-07 のモデルで、固定val80枚
  (正解70個)は 0.5で68/70・余分な候補4、0.7で67/70・余分3（余分はラベルずれ、本当の誤検出は0）。
  学習に入れていない VRCT 自身のオーバーレイ49枚では、0.5で誤検出1、0.7で0。実機で低い閾値だと
  VRChat の config 画面を誤検出したため引き上げた。モデルを学習し直したら決め直す
  （表は上流 VRCT の https://github.com/misyaguziya/VRCT/blob/develop/docs/ocr_yolo_training.md）
- VRCT 自身のオーバーレイ（翻訳ログの窓）は暗い角丸パネルに文字が並ぶので吹き出しと紛らわしく、
  拾うと OCR が自分の翻訳を読み返して翻訳し直すループになる。文字列で照合して捨てる案は、
  切り取り方で OCR 結果が大きく変わるので採らず、検出器にネガティブとして教えている
  （経緯は docs/ocr_model_retrain_2026-10-07.md）
- 速度は 16:9 のウィンドウで約60ms/枚、正方形に近い窓でも約110ms/枚（i7-9700K の実測、
  他の処理が動いていると2〜3倍ぶれる）。検出は tick のOCR予算の外で走るので、
  そのまま tick の長さに乗る
- `crop_padding`（既定4px）はOCRに渡す切り出しを各辺4px広げる。小さい吹き出しでは
  この分だけ枠がGTからずれるので、IoUで評価するときは0にして測る
- 学習・再学習とモデルの差し替え手順は [上流 VRCT の docs/ocr_yolo_training.md](https://github.com/misyaguziya/VRCT/blob/develop/docs/ocr_yolo_training.md)

#### 経緯: 色/輪郭ヒューリスティックからの置き換え（2026-09-17）
初版は OpenCV の adaptiveThreshold → 輪郭抽出 → 幾何フィルタ（面積比・アスペクト比・
画面端マージン・下部HUD除外）に、吹き出しパネルの「縁の色ばらつき」フィルタと位置
スコアリングを足した実装だった。VRChatのチャット吹き出しは、ワールド制作者が作る
看板・UIパネルと同じ「ワールド内3D要素」として描画されるため形状だけでは区別できず、
色ばらつきでの判別も実機で反証された（工場ゲームのUIパネル文字を誤検出）。
学習ベースの検出器に置き換えたことでこの一連のヒューリスティックは不要になり、
パラメータ（`collar_width` / `max_collar_std` / `center_bias_weight` 等）も含めて削除済み。

### ocr_engine_rapidocr.py — OCRエンジン (RapidOCR / ONNX PP-OCR)
- モデル指定ごとに推論器を遅延生成してキャッシュする。`readtext_bgr(crop)` は
  `[{"text", "confidence"}, ...]` を返し、例外は投げない (失敗時は空リスト)
- パイプラインは `readtext_bgr_or_raise` を使い、推論・結果の変換の例外を
  「読める文字がない」と区別する。文字だけを使う既存の呼び出し元には空リストを返す契約を保つ。
- **onnxruntimeのみで動く**。faster-whisper が Silero VAD 用に既に依存しているので、
  実行時依存は増えない。PaddlePaddle も torch も要らない
- `Det.limit_side_len=320`。RapidOCRの既定は短辺を736pxまで**拡大**する設定
  (`limit_type="min"`) で、吹き出しの切り出しは小さい(短辺100px前後のこともある)ため
  7倍に引き伸ばされ1枚2秒近くかかっていた。320で実測1778ms→790msになり精度は落ちなかった

#### 経緯: EasyOCRからの置き換え (2026-09-18)
学習用データセットの吹き出し95枚をCPUで読み比べた結果。CERは低いほど良い。

| エンジン | CER | ほぼ正解(CER≤0.2) | 中央値 |
|---|---|---|---|
| EasyOCR (ja+en) | 0.69 | 34% | 643 ms/枚 |
| **PP-OCRv6 small** | **0.27** | **66%** | 790 ms/枚 |
| PP-OCRv5 ch | 0.62 | 54% | 918 ms/枚 |

速度はEasyOCRと同程度(中央値はむしろEasyOCRが速い)で、**速くなったから替えたのではない**。
決め手は精度と依存の重さ。EasyOCRは縦書き(あいうえお/かきくけ)を全く読めず、句読点が落ち、
単語間のスペースが潰れていた。またEasyOCRはtorchを必須依存に持ち、torch(1.2GB)・
scipy(119MB)・scikit-image(30MB)を配布物へ連れてきていた。

### ocr_languages.py — 設定値からモデルを決める
- PP-OCRv6 small は1モデルに**日本語・英語・中国語(簡繁)＋ラテン文字系40言語**が入るので、
  この範囲は `auto` のまま言語を選ばせずに読める
- ハングル・キリル文字・タイ文字・アラビア文字・デーヴァナーガリーは v6 small に含まれず、
  PP-OCRv5 のスクリプト別モデルへ切り替える。選択肢はこの5系統 (6言語) と `auto` だけ
- 旧バージョンが保存した言語名 (Japanese / English など) は auto と同じモデルへ解決する
- 未対応の値は None を返し、呼び出し側が起動を拒否する。黙って別モデルへ
  フォールバックしない

| 設定値 | 使うモデル |
|---|---|
| `auto` (既定) と日英中・ラテン系の言語名 | PP-OCRv6 small |
| Korean | PP-OCRv5 mobile / korean |
| Russian, Ukrainian | PP-OCRv5 mobile / cyrillic |
| Thai | PP-OCRv5 mobile / th |
| Arabic | PP-OCRv5 mobile / arabic (精度は低め) |
| Hindi | PP-OCRv5 mobile / devanagari |

VRCT-VOX ではモデルを配布物へ同梱しない。ユーザーが 設定 → チャット読み取り で条件を確認して
同意したときだけ、固定リビジョンの PaddleOCR 公式 ONNX (Hugging Face、Apache-2.0) を
`downloaded_models/` へダウンロードし、`ocr_models.py` がそのパスを RapidOCR へ明示的に渡す
(RapidOCR 自身のダウンロードは無効化)。開発時は `tools/fetch_ocr_models.py --root ...` でも同じ
経路で取得できる。詳細は [ocr-linux-capture.md](ocr-linux-capture.md)。

### ocr_pipeline.py — オーケストレーター
- 独立スレッドで poll ループを回し、capture → detect → OCR（同じ候補画像なら認識結果を再利用）→ dedup → callback
- コールバックのペイロードはマイク／スピーカーの transcript 結果と同じ形状で、`Controller.ocrMessage` から既存の翻訳・オーバーレイ経路に載せられる

## クラス構造

### OcrPipeline クラス (ocr_pipeline.py)

```python
class OcrPipeline:
    def __init__(
        self,
        callback: Callable[[dict], None],
        source_language: str = "auto",
        window_title: str = "VRChat",
        poll_interval_ms: int = 750,
        min_confidence: float = 0.85,
        min_text_length: int = 2,
    ) -> None:
        self._callback = callback
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._capture: Optional[OcrCapture] = None
        self._detector = BubbleDetector()
        self._dedup = _DedupCache()
        self._reader = None
```

### OcrCapture クラス (ocr_capture.py)

```python
class OcrCapture:
    BACKEND_HWND = "hwnd"
    BACKEND_OPENVR = "openvr_mirror"
    BACKEND_NONE = "none"

    def __init__(self) -> None:
        self._hwnd = HwndCapture()
        self._openvr: Optional[OpenVRMirrorCapture] = None
        self._backend = self.BACKEND_NONE
```

## 処理フロー

```
┌───────────────────┐        ┌──────────────────┐
│  OcrCapture       │        │ BubbleDetector   │
│  (HWND / OpenVR)  │──BGR──►│ (YOLOX-Tiny/ONNX)│
└───────────────────┘        └────────┬─────────┘
                                      │ [(bbox, crop), ...]
                                      ▼
                             ┌──────────────────┐
                             │ OCR / 結果の再利用 │
                             │ (crop→words+conf)│
                             └────────┬─────────┘
                                      │ merged text
                                      ▼
                             ┌──────────────────┐
                             │ _DedupCache      │  ← text_hash + 最後に見た時刻
                             │ (LRU)            │
                             └────────┬─────────┘
                                      │ unique text
                                      ▼
                             ┌──────────────────┐
                             │ callback         │
                             │ (Controller.     │
                             │  ocrMessage)     │
                             └────────┬─────────┘
                                      │
                                      ▼
                          既存 Translator → UI ログ + Overlay
                                     （OSC には送らない）
```

## 認識結果の再利用

候補画像の全画素を BLAKE2b（128 bit）でハッシュし、形状とデータ型もキーに含めて、
成功した認識結果（文字なしの空リストも含む）を最大32件のLRUに保存する。
切り出しでできる非連続な配列もC順序で全画素を読む。画像本体は保持しない。
候補の位置はキーに含めず、再利用時も現在の位置で吹き出しの分割・見た目判定・行の結合を行う。
失敗後の待機中を除き、取り込みと検出は毎tick行い、認識だけを省く。

キャッシュは言語・モデル指定・モデルの保存先・推論器の同一性、信頼度、範囲、検出器とその設定、
取り込み元と取得後のバックエンドなどの処理条件ごとに破棄する。`applyConfig` の反映時、
フレームを取得できないとき、停止・開始時、ワーカー終了時にも捨てる。
認識結果の再利用用キャッシュと、配送済みの文を覚える `_DedupCache` は別物である。
再利用しても通常の重複判定へ渡し、「最後に見た時刻」を毎回更新する。
消えた候補の保存結果だけを配送したり、見えたことにしたりはしない。
時間予算で読み直しを待つ上位6候補も、現在の全画素が保存結果のキーと一致すれば、
配送済みの文の「最後に見た時刻」だけを更新する。一巡に30秒以上かかっても同じ文を再配送しない。
この確認は20秒の認識期限を延ばさず、未配送の文を配送することもない。

`RECOGNITION_REFRESH_SEC` は20秒。推論結果が毎回同じとは限らないため、最後の実認識から
20秒経ったら再利用せず、次にその候補を処理できるtickで読み直す。ヒットしても期限は延ばさない。
既定の750ms間隔で約27回に1回の認識を残し、固定画像での負荷削減と結果の見直しを両立する。
tickの予算・上位6候補の制限・失敗時の待機は維持するので、それらによる遅延は別に生じる。

認識が例外になったら全ての認識キャッシュを捨て、古い成功結果で代用しない。
再利用では推論器の失敗履歴や待機を解除せず、実認識の成功だけを復旧とする。
これにより既知の故障は従来の連続失敗とbackoffに入り、未判明の故障も定期的な再読取で確認する。
30秒ごとのログは `ocr` を実呼び出し数のまま保ち、`reused` に再利用した候補数を記録する。
`text` は文字を得た候補数、`bubble` は後処理で得た吹き出し数、`emit` は配送数で、
再利用した結果も従来と同じ段階で集計する。

## 行の繋ぎ方

OCRは吹き出し内の各行を別々に返す。そこには「送信者が入れた改行」と「幅による
折り返し」の両方が含まれるが、**画像からは区別できない**。VRChatはどちらも同じように
描画し、吹き出しの幅も内容に合わせて決まるため。実データで確認したところ、改行4行の
箇条書き (右端 100/99/98/91%) も折り返された1文 (100/100/65%) も、行の右端の分布は
同じだった。

そこで次の規則で繋ぐ (`_mergeWords`)。

1. 前の行が文末の記号 (`。．.！!？?…」』)）`) で終わっていれば**改行**
2. それ以外は折り返しとみなして繋ぐ。ラテン文字が絡む境目は**スペース**、
   日本語・中国語だけの境目は**詰める**

2つ目は、全部スペースで繋いでいたときに日本語へ余計なスペースが入っていた
(「夕焼けで少 しずつ」) ための措置。右端の余白で改行を判定する案も試したが、
吹き出しに複数の文字列が写ると基準がずれて折り返しを改行と誤判定したのでやめた。

文末記号の無い改行 (「上の行」「下の行」など) は復元できない。これは画像からは
判別不能なので、仕様として受け入れている。

## 重複抑制（dedup）

**覚えている間は同じ文を配送しない。** 時間で解禁する方式ではない。

- Controllerが受け付けた文だけを `_DedupCache` (最大128件) に持ち、見るたびに「最後に見た時刻」を更新する。拒否された文は次のtickで再度試す。コールバックの例外も配送済みにせず、tickの失敗として記録・表示し、待ち時間を置いて再試行する
- 保持時間は画面から**消えてから**測る。`DEDUP_RETENTION_SEC` (30秒、定数) のあいだ現れなければ
  忘れ、以降に同じ文が出たら新しい発言として配送する。設定にはしていない。記憶だけで時間の上限を
  持たないと「はい」「Wow!」のような短文がLRUから押し出されるまで二度と表示されず、静かな
  インスタンスでは何時間もかかるため。一方でユーザーが決める材料も無い
- 保持時間の下限は **tick間隔の2倍**。1tickはOCR1件あたり約0.8秒かかるので、設定値の方が
  短いと出続けている吹き出しでも見るたびに忘れられ、同じ文が繰り返し配送される
  (実機で 1秒設定 / tick 1〜2.6秒のときに再現、2026-09-18)
- tick間隔は候補のないときやフレームのないときも測り、同じ場所で古い記録を捨てる。候補が消えていた時間全体を「遅い1tick」として扱わない。通常のポーリングで30秒を超えて見えなければ、同じ文でも再配送する
- 5文字未満の文は完全一致だけで判定し、「はい」と「いや」などの別の返事を落とさない。
  長い文は短い方の文字数の2割（切り捨て）、最大2文字までの編集をOCRのゆらぎとして扱う

## 1 tick あたりの処理量制限

混雑したワールドや文字の多い UI では候補矩形が数十件になることがあり、全件 OCR するとループが数秒止まって Whisper と GPU を奪い合います。そのため:

- `MAX_CANDIDATES_PER_TICK`（既定6）で検出器の信頼度上位の候補に絞る。前回の矩形との重なり（IoUが0.5以上）で候補を対応付け、まだ試していない候補、最後に試した順が古い候補を先に読む。信頼度順が変わったり少し移動したりしても順番を引き継ぐ。保持するのは矩形と試した順だけで、読む画像は現在のフレームから選ぶ
- `TICK_OCR_BUDGET_RATIO`（既定 0.8）× poll interval を時間予算とし、超過した時点でその tick を打ち切り
- 推論例外が出たtickは残りの候補を読まず、連続失敗時は取得・検出・推論を待機する。
  ログの集約、待機時間、復旧の条件は [UC-05](../../../docs/spec/use-cases.md#uc-05-vrchatのチャットボックスを読み取って訳す) を参照。

## 実行中の失敗と状態表示

検出・取り込み・tick全体の例外には、それぞれ独立した再試行の時刻を持つ。
初回の失敗から1秒、2秒、4秒と待ちを延ばし、上限は30秒とする。
認識の例外は従来どおり3回連続して失敗してから待ちを延ばす。
配送コールバックの例外はtick全体の例外として扱い、同じログ集約と待ち時間を使う。
WindowsのOpenVR・HWNDも取得失敗を記録し、どの取り込み元からも画像が取れないときは
取り込み段階の再試行に進む。VRが失敗してもデスクトップから画像が取れれば読み取りを続ける。
どの段階でも、待機中は取得・検出・認識を止め、設定変更と停止は受け付ける。
検出器が動作中に失敗しても範囲読みに自動で変えず、読み取りを一時停止して同じ検出器を再試行する。
範囲読みに変えると読み取る対象が広がるためである。

X11のデコーダーが扱えない画素形式やXGetImageの失敗は `X11CaptureError` として
ファサードへ渡す。ファサードの障害記録をパイプラインが確認して再試行を制御する。
画像形式を確認しない開始前の準備確認だけで「読み取り中」とは表示しない。
最初のフレーム待ちと、失敗による一時停止を区別する。フレームが取れない間は取り込みの復旧としない。

`runtimeStatus` は `state`（`stopped` / `waiting` / `reading` / `retrying`）、
`stage`、既存の `OCR_DISABLED_*` による `error_code`、実際の候補取得元 `detector` を返す。
`/get/data/ocr_capture_status` はこの4項目に加え、`active`（有効化済みで停止していないワーカーがあるか）、
`source`（直近の画像の取り込み元。`window` / `vr` / `null`）、`available_sources` を返す。
`available_sources` はWindowsで `["window", "vr"]`、Linuxで `["window"]`。
無効化後やワーカーの停止通知後は、スレッドが終了処理中でも `active: false`、`state: stopped` とし、
`source`、`stage`、`error_code`、`detector` は `null` にする。
この取得は画像の取り込み、デバイスの検査、モデル読み込みを行わない。
OCR設定画面を開いている間だけ1秒間隔で1回問い合わせ、閉じると止める。
取り込み元と停止中・待機中・読み取り中・再試行中（失敗した段階）を1つの状態欄にまとめる。
停止中は開始に必要な準備も同じ欄に表示し、検出器の取得・選択・実際の使用状態は別の検出器欄に残す。
正常な状態応答は `POLLED_ENDPOINTS` により診断ログへ書かない。再試行の理由を含む場合も200で返す。
実行時のエラーコードは一時停止の理由を示す。開始失敗の通知とは異なり、オンのまま再試行する。

検出器のダウンロード済み状態と使用設定は `/get/data/ocr_readiness` で、
ワーカーが実際に選んだ検出器は `runtimeStatus.detector` で確認する。
範囲読みのまま稼働中に検出器を取得した場合は、オフ・オンが必要なことを表示する。
既存の設定変更で切り替えを予約した場合は、`_applyPending` が反映してから表示を変える。
読み込み失敗による範囲読みへの復帰も、その実態を表示する。

## OpenVR セッションの共有について

OpenVR の初期化は**プロセス単位**で、Overlay・Clipboard と共有しています。そのため本モジュールは:

- `openvr.init()` / `openvr.shutdown()` を直接呼ばず、`models/openvr_session.py` の `acquire()` / `release()` を使う。
  本当の `openvr.shutdown()` は、全員が解放したときだけ走る
- ミラーテクスチャは**初回に 1 度だけ取得**して毎フレーム使い回す。毎回取り直すと古いフレームが返り続ける（ValveSoftware/openvr#1888）。
  D3D11 の資源は OCR のワーカースレッドで作成・読み出し・解放する
- 取得に失敗し続ける間（SteamVR 再起動中など）は、トレースバックを最初の1回だけ `error.log` に残す
- 失敗時はテクスチャと自分のセッション参照を解放して `_initialized` を落とし、次 tick で取り直す
  （Overlay の `reStartOverlay()` と同じ「解放してから取り直す」順）。OCR 停止時（`close()`）も参照を解放する
- VRChat 以外のシーンを表示中なのは異常ではないので、テクスチャもセッションも保持したまま None を返す

## 設定の反映タイミング

OCR系の設定は**実行中でも次のtickから反映される**。言語以外は `Controller` の各setterが
`model.updateOCRCaptureSettings()` を呼び、`OcrPipeline.applyConfig()` が値を預かって、
ワーカースレッドが次のtickの頭で `_applyPending()` で取り込む。
このとき認識結果の再利用用キャッシュも破棄する。

| 設定 | 反映のされ方 |
|---|---|
| `OCR_SOURCE_LANGUAGE` | 停止中はそのまま保存する。稼働中は保存前に取得済みファイルを検証して推論器を準備し（キャッシュ済みなら再利用）、次のtickで切り替える。重複抑制のキャッシュも捨てる |
| `OCR_WINDOW_TITLE` | キャプチャを開き直す |
| `OCR_POLL_INTERVAL_MS` / `OCR_MIN_CONFIDENCE` / `OCR_BUBBLE_MIN_TEXT_LENGTH` | 値を差し替える |

言語のsetterは `model.setOCRSourceLanguage()` で開始・停止と直列化する。
停止中は検証せずに保存する（取得の案内が選んだ言語のモデルを示せるように。足りないファイルは開始時に知らせる）。
稼働中は `resolveModelFiles()` でサイズ・SHA-256を検証し、開始時と同じ `getReader()` で推論器を準備してから保存する。読み込みは要求を処理する側で済ませ、
`applyLanguage()` が言語と準備済み推論器を一緒に預かる。ワーカー上では読み込みを行わず、
次のtickで参照だけを切り替えるので、保存後に読み込み失敗を黙殺する経路はない。
言語以外の設定変更で、この待機中の切り替えを上書きしない。

未取得なら `OCR_DISABLED_MODEL_MISSING`、破損や読み込み失敗なら
`OCR_DISABLED_MODEL_LOAD_FAILED` を、変更前の言語を `data` に入れて返す。
UIは言語の待機を解除してその値へ戻し、稼働スイッチと既存の推論器を維持する。
ファイル検証は同意済みの取得先だけを使い、ダウンロードは起こさない。

キャプチャのOSリソースはスレッドに紐づくので、開き直す処理は引き続き
**使っているワーカースレッドの側で**行う。

## アプリ終了時の停止

`Controller.shutdown()` は最初にOCRの開始受付と結果の配送を閉じ、稼働スイッチをオフにして
`model.requestOCRShutdown()` でワーカーの停止イベントを立てる。モデル読み込みが
開始・停止のロックを保持していても、この通知は待たない。読み込み中だった開始要求も、
終了通知を確認したらキャプチャを起動せずに戻る。

その後、既存のサービス停止ヘルパーで `stopOCRCapture()` を最大5秒待ってから、
翻訳・オーバーレイなどの出力先を終了する。期限を越えたワーカーは所有したままにし、
戻った時点で自分が作ったキャプチャを閉じる。推論自体を強制中断することはできないが、
終了後の新しいtickと結果のコールバックは抑止する。既に翻訳中だったOCRメッセージも
`publication_guard` で遅れた出力を捨てる。watchdogの強制終了期限や他サービスの上限は変えない。

## 設定キー

`src-python/config.py` に `ManagedProperty` として追加されています。

| キー | 型 | 既定値 | 説明 |
|---|---|---|---|
| `ENABLE_OCR_CAPTURE` | bool | False | OCR パイプラインの有効化（serialize=False, 起動毎にオフ） |
| `OCR_SOURCE_LANGUAGE` | str | "auto" | 読み取る言語。`auto` は日英中＋ラテン文字系を1モデルで読む。別モデルが要る文字体系のみ明示選択する（選択肢は `ocr_languages.SELECTABLE_LANGUAGES`） |
| `OCR_WINDOW_TITLE` | str | "VRChat" | キャプチャ対象ウィンドウのタイトル部分一致文字列（大文字小文字を区別しない） |
| `OCR_POLL_INTERVAL_MS` | int | 750 | キャプチャ間隔（100〜5000） |
| `OCR_MIN_CONFIDENCE` | float | 0.85 | OCR 信頼度の下限（0.1〜0.99）。PP-OCRは誤読時もスコアが高く、実測では 0.55 で誤りを1件も落とせず、0.85 なら正解を失わずに誤りの34%を落とせた |
| `OCR_BUBBLE_MIN_TEXT_LENGTH` | int | 2 | 最小テキスト長（1〜50） |
| `OCR_CAPTURE_REGION` | dict | `{x: 0, y: 0, width: 1, height: 1}` | デスクトップウィンドウ内の範囲。旧版の単一範囲を引き継ぐ |
| `OCR_VR_CAPTURE_REGION` | dict | `{x: 0, y: 0, width: 1, height: 1}` | SteamVRの左目側の映像内の範囲。未保存なら映像全体 |

値域・選択肢は config のディスクリプタ（`allowed=`）で検証する。setter は他の設定と同じく
`@_configValidationErrorResponse(ErrorCode.VALIDATION_CONFIG_VALUE_INVALID)` を付け、不正値は
エラー応答で拒否する（丸めない）。getter は `_SIMPLE_CONFIG_GETTERS` で生成する。
読み取り言語の選択肢は `config.SELECTABLE_OCR_SOURCE_LANGUAGE_LIST`（中身は `ocr_languages.SELECTABLE_LANGUAGES`）。

## エンドポイント

`mainloop.py` に登録済み。Frontend からは `useOcr()` フック経由で自動的に叩かれます。

- `/set/enable/ocr_capture`, `/set/disable/ocr_capture` — 開始・停止。翻訳と同じメイン機能として
  「Main Window」グループに置き、初期化完了までロックする。状態は保存せず起動時は常にOFFなので
  `/get/data/ocr_capture` は無い
- `/get/data/ocr_*`, `/set/data/ocr_*` — 各設定キー（setterは実行中のパイプラインへ即時反映する）
  - エンジンを選ぶ設定は持たない。実装が1つしか無いのに保存値と判定値がずれてOCRが起動しなくなる事故を起こしたため (2026-09-18)
- `/get/data/selectable_ocr_source_languages` — OCRで選べる言語の一覧（UIのドロップダウンの中身）
- `/get/data/ocr_capture_status` — 取り込み元、実行状態、実際に使う検出器をまとめて返す読み出し専用の状態取得。停止中でも問い合わせられる
- `/run/transcription_ocr_message` — OCR 結果を UI ログに配送（`useReceiveRoutes.js`）

## Controller 連携

- `Controller.startOcrCapture() -> bool` — 文字起こしと同じく `config.ENABLE_OCR_CAPTURE = self.startOcrCapture()`
  の形で呼ぶ。文字認識モデルと吹き出し検出モデルを読み込み終えてから戻る（翻訳のONと同じく応答を待たせる）。
  失敗したら `model.startOCRCapture` が投げた `OcrStartError` の `OCR_DISABLED_*`（それ以外の例外は
  `OCR_DISABLED_UNKNOWN`）を、翻訳の `TRANSLATION_DISABLED_VRAM` と同じく `/run/enable_ocr_capture` へ送って False を返す
  - ワーカーは `activation_ready` で `ENABLE_OCR_CAPTURE` の確定を待ってから最初のtickを実行する。待機中の停止・終了通知も有効
- `Controller.stopOcrCapture()` — 停止
- `model.setOCRSourceLanguage()` — 停止中は言語を保存する。稼働中はモデルを検証・準備してから保存し、推論器の切り替えを予約する
- `model.updateOCRCaptureSettings()` — 言語以外の設定変更を実行中のパイプラインへ渡す
- `Controller.ocrMessage(result)` — `OCR_MESSAGE_SPEC` を渡して `_processMessage` に委ねる
  (mic/speaker/chat と同じ共通パイプライン。差分は spec 側に持たせている)
  - OCR固有の差分: OSCへ送らない (`osc_send_gate_attr=None`)、小さいオーバーレイを使わない、
    payload に `source: "ocr"` を載せる (UIがバッジ表示に使う)
  - **OSC 送信は行わない**（コード内コメントで明示）
  - 有効化前、停止後、終了中や配送epochが失効した結果はFalseを返し、パイプラインの配送済み記録に残さない

## UI

- サイドバー: `config_page/sidebar_section/SidebarSection.jsx` に "OCR" タブ追加
- 設定画面: `config_page/setting_section/setting_box/ocr/Ocr.jsx`
  - 有効化トグル、ソース言語入力、GPU トグル、poll interval / min confidence / min text length / dedup cooldown スライダー

## 動作確認手順

Windows + VRCT ビルド前提。詳細は「VR モードでのデスクトップミラー最小化」ケースを含めて検証してください。

1. `pip install -r requirements.txt` で依存を追加インストール
2. VRCT 起動 → 設定画面 → OCR タブ
3. Desktop モード：VRChat 起動 → 他プレイヤーがチャットを打つワールドに入る → OCR 有効化 → ログに翻訳が並ぶこと
4. VR モード（通常）：SteamVR 起動 → VRChat VR モード → OCR 有効化 → メインログとオーバーレイに翻訳が出ること
5. VR モード（最小化）：上記状態でデスクトップミラーウィンドウを最小化 → 翻訳が継続すること（backend が `openvr_mirror` に切り替わっている）
6. VRChat のチャットボックスに OCR 翻訳が**流れていないこと**を確認

## 既知の制約

- **学習データが1ワールド・1セッションの100枚**しかない。別のワールドや距離・
  明るさが大きく違う場面では取りこぼしや誤検出が出る可能性が高い。取りこぼすなら
  `BubbleDetector(confidence=...)` を下げ、その場面の画像を集めて再学習する
- **ワールド由来のテキスト**（看板・ワールド内の案内文）は検出対象外として学習している。
  アバターのチャット吹き出し（角丸の暗いパネル＋しっぽ）だけを拾う
- **VRChat Desktop モード起動 + SteamVR も起動中** の場合は、SteamVR が表示中のアプリが VRChat でないため、次の再判定まで HWND キャプチャで読む（デスクトップのウィンドウが最小化されていれば読めない）
