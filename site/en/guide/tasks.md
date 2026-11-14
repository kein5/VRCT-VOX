# Find what you want to do

Each section names what you need and the main steps. The full steps are on the linked pages.

[How voice and text flow](./how-it-works) shows how voice and text move through the app, which makes the rest easier to follow.

[[toc]]

## Send translated text to the VRChat chatbox

You need: VRChat's OSC, and a translation model or API

1. In VRChat's Action Menu, set "Options" → "OSC" to "Enabled".
2. In "Language Settings" on the left of the main screen, choose your language and theirs.
3. Turn on "Translation" and send from the box at the bottom.

See [First setup](./first-setup) and [Translation](../features/translation).

## Send what you say as text

You need: a speech recognition (ASR) model

1. Under Settings → "Device", choose the microphone that picks up your voice.
2. Under Settings → "Speech recognition (ASR)", download a recognition model.
3. Turn on "Mic input" on the main screen and speak. With "Translation" on too, the translation is sent with it.

See [Speech recognition (ASR) and realtime captions](../features/transcription).

## See the other players' voices as captions

You need: a speech recognition (ASR) model, and SteamVR to see them in VR

1. Under Settings → "Speech recognition (ASR)", in "Game audio captions", choose an output device that plays only VRChat's sound.
2. Turn on "Listening" on the main screen. Captions appear in the main screen's log.
3. To lay them over the screen, turn on the desktop caption overlay; to see them in VR, turn on the caption overlay.

See [Speech recognition (ASR) and realtime captions](../features/transcription) and [VR and overlay](../features/vr).

## Read and translate the other players' chatbox

You need: the chat reading (OCR) models

1. Under Settings → "Chat reading (OCR)", download the recognition models.
2. Start VRChat.
3. Turn on "Chat reading (OCR)" on the main screen.

See [Chat reading (OCR)](../features/chat-reading).

## Say your translated text aloud

You need: a text to speech (TTS) model and a virtual microphone

1. Under Settings → "Text to speech (TTS)", download a model.
2. Choose a virtual microphone under "Output device", and choose the same one as your microphone in VRChat. On Linux use the managed virtual microphone; on Windows, a virtual cable you install separately.
3. In "Chat voice", choose whether to speak the original or the translation.
4. Turn on "Text to speech (TTS)" on the main screen.

See [Text to speech (TTS)](../features/tts) and [Linux audio route](./linux-audio).

## Change your voice for others to hear

You need: the RVC runtime and a model, an NVIDIA GPU, and a virtual microphone

1. Under Settings → "Voice changer (RVC)", download the runtime and a model, or point to files you have.
2. Set up a virtual microphone that carries the changed voice to VRChat.
3. Turn on "Voice changer (RVC)" on the main screen.

See [Voice changer (RVC, Seed-VC)](../features/voice-conversion).

## Say the translation of your words in your changed voice

You need: both text to speech (TTS) and the voice changer (RVC) set up

1. Do the two sections above (say your translated text aloud, change your voice).
2. Under Settings → "Text to speech (TTS)", set "Realtime microphone speech" to "Speak final translations" and "Speak through voice conversion" to "On".
3. On the main screen, turn on "Translation", "Mic input", "Text to speech (TTS)" and "Voice changer (RVC)", and speak. Your microphone is captioned by realtime captions.

See [Voice changer (RVC, Seed-VC)](../features/voice-conversion).

## Show captions in a stream (OBS)

You need: OBS

1. Under Settings → "Advanced", turn on "Enable OBS Browser Source".
2. Press "OBS URL (click to copy)" to copy the URL.
3. In OBS, add a "Browser" source and paste the URL.

See [OBS and WebSocket](../features/integrations).

## Use models you trained or bought

You can use models you trained, models published elsewhere, and models you bought. Which features can use them differs.

See [Use your own models](./custom-models).

## Check where your voice and text go right now

Press "Inputs and outputs" in the bar at the top of the main screen. A graph shows where your voice and chat go, with how long each step took.

See [Inputs and outputs](../features/io-flow).

## Stop speech or voice at once

- "Stop speech" stops the speech playing now and the speech waiting.
- "Mute" stops everything sent to the virtual microphone.

Both are always at the top of the main screen, and both can have hotkeys.

See [Text to speech (TTS)](../features/tts) and [Quick Chat and hotkeys](../features/quick-chat).
