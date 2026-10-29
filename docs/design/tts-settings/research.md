# 音声・TTSのUI調査（imozuru）

2026-10-29。設計とモックアップの根拠。製品のUI変更・音声性能の検証結果ではない。

最初に見るもの:
- [トップ画面のモック](main.html) / [画像](main-on.png)
- [専用設定ページのモック](mockup.html) / [生成設定の画像](generation.png)
- [設計案](../../superpowers/specs/2026-10-29-tts-settings-ui-design.md) / [実装計画](../../superpowers/plans/2026-10-29-tts-settings-ui.md)
- [詳細レポート](../../../tmp/voice-resume/research/tts-settings-ui/digest.html) / [原文の抜き書き](../../../tmp/voice-resume/research/tts-settings-ui/report.html)

後ろ2つはローカルの研究フォルダー。公開物には含めず、公開原典は以下から直接参照できる。

## 調べたことと採用する判断

| 論点 | 確認した根拠 | このアプリへの提案 |
|---|---|---|
| ボタンと入力が似ている | TTS独自CSSが同じルールを指定。デジタル庁はボタンの重要度に応じたスタイルを示す | 既存の行・色を使い、入力は暗い面、操作は塗り＋動詞ラベル |
| 保存の見落とし | GOV.UKは主な操作を強調し、主操作を増やしすぎない方針 | formごとに保存対象を明示。未保存を文章でも表示 |
| 長い設定 | GOV.UK Detailsは一部の利用者が必要な情報向けで、主要な情報を隠す用途は避ける | 普段の読み上げ/出力を先に置く。未設定・失敗時の準備手順は開いて見せる |
| 保存/起動の状態 | W3CのStatus Messagesはフォーカスを奪わない通知を説明 | 保存中、確認済み、失敗、停止中を区別する |
| 独立ページとトップスイッチ | ユーザーが明示希望。W3C APGはswitchのlabelを状態で変えないとする | メニュー「音声・TTS」、トップにTTS switchと状況/設定リンク |
| TTSだけのOFF | 既存muteは管理ルート全体、schedulerの_mutedもルート所有 | 独立tts_enabledを追加し、原音・VC・OSCを変更しない |
| seed/Instruction | 固定speech.cppのAPI/ADRと実機モデル宣言 | 日本語/多言語別に保存し、対応モデルへJSON項目として送る |

根拠は配置案の正しさを自動で保証するものではない。W3Cの一貫した識別は、全画面のピクセルや
装飾を同一にする要求ではない。既存の色・行配置を使う判断は、このユーザー要望とコードに基づく。

## 原典

1. [デジタル庁：ボタンの使い方](https://design.digital.go.jp/dads/components/button/usage/)
   — 重要度、ボタンの役割、配置。保存原文`dads-button.md:53`以降。
2. [GOV.UK：Button](https://design-system.service.gov.uk/components/button/)
   — 操作を記したラベル、主操作の強調。`govuk-button.md`のDefault buttons。
3. [GOV.UK：Details](https://design-system.service.gov.uk/components/details/)
   — Buttonの関連部品リンクから追跡。`govuk-details.md:45,49`。
4. [W3C：一貫した識別](https://www.w3.org/WAI/WCAG22/Understanding/consistent-identification.html)
   と[状態メッセージ](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)
   — `w3c-identification.md:24`, `w3c-status.md:23`。
5. [W3C：Switch Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/switch/)
   — label、Space、role、checked。`w3c-switch.md:22,34`。
6. [W3C：Target Size Minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
   — 24 CSS pxと例外。`w3c-target.md:23`以降。
7. [speech.cpp固定版：Server API](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/docs/server.md)
   — `/v1/models`、`seed`、`instructions`、`X-Speech-Seed`。
8. [speech.cpp固定版：Instructionのモデル差](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/docs/adr/the-option-instructions-carries-qwen3-tts-instruct-and-irodori-tts-caption.md)
   — Irodori caption encoderと、Qwen3-TTS0.6B非対応。

資料による違いも確認した。GOV.UKは主要操作の左寄せ、デジタル庁はデスクトップで進行操作の右寄せを
基本とする。このアプリでは右側に操作を置く既存の設定行へ合わせる。どちらかを普遍的な法則とは扱わない。

同梱サーバーは起動引数でseedを指定しておらず、現在のHTTP clientもseedを送らない。
外部サーバーは自身にseed既定値がありうるため、省略時のUIは「ランダム（サーバー既定）」と説明する。
現在のIrodori MFからGETした能力情報はseed0〜9007199254740991、instructions対応。
この読み取りで新規モデル取得・音声合成・録音は行っていない。

## 調査を区切った理由と未検証

日本語のボタン/フォーム資料と英語のcomponent/accessibility資料の2方向から探索し、Button→Details、
speech API→Instruction ADR→実機モデル宣言を追った。各論点に原典が付き、必須準備を隠さないという
制約も得られたため「論点充足」で区切った。取得失敗・有料で未到達の主要資料はない。
過去のProviderエラーを踏まえて本セッション内で調査し、AITの子セッションは起動していない。

モックは保存表示、別formの保存、CPUへの再試行表示、停止、TTSスイッチのSpace操作を確認した。
12枚の表示を生成し、横はみ出しとJavaScript例外を検査した。[記録](mockup-checks.json)
モックの初回検査でSVGとボタンのID重複を見つけ、接頭辞を分けて修正した。

製品バックエンドとの接続、実際のOFF後の無音、固定seedのPCM一致、Instructionの聴感/遅延、
スクリーンリーダーと全拡大率での適合、Windows実機は未検証。モックの成功をこれらの合格として扱わない。

モックの多言語・ASR・直接VCの詳細は配置の見本で、一部の入力を省略している。
実装時は既存項目と保存契約を維持する。例文やseed42はデモ値で、製品の既定値にはしない。

## 追加確認：HTML単体プレビューの表示崩れ

ユーザーの報告後、トップ画面のHTMLだけを別フォルダーにコピーすると、外部のmockup.cssが
ERR_FILE_NOT_FOUNDになり、背景やアイコン寸法が崩れることを再現した。
前回の検証は同じフォルダーにCSSが存在する場合だけで、この渡し方を検査できていなかった。
ユーザーの実際のプレビュー環境自体は未確認。

CSSをHTML内へ含め、不要になった外部CSSを削除した。
構造の原典は[HTML Standardのstyle要素](https://html.spec.whatwg.org/multipage/semantics.html#the-style-element)。
トップ画面の状態選択欄が実際のTTSスイッチと食い違う点も修正した。
各HTMLの単独表示2サイズと、OFFのまま専用設定へ移動して戻る操作が成功し、
JavaScript例外・リソース取得失敗は0件。[検証記録](standalone-checks.json)
アプリ本体・音声出力への変更はない。
