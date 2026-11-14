---
layout: home
hero:
  name: VRCT-VOX
  # Each span stays on one line where it fits (custom.css), so the headline breaks between them.
  text: <span class="nb">VRChatの会話を</span><span class="nb">翻訳・字幕・読み上げで支える</span>
  tagline: 翻訳、字幕、読み上げ、声の変換、チャットの読み取りを1つにまとめたデスクトップアプリです。VRCTの非公式な派生版です。
  actions:
    - theme: brand
      text: インストール
      link: /ja/guide/install
    - theme: alt
      text: やりたいことから探す
      link: /ja/guide/tasks
shot:
  src: /screenshots/ja/main.webp
  alt: VRCT-VOXのメイン画面。日本語の発言に英語の訳が、相手の英語の発言に日本語の訳が付いている
# Each feature beside a short loop of what it does (theme/HomeShowcase.vue). The id names the
# loop under public/motion/ja/, rendered by site/motion.
showcase:
  - id: translate
    title: 翻訳して送る
    details: 入力した文章を翻訳して、VRChatのチャットボックスへ送ります。ローカルの翻訳モデルと外部の翻訳APIを選べます。
    link: /ja/features/translation
    linkText: 翻訳の使い方
  - id: captions
    title: 字幕にする
    details: 自分のマイクとほかのプレイヤーの声を、同梱の音声認識（ASR）サーバーで文字にします。
    link: /ja/features/transcription
    linkText: 音声認識（ASR）とリアルタイム字幕の使い方
  - id: tts
    title: 声で届ける
    details: 送った文章や翻訳をテキスト読み上げ（TTS）で声にして、仮想マイクを通してVRChatのマイクに流します。チャットボックスへの送信とは別に、読み上げだけをオンやオフにできます。
    link: /ja/features/tts
    linkText: テキスト読み上げ（TTS）の使い方
  - id: voice-changer
    title: 声を変える
    details: ボイスチェンジャー（RVC・Seed-VC）でマイクの声を変えて、VRChatに届けます。自分で用意したモデルも使えます。
    link: /ja/features/voice-conversion
    linkText: ボイスチェンジャー（RVC・Seed-VC）の使い方
  - id: chat-reading
    title: 相手のチャットを読む
    details: チャット読み取り（OCR）で、画面に出た相手のチャットボックスの文字を読み取って訳します。
    link: /ja/features/chat-reading
    linkText: チャット読み取り（OCR）の使い方
showcaseNote:
  text: 機能に使うモデルはアプリに入っていません。提供元、ライセンス、容量を見て同意したものだけをダウンロードします。
  link: /ja/guide/models
  linkText: モデルの取得
---
