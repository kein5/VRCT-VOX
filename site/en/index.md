---
layout: home
hero:
  name: VRCT-VOX
  text: Translation, captions and speech for your VRChat conversations
  tagline: One desktop app for translation, captions, speech, a voice changer and chat reading. It is an unofficial derivative of VRCT.
  actions:
    - theme: brand
      text: Install
      link: /en/guide/install
    - theme: alt
      text: Find what you want to do
      link: /en/guide/tasks
shot:
  src: /screenshots/en/main.webp
  alt: The VRCT-VOX main window. A message sent in Japanese has its English translation, and the other player's English reply has its Japanese translation
# Each feature beside a short loop of what it does (theme/HomeShowcase.vue). The id names the
# loop under public/motion/en/, rendered by site/motion.
showcase:
  - id: translate
    title: Translate and send
    details: Translates what you type and sends it to the VRChat chatbox. Choose local translation models or external translation APIs.
    link: /en/features/translation
    linkText: Using translation
  - id: captions
    title: Captions
    details: Turns what you say and other players' voices into text, with the speech recognition (ASR) server that comes with the app.
    link: /en/features/transcription
    linkText: Using speech recognition (ASR) and realtime captions
  - id: tts
    title: Speak it
    details: Reads your text or its translation aloud with text to speech (TTS), into VRChat's microphone. You can turn speech on and off separately from sending text to the chatbox.
    link: /en/features/tts
    linkText: Using text to speech (TTS)
  - id: voice-changer
    title: Change your voice
    details: Changes your microphone's voice with the voice changer (RVC, Seed-VC) and gets it to VRChat. Models you bring yourself work too.
    link: /en/features/voice-conversion
    linkText: Using the voice changer (RVC, Seed-VC)
  - id: chat-reading
    title: Read their chat
    details: Chat reading (OCR) reads the other players' chatbox text on your screen and translates it.
    link: /en/features/chat-reading
    linkText: Using chat reading (OCR)
showcaseNote:
  text: The models the features use do not come with the app. You download only what you agree to, after checking its provider, license and size.
  link: /en/guide/models
  linkText: Model downloads
---
