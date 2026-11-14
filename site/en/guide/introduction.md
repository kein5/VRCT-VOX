# What is VRCT-VOX

VRCT-VOX is a desktop app that helps you talk in VRChat. It combines translation, speech recognition (ASR), text to speech (TTS), a voice changer (RVC) and chat reading (OCR) in one app.

It is derived from [VRCT](https://github.com/misyaguziya/VRCT) and developed by [kein5](https://github.com/kein5).

::: warning Not an official VRCT release
VRCT-VOX is not endorsed by the VRCT authors or VRChat. Send questions and bug reports about VRCT-VOX to the [VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues), not to the VRCT authors.
:::

## What VRCT-VOX adds to VRCT

### Speak your translations

Reads your text or its translation with [speech.cpp](https://github.com/nyosegawa/speech.cpp) into VRChat's microphone, through a virtual microphone. Japanese uses Irodori; other languages use Qwen3-TTS. Voice and chatbox text are configured separately.

See [Text to speech (TTS)](../features/tts).

### Hear yourself

Optionally plays the speech that goes to VRChat on your own speakers or headphones too.

See [Hear it yourself](../features/tts#hear-it-yourself) in Text to speech.

### Voice changer

Changes your microphone's voice with an RVC or Seed-VC runtime. The settings can fetch the runtime for you after you check its license and size and agree.

See [Voice changer (RVC, Seed-VC)](../features/voice-conversion).

### Realtime captions

Turns what you say and other players' voices into text, with the speech recognition server that comes with the app.

See [Speech recognition (ASR) and realtime captions](../features/transcription).

### Chat reading

Reads the text of chatboxes shown on the VRChat screen.

See [Chat reading (OCR)](../features/chat-reading).

### Model downloads

Models are downloaded only after you check their license and size and agree.

See [Model downloads](./models).

### Linux support

Global shortcuts on Wayland, a PipeWire virtual microphone and Japanese input methods (fcitx/Mozc, ibus). The VR UI, chat reading from a shared native Wayland window, and pasting in Voice Typing Mode work too.

For the virtual microphone, see [Linux audio route](./linux-audio).

## Versions and tested environments

The first stable version is 0.1.0. Versions count from 0.1.0, separately from VRCT (3.x). Betas are published from the `develop` branch and stable releases from `main`.

The Linux build has been tested with real models on CachyOS (KDE Plasma, Wayland). The Windows build has been tested with real models on a Windows 11 PC.

Next, see [Install](./install). To see what it can do first, read [Find what you want to do](./tasks); for how voice and text move through it, read [How voice and text flow](./how-it-works).
