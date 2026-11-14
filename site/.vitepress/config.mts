import { defineConfig, type DefaultTheme } from 'vitepress'
import { tokenize } from './searchTokenize.mjs'
import { slugify } from './slugify.mjs'

const repo = 'https://github.com/kein5/VRCT-VOX'
const site = 'https://kein5.github.io/VRCT-VOX/'

// hreflang pairs: /ja/<page> and /en/<page> share a path; / is the language picker.
function alternates(relativePath: string): [string, Record<string, string>][] {
  const page = relativePath.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '')
  const match = page.match(/^(ja|en)\/(.*)$/)
  if (page !== '' && !match) return []
  const rest = match ? match[2] : ''
  const link = (lang: string, href: string) => ['link', { rel: 'alternate', hreflang: lang, href }] as [string, Record<string, string>]
  return [link('ja', `${site}ja/${rest}`), link('en', `${site}en/${rest}`), link('x-default', site)]
}

// Pages are grouped by what a reader comes to do: start, find a task, look a feature up, fix
// something. The feature pages keep the order of the app's settings menu.
function sidebarJa(): DefaultTheme.SidebarItem[] {
  return [
    {
      text: 'はじめに',
      items: [
        { text: 'VRCT-VOXとは', link: '/ja/guide/introduction' },
        { text: 'インストール', link: '/ja/guide/install' },
        { text: '動作環境と推奨スペック', link: '/ja/guide/requirements' },
        { text: '最初の設定', link: '/ja/guide/first-setup' },
        { text: '声と文字の流れ', link: '/ja/guide/how-it-works' },
      ],
    },
    {
      text: 'やりたいこと',
      items: [
        { text: 'やりたいことから探す', link: '/ja/guide/tasks' },
        { text: '自分のモデルを使う', link: '/ja/guide/custom-models' },
      ],
    },
    {
      text: '機能の詳細',
      items: [
        { text: '翻訳', link: '/ja/features/translation' },
        { text: '音声認識（ASR）とリアルタイム字幕', link: '/ja/features/transcription' },
        { text: 'テキスト読み上げ（TTS）', link: '/ja/features/tts' },
        { text: 'ボイスチェンジャー（RVC・Seed-VC）', link: '/ja/features/voice-conversion' },
        { text: 'チャット読み取り（OCR）', link: '/ja/features/chat-reading' },
        { text: 'VRとオーバーレイ', link: '/ja/features/vr' },
        { text: '入力と出力', link: '/ja/features/io-flow' },
        { text: '入力の小窓とホットキー', link: '/ja/features/quick-chat' },
        { text: 'OBSとWebSocket', link: '/ja/features/integrations' },
      ],
    },
    {
      text: '設定と運用',
      items: [
        { text: 'モデルの取得', link: '/ja/guide/models' },
        { text: 'Linuxの音声経路', link: '/ja/guide/linux-audio' },
        { text: '困ったとき', link: '/ja/guide/troubleshooting' },
        { text: 'プライバシー', link: '/ja/guide/privacy' },
        { text: 'ライセンスと謝辞', link: '/ja/guide/license' },
      ],
    },
  ]
}

function sidebarEn(): DefaultTheme.SidebarItem[] {
  return [
    {
      text: 'Getting started',
      items: [
        { text: 'What is VRCT-VOX', link: '/en/guide/introduction' },
        { text: 'Install', link: '/en/guide/install' },
        { text: 'System requirements', link: '/en/guide/requirements' },
        { text: 'First setup', link: '/en/guide/first-setup' },
        { text: 'How voice and text flow', link: '/en/guide/how-it-works' },
      ],
    },
    {
      text: 'What you want to do',
      items: [
        { text: 'Find what you want to do', link: '/en/guide/tasks' },
        { text: 'Use your own models', link: '/en/guide/custom-models' },
      ],
    },
    {
      text: 'Features',
      items: [
        { text: 'Translation', link: '/en/features/translation' },
        { text: 'Speech recognition (ASR) and realtime captions', link: '/en/features/transcription' },
        { text: 'Text to speech (TTS)', link: '/en/features/tts' },
        { text: 'Voice changer (RVC, Seed-VC)', link: '/en/features/voice-conversion' },
        { text: 'Chat reading (OCR)', link: '/en/features/chat-reading' },
        { text: 'VR and overlay', link: '/en/features/vr' },
        { text: 'Inputs and outputs', link: '/en/features/io-flow' },
        { text: 'Quick Chat and hotkeys', link: '/en/features/quick-chat' },
        { text: 'OBS and WebSocket', link: '/en/features/integrations' },
      ],
    },
    {
      text: 'Setup and operation',
      items: [
        { text: 'Model downloads', link: '/en/guide/models' },
        { text: 'Linux audio route', link: '/en/guide/linux-audio' },
        { text: 'Troubleshooting', link: '/en/guide/troubleshooting' },
        { text: 'Privacy', link: '/en/guide/privacy' },
        { text: 'License and credits', link: '/en/guide/license' },
      ],
    },
  ]
}

export default defineConfig({
  base: '/VRCT-VOX/',
  title: 'VRCT-VOX',
  // Only the / language picker uses this; each locale sets its own lang.
  lang: 'en',
  cleanUrls: true,
  lastUpdated: false,
  // Dark Studio (DESIGN.md) only; no light theme to keep in sync.
  appearance: 'force-dark',
  head: [['meta', { name: 'theme-color', content: '#111b2c' }]],
  transformHead: ({ pageData }) => alternates(pageData.relativePath),
  markdown: {
    image: { lazyLoading: true },
    // Japanese ids stay composed, so links to headings with voiced marks find them (slugify.mjs).
    anchor: { slugify },
    toc: { slugify },
    config(md) {
      // Every picture in a page is a screenshot: it can take focus and opens larger (theme/index.ts).
      const image = md.renderer.rules.image!
      md.renderer.rules.image = (tokens, index, options, env, self) => {
        const token = tokens[index]
        token.attrSet('data-zoom', '')
        token.attrSet('tabindex', '0')
        token.attrSet('role', 'button')
        token.attrSet('aria-haspopup', 'dialog')
        return image(tokens, index, options, env, self)
      }
    },
  },
  locales: {
    // Both languages live under their own path; / picks one (see index.md).
    ja: {
      label: '日本語',
      lang: 'ja',
      link: '/ja/',
      description: 'VRChat向けの翻訳・音声認識・読み上げ・声の変換・チャット読み取りアプリVRCT-VOXの使い方',
      themeConfig: {
        nav: [
          { text: 'ガイド', link: '/ja/guide/introduction' },
          { text: 'ダウンロード', link: `${repo}/releases` },
        ],
        sidebar: sidebarJa(),
        outline: { label: 'このページの内容' },
        docFooter: { prev: '前のページ', next: '次のページ' },
        returnToTopLabel: 'ページの先頭へ',
        sidebarMenuLabel: 'メニュー',
        langMenuLabel: '言語',
        notFound: {
          title: 'ページが見つかりません',
          quote: 'URLを確かめるか、トップページから探してください。',
          linkText: 'トップページへ',
        },
        footer: {
          message: 'VRCT-VOXはVRCTの非公式な派生版です。VRChat Inc.とは関係ありません。',
          copyright: 'MIT License · 元のVRCTの著作権表示を保持しています',
        },
      },
    },
    en: {
      label: 'English',
      lang: 'en',
      link: '/en/',
      description: 'How to use VRCT-VOX, a translation, speech recognition, text-to-speech, voice conversion and chat-reading app for VRChat',
      themeConfig: {
        nav: [
          { text: 'Guide', link: '/en/guide/introduction' },
          { text: 'Download', link: `${repo}/releases` },
        ],
        sidebar: sidebarEn(),
        footer: {
          message: 'VRCT-VOX is an unofficial derivative of VRCT. It is not affiliated with VRChat Inc.',
          copyright: 'MIT License · The original VRCT copyright notice is retained',
        },
      },
    },
  },
  themeConfig: {
    socialLinks: [{ icon: 'github', link: repo }],
    search: {
      provider: 'local',
      options: {
        // The same words when the index is built and when a query is typed (searchTokenize.mjs).
        miniSearch: { options: { tokenize } },
        locales: {
          ja: {
            translations: {
              button: { buttonText: '検索', buttonAriaLabel: '検索' },
              modal: {
                noResultsText: '見つかりませんでした',
                resetButtonTitle: '検索語を消す',
                footer: { selectText: '選ぶ', navigateText: '移動', closeText: '閉じる' },
              },
            },
          },
        },
      },
    },
  },
})
