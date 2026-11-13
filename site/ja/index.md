---
layout: home
hero:
  name: VRCT-VOX
  # Each span stays on one line where it fits (custom.css), so the headline breaks between them.
  text: <span class="nb">VRChatの会話を</span><span class="nb">翻訳・字幕・読み上げで支える</span>
  tagline: 翻訳、音声認識、読み上げ（TTS）、声の変換、チャット読み取りをまとめたデスクトップアプリです。VRCTの非公式な派生版です。
  actions:
    - theme: brand
      text: はじめる
      link: /ja/guide/introduction
    - theme: alt
      text: ダウンロード
      link: https://github.com/kein5/VRCT-VOX/releases
shot:
  src: /screenshots/ja/main.webp
  alt: VRCT-VOXのメイン画面。日本語の発言に英語の訳が、相手の英語の発言に日本語の訳が付いている
features:
  - title: 翻訳して送る
    details: 入力した文章を翻訳して、VRChatのチャットボックスへ送ります。ローカルの翻訳モデルと外部の翻訳APIを選べます。
    link: /ja/features/translation
  - title: 読み上げる
    details: 送った文章や翻訳を、同梱のspeech.cppで読み上げて仮想マイクへ流します。文字の送信とは別にオンとオフを切り替えられます。
    link: /ja/features/tts
  - title: 字幕にする
    details: 自分のマイクとほかのプレイヤーの声を、同梱の音声認識サーバーで文字にします。
    link: /ja/features/transcription
  - title: 同意してから取得する
    details: モデルは同梱していません。提供元・ライセンス・容量を確かめて同意したものだけを取得します。
    link: /ja/guide/models
---
