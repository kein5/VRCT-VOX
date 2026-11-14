// The words inside the animations. The Japanese video shows a Japanese speaker talking with
// an English speaker; the English video shows the same scene from the other side.
export type Lang = 'ja' | 'en'
type Words = Record<Lang, string>

const w = (ja: string, en: string): Words => ({ ja, en })

export const copy = {
  laneMine: w('自分から相手へ', 'You to others'),
  laneTheirs: w('相手から自分へ', 'Others to you'),
  vrchat: w('VRChat', 'VRChat'),
  translate: {
    box: w('入力欄', 'Message box'),
    input: w('はじめまして、よろしくね', 'Nice to meet you'),
    node: w('翻訳', 'Translation'),
    output: w('Nice to meet you', 'はじめまして'),
    place: w('チャットボックス', 'Chatbox'),
  },
  captions: {
    node: w('音声認識', 'Speech recognition'),
    heard: w('Where are you from?', 'どこから来たの？'),
    translated: w('どこから来たの？', 'Where are you from?'),
    place: w('字幕', 'Captions'),
  },
  tts: {
    box: w('送った文', 'Sent text'),
    input: w('ようこそ', 'Welcome'),
    node: w('読み上げ', 'Text to speech'),
    mic: w('仮想マイク', 'Virtual mic'),
  },
  voice: {
    mic: w('マイク', 'Microphone'),
    node: w('ボイスチェンジャー', 'Voice changer'),
  },
  chat: {
    screen: w('VRChatの画面', 'VRChat screen'),
    seen: w('Where should we go next?', '次はどこに行く？'),
    node: w('チャット読み取り', 'Chat reading'),
    received: w('受信', 'Received'),
    translated: w('次はどこに行く？', 'Where should we go next?'),
    log: w('ログ', 'Log'),
  },
}

export const say = (words: Words, lang: Lang) => words[lang]
