// The route strip at the top of a feature page (RouteStrip.vue): where voice and text go
// through the part this page sets up. A page names its route in its front matter, e.g.
// `route: tts`. The lanes and colours follow the flow diagram on how-it-works.

export interface Words {
  ja: string
  en: string
}

export interface Lane {
  side: 'mine' | 'theirs'
  nodes: (Words & { here?: boolean })[]
}

export const laneNames: Record<Lane['side'], Words> = {
  mine: { ja: '自分から相手へ', en: 'You to others' },
  theirs: { ja: '相手から自分へ', en: 'Others to you' },
}

const node = (ja: string, en: string, here = false) => ({ ja, en, here })

export const routes: Record<string, Lane[]> = {
  translation: [
    { side: 'mine', nodes: [node('自分の文・声', 'Your text or voice'), node('翻訳', 'Translation', true), node('チャットボックス', 'Chatbox')] },
    { side: 'theirs', nodes: [node('相手の声・チャット', "Others' voice or chat"), node('翻訳', 'Translation', true), node('ログ・字幕', 'Log and captions')] },
  ],
  transcription: [
    { side: 'mine', nodes: [node('自分の声', 'Your voice'), node('音声認識', 'Speech recognition', true), node('翻訳・送信', 'Translate and send')] },
    { side: 'theirs', nodes: [node('相手の声', "Others' voice"), node('音声認識', 'Speech recognition', true), node('ログ・字幕', 'Log and captions')] },
  ],
  tts: [
    { side: 'mine', nodes: [node('文・訳文', 'Text or translation'), node('読み上げ', 'Text to speech', true), node('仮想マイク', 'Virtual microphone'), node('VRChat', 'VRChat')] },
  ],
  'voice-conversion': [
    { side: 'mine', nodes: [node('マイク', 'Microphone'), node('ボイスチェンジャー', 'Voice changer', true), node('仮想マイク', 'Virtual microphone'), node('VRChat', 'VRChat')] },
  ],
  'chat-reading': [
    { side: 'theirs', nodes: [node('相手のチャットボックス', "Others' chatbox"), node('チャット読み取り', 'Chat reading', true), node('翻訳', 'Translation'), node('ログ・字幕', 'Log and captions')] },
  ],
  'windows-audio': [
    { side: 'mine', nodes: [node('読み上げ・変えた声', 'Speech or changed voice'), node('仮想ケーブル', 'Virtual cable', true), node('VRChatのマイク', "VRChat's microphone")] },
  ],
  'linux-audio': [
    { side: 'mine', nodes: [node('読み上げ・変えた声', 'Speech or changed voice'), node('仮想マイク', 'Virtual microphone', true), node('VRChatのマイク', "VRChat's microphone")] },
  ],
}
