# ADR-008: 外部の合成音声エンジン（VOICEVOX系、COEIROINK）を読み上げに使う

Status: 採用（2026-11-15、0.3.0に入れる）。未実装。
Date: 2026-11-15
Related: [ADR-007](adr-007-translated-speech-through-voice-conversion.md)

利用者が2026-11-15に設計メモを書き、「これもv0.3.0に入れて」と依頼した。1章から10章はそのメモである。11章と12章は、同じ日にコードと照らし合わせた結果と、9章の未決事項への提案である。

## 1. 目的

現在の AI ボイス（speech.cpp）による TTS に加えて、利用者が自分の PC にインストールした
合成音声エンジン（VOICEVOX、COEIROINK、AivisSpeech、SHAREVOX）を TTS バックエンドとして
選択できるようにする。対象は日本語読み上げ（`japanese` ロール）とする。

## 2. 方式：同梱ではなく「接続」

エンジン本体や音声モデルはアプリに同梱・再配布しない。利用者が導入済みのエンジンが
localhost で公開する HTTP API に接続する方式を採る。

理由（ライセンス）:

- VOICEVOX の本体利用規約は、本ソフトウェアの全部または一部の無断再配布を禁止している。
  エンジン／コアのコードは LGPL-3.0 等だが、音声ライブラリを含む配布物は別扱いであり、
  同梱配布は規約違反になる。再配布を希望する場合は製作者への相談が必要とされている。
- COEIROINK の公式利用規約も、ソフトウェア・モデルの再配布を禁止事項に含む。
- 生成音声の利用条件（クレジット表記など）は音声ライブラリごとに異なり、それを遵守する
  義務は音声を公開する利用者側にある。アプリ側は再配布をしないことで、この分界を保つ。

この方式は既存設計とも整合する。`settings.py` の `local_url()` は接続先を
`http://127.0.0.1:PORT` 形式のローカルサーバに限定して検証済みであり、
外部エンジン接続も同じ制約（ループバックのみ、LAN へ公開しない）の下に置く。

## 3. 対象エンジンと API

| エンジン | 既定 URL | API 形式 | 備考 |
|---|---|---|---|
| VOICEVOX | `http://127.0.0.1:50021` | VOICEVOX API | 本家。話者 ID は整数 style id |
| SHAREVOX | `http://127.0.0.1:50025` | VOICEVOX 完全互換 | URL 差し替えのみで対応可 |
| AivisSpeech | `http://127.0.0.1:10101` | VOICEVOX 概ね互換 | 下記 5.2 の注意あり |
| COEIROINK v2 | `http://127.0.0.1:50032` | 独自 API（v2） | 専用アダプタが必要。下記 3.2 |

COEIROINK v1 は VOICEVOX 互換だったが、現行の v2 は互換ではないため対象外とする
（v2 のみを対象にする）。

### 3.1 VOICEVOX 互換 API の呼び出し手順

1. `GET /speakers` — 話者とスタイルの一覧を取得（設定 UI の話者選択に使う）
2. `POST /audio_query?text=...&speaker=<style_id>` — AudioQuery（アクセント・音素長など）を取得
3. `POST /synthesis?speaker=<style_id>`（body = AudioQuery JSON）— WAV バイト列を取得

### 3.2 COEIROINK v2 API の呼び出し手順

1. `GET /v1/speakers` — 話者一覧（`speakerUuid` と styles の `styleId`）を取得
2. `POST /v1/synthesis`（body に `speakerUuid`、`styleId`、`text`、各種 Scale を含む JSON）
   — 1 リクエストで WAV を取得。AudioQuery 相当の2段階呼び出しは不要
   （韻律の事前調整が必要な場合のみ `/v1/estimate_prosody` を使う）

## 4. モジュール構成（提案）

既存の `speechcpp_tts.py` と同じ流儀（`http.client` ベース、例外は安全なコードのみを
持つ `SpeechError` 相当、キャンセルは `CancelToken` 連携）で実装する。

- `src-python/models/tts/voicevox_tts.py`（新規）
  - VOICEVOX 互換クライアント。エンジン種別（voicevox / sharevox / aivis）と
    ベース URL をパラメータ化し、3 エンジンを1実装で賄う。
  - 接続確認（`/version` または `/speakers` への短いタイムアウトのプローブ）と
    話者列挙、合成（audio_query → synthesis）を担当。
- `src-python/models/tts/coeiroink_tts.py`（新規）
  - COEIROINK v2 専用クライアント。話者列挙と `/v1/synthesis` のみ。
- `src-python/models/tts/settings.py`（拡張）
  - `VoiceSettings` の `japanese` ロールにエンジン選択を追加する。
    例：`japanese_engine: str = "speechcpp"`（`speechcpp` | `voicevox` | `sharevox` |
    `aivis` | `coeiroink`）と、エンジン別の URL・話者（style id／speakerUuid+styleId）を
    保持するフィールド。既存フィールド（`japanese_url`、`japanese_voice` 等）の意味は
    変えず、追加フィールドは既定値により後方互換を保つ。
  - URL は既存の `local_url()` で検証する（ループバック以外を拒否）。
- スケジューラ／再生系（`tts_scheduler.py`、変換ルータ）は変更しない。
  新バックエンドは既存バックエンドと同じく WAV→PCM 変換後の `AudioFrame` 列を
  供給する側として接続する。

### 4.1 音声形式の変換

- 各エンジンの出力は WAV（VOICEVOX 既定 24kHz モノラル。出力サンプルレートは
  AudioQuery の `outputSamplingRate` で変更可能）。
- 既存パイプラインが期待する PCM 形式へ、WAV デコードと必要に応じたリサンプルを
  バックエンド側で行う。変換はメモリ上で完結させ、一時ファイルを作らない。

## 5. 実装上の注意

### 5.1 遅延と文分割

- エンジン API は文単位の一括合成で、ストリーミング合成はできない。翻訳文は
  既存の文分割に従い、文ごとに合成→順次再生する。初回発話までの遅延は
  CPU 推論で短文あたり概ね 0.3〜1 秒程度を見込む（実機計測で要確認）。
- 合成中の中断（新しい発話による割り込み等）は既存の `CancelToken` の仕組みに合わせ、
  進行中の HTTP リクエストを閉じられるようにする。

### 5.2 AivisSpeech の互換性の範囲

- AivisSpeech Engine は VOICEVOX API と概ね互換だが、AudioQuery の内容をクライアント側で
  編集してから `/synthesis` に渡すと、仕様差異により正常に合成できない場合がある。
  本実装では AudioQuery を改変せず、そのまま合成に渡す（速度・音量等の調整は
  AudioQuery の Scale フィールドの範囲に限る）。

### 5.3 エンジン未起動時の扱い

- エンジンは利用者が別途起動する外部プロセスであり、アプリは起動・終了を管理しない
  （speech.cpp の bundled モードとは異なる）。未起動・接続失敗は「未準備」状態として
  設定 UI に表示し、発話時は安全に失敗させる（既存の失敗通知の流儀に従う）。
  自動起動は行わない。
- 複数エンジンの同時起動はポートが異なるため可能。検出はプローブの成否で行い、
  起動していないエンジンを一覧から除外するのではなく「未接続」と明示する。

### 5.4 ログとプライバシー

- 既存コードの規約どおり、読み上げテキスト・音声データ・サーバ応答ボディを
  ログや例外メッセージに含めない。エラーは安全なコードのみで表す。

## 6. ライセンス・運用上の取り決め

- アプリはエンジン本体・音声モデルを一切同梱・再配布しない。設定 UI には各エンジンの
  公式サイトへのリンクと「エンジンは別途インストールが必要」の案内を置く。
- 生成音声のクレジット表記義務は音声ライブラリ（キャラクター）ごとに異なり、
  公開形態に応じた遵守は利用者の責任である。設定 UI の話者選択付近に、
  規約確認を促す注記とクレジット表記の例（例：`VOICEVOX:ずんだもん`、
  `COEIROINK:合成音声名`）を表示する。
  - VOICEVOX：声ごとに個別規約。クレジット必須の声が多く、表記省略には
    有償契約が必要な権利者もいる。
  - COEIROINK：本体規約で `COEIROINK:合成音声名` のクレジットが必須。
    加えて音声ライブラリごとの規約が適用される。
  - AivisSpeech：エンジン自体はクレジット不要で利用可。モデル（AIVMX）ごとに
    ライセンス（ACML 等）が設定されるため、モデル側の条件が優先する。
  - SHAREVOX：声ごとにクレジット必須の場合がある。
- 本機能は日本語専用である。VOICEVOX 系エンジンは日本語以外のテキストを正しく
  合成できないため、`multilingual` ロールには割り当てない（英語等の読み上げが
  必要になった場合は、組み込み可能な Piper（MIT）や OS 標準音声が別途候補になる）。

## 7. テスト方針

- 既存の `src-python/test/test_tts_*.py` の流儀に合わせ、実エンジンを使わず
  ローカルの偽 HTTP サーバで契約を検証する。
  - VOICEVOX 互換：`/speakers` の解釈、audio_query→synthesis のリクエスト形、
    WAV 応答の PCM 化、接続失敗時のエラーコード。
  - COEIROINK v2：`/v1/speakers` の解釈、`/v1/synthesis` のリクエスト形
    （speakerUuid／styleId の受け渡し）。
  - 設定：エンジン選択フィールドの検証（未知のエンジン名、ループバック以外の
    URL の拒否）。
- 実機確認は VOICEVOX と COEIROINK v2 の実プロセスで行い、短文の合成遅延と
  VRChat 併用時の負荷を計測する。

## 8. 非対象（この提案に含まないもの）

- エンジン本体の自動インストール・自動起動・同梱配布
- 音声モデルのダウンロード管理（既存のモデルダウンロード基盤には載せない）
- 歌唱合成、モーフィング、ユーザー辞書編集などのエンジン固有機能の UI 化
- COEIROINK v1 互換モード
- 多言語ロールへの割り当て

## 9. 決定事項（未決）

1. 既定のエンジン選択肢の提示順と、未接続エンジンの表示方法（設定 UI の設計に依存）
2. 話者・スタイルの保存形式（style id の数値保存か、話者名＋スタイル名の保存か。
   エンジン側のアップデートで id が変わる可能性への配慮）
3. AivisSpeech を初回リリースの対象に含めるか（互換性の検証コストとの兼ね合い）
4. 合成遅延の実測結果次第で、文より細かい分割（句読点単位）が必要かどうか

## 10. 参考資料

- VOICEVOX 公式サイト・利用規約：https://voicevox.hiroshiba.jp/term/
- VOICEVOX ENGINE リポジトリ（API 仕様、OpenAPI 定義を同梱）
- COEIROINK 公式サイト・利用規約：https://coeiroink.com/terms
  ／ API リファレンス：https://coeiroink.com/help/002
- AivisSpeech Engine リポジトリ（VOICEVOX API との互換性に関する記載を含む）
- SHAREVOX 公式サイト

## 11. コードとの照合（2026-11-15）

メモの前提をdevelop（`e21f319f`）のコードと照らし合わせた。

### 合っていた前提

- `local_url()`（`src-python/models/tts/settings.py`）は、`http`のループバック（`127.0.0.1`、`localhost`、`::1`）だけを受け付け、パス・クエリ・利用者情報を拒否する。エンジンの既定URLはどれもこの形に収まる。
- `SpeechError`と`CancelToken`は`speechcpp_tts.py`にある。`CancelToken.register()`に閉じる処理を登録すれば、進行中のHTTP要求を割り込みで閉じられる。
- `VoiceSettings`は`japanese_*`と`multilingual_*`の2つのロールを持つ。`from_dict()`は欠けた項目を既定値で補うので、項目を足しても既存の設定は読める。

### 違っていた前提

実装では次のとおりにする。

- 文分割はまだない。`tts_scheduler.py`は1件の発話を丸ごと`synthesize_stream()`に渡す。speech.cppはPCMを少しずつ返すので、分割がなくても最初の音が早い。エンジンは文ごとにWAVを丸ごと返すので、新しいバックエンドの`synthesize_stream()`の中で文に分け、1文ずつ合成して順に`AudioFrame`を返す。スケジューラは変えない。
- リサンプルは要らない。`AudioFrame`（`models/voice_events.py`）は8000〜192000 Hz、モノラルかステレオの16ビットPCMを受け付け、出力側で合わせる。バックエンドはWAVを解いて16ビットPCMにするだけでよい。16ビット以外のWAVは`SpeechError`で断る。
- スケジューラの1か所は変える。今は`request_for()`がURLと声を返し、`provider_factory(url)`が必ず`SpeechCppTTS`を作る。エンジンの種類も渡して、種類に合うクライアントを作るようにする。キューと再生の仕組みは変えない。

### そのほかに決めること

- 既存の`japanese_server`（`external` | `bundled`）は、speech.cppの接続先の選び方である。`japanese_engine`がspeech.cpp以外のときは、この値と`japanese_url`を使わない。エンジンのURLはエンジンごとの項目に持つ。
- 0.3.0で項目を足すと、0.2.0は知らない項目を含む読み上げの設定を不正とみなし、既定に戻す。0.3.0から0.2.0へ戻した人は、読み上げの設定をやり直すことになる。更新するときの注意に書く。
- 設定画面から各エンジンの公式サイトを開くには、URLを開ける先の一覧（`src-tauri/capabilities/vrct_capability.json`、第2回セキュリティ監査 SEC-02）に公式サイトを足す。
- 発話には始まるまでの期限がある（`CancelToken`の`start_deadline`）。長い文をCPUで合成すると、最初の文が期限に間に合わないことがある。文に分けたうえで、実機で測って確かめる。

## 12. 未決事項への提案

利用者が別に決めない限り、次で実装する。

1. 並び順と未接続の表示: AIボイス（speech.cpp、既定）、VOICEVOX、COEIROINK、AivisSpeech、SHAREVOXの順にする。選んだエンジンに接続できないときは、その欄に「未接続」と、エンジンを起動してから「再確認」を押す案内を出す。自動で何度も問い合わせることはしない。
2. 話者の保存: style id（COEIROINKはspeakerUuidとstyleId）と一緒に、話者名とスタイル名も保存する。読み上げのときにidが見つからないか、名前が変わっていれば、名前で探し直す。それでも見つからなければ、安全なコードで失敗し、話者を選び直すよう案内する。
3. AivisSpeech: 0.3.0に入れる。VOICEVOX互換のクライアントを使い、AudioQueryは書き換えずにそのまま渡す（5.2）。
4. 文より細かい分割: まず文（`。`、`！`、`？`、`!`、`?`、改行）で分ける。実機で測って遅すぎれば、読点での分割を足す。

実機での確認にはこのPCにエンジンを入れる必要がある。エンジンと音声ライブラリのダウンロードになるので、入れる前に利用者の同意を得る。
