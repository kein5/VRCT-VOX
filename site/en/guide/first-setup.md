# First setup

This page sets up translating text and sending it to the VRChat chatbox. Add speech or captions afterwards with the feature guides.

![The VRCT-VOX main screen with Translation on and a conversation in the log](/screenshots/en/main.webp)

The switches and languages are on the left, the conversation log is on the right, and the message box is at the bottom.

## 1. Choose whether to send usage data

On the first start, a screen asks whether to send usage data. Choose "Send", "Don't send" or "Decide later". The app works the same whichever you choose. [Privacy](./privacy) lists what is sent.

## 2. Turn on OSC in VRChat

VRCT-VOX sends text to the VRChat chatbox over OSC. In VRChat, open the Action Menu, go to "Options" → "OSC" and choose "Enabled".

"Quick settings" at the top right of the main screen says whether a VRChat with OSC enabled was found on this PC. The top of Settings → "VRChat" says the same.

!["Quick settings" open, saying that VRChat was found](/screenshots/en/quick-settings.webp)

By default VRCT-VOX sends to `127.0.0.1` on port `9000`, which is also VRChat's default, so you usually don't need to change it. To change it, use "OSC" under Settings → "VRChat".

## 3. Choose your languages

In "Language Settings" on the left of the main screen, choose:

- **Your Language**: the language you speak or type.
- **Target Language**: the language to translate into. You can choose up to three.

## 4. Turn on Translation and send

Turn on "Translation" on the left of the main screen. If the translation model has not been downloaded, a review of what will be downloaded opens. Check the provider, license and size and agree; the download starts, and Translation turns on when it finishes.

Type in the box at the bottom and send. The original and its translation appear in the log, and the same text appears in the VRChat chatbox.

::: tip Without a local model
Choose an external translation API under Settings → "Translation". See [Translation](../features/translation).
:::

Models you have not downloaded yet are also listed under "Before you start" on the main screen while the conversation is empty.

## 5. Choose your microphone and speaker

Do this before you use a voice feature (captions, text to speech, the voice changer). Open the settings with the gear at the bottom left of the main screen, then open "Device".

- **Mic**: the microphone that picks up your voice. On Linux it lists PipeWire inputs.
- **Speaker**: the output used to listen to other players.

"Auto Select" uses the system default device.

## Next

- For everything else it can do: [Find what you want to do](./tasks)
- To speak your translations: [Text to speech (TTS)](../features/tts)
- To turn speech into text: [Speech recognition (ASR) and realtime captions](../features/transcription)
- To read other people's chatboxes: [Chat reading (OCR)](../features/chat-reading)
