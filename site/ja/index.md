---
layout: home
hero:
  name: VRCT-VOX
  # Each span stays on one line where it fits (custom.css), so the headline breaks between them.
  text: <span class="nb">VRChatの会話を</span><span class="nb">翻訳・字幕・読み上げで支える</span>
  tagline: 翻訳、音声認識（ASR）、テキスト読み上げ（TTS）、ボイスチェンジャー（RVC）、チャット読み取り（OCR）をまとめたデスクトップアプリです。VRCTの非公式な派生版です。
  actions:
    - theme: brand
      text: はじめる
      link: /ja/guide/introduction
    - theme: alt
      text: やりたいことから探す
      link: /ja/guide/tasks
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
  - title: 字幕にする
    details: 自分のマイクとほかのプレイヤーの声を、同梱の音声認識（ASR）サーバーで文字にします。
    link: /ja/features/transcription
  - title: 声で届ける
    details: 送った文章や翻訳をテキスト読み上げ（TTS）で声にして、仮想マイクへ流します。文字の送信とは別にオンとオフを切り替えられます。
    link: /ja/features/tts
  - title: 声を変える
    details: ボイスチェンジャー（RVC・Seed-VC）でマイクの声を変えて届けます。自分で用意したモデルも使えます。
    link: /ja/features/voice-conversion
  - title: 相手のチャットを読む
    details: チャット読み取り（OCR）で、画面に出た相手のチャットボックスの文字を読み取って訳します。
    link: /ja/features/chat-reading
  - title: 同意してから取得する
    details: モデルは同梱していません。提供元、ライセンス、容量を確かめて同意したものだけを取得します。
    link: /ja/guide/models
---
