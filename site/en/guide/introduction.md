# What is VRCT-VOX

VRCT-VOX is a desktop app that helps you talk in VRChat. It combines translation, speech recognition (ASR), text to speech (TTS), a voice changer (RVC) and chat reading (OCR) in one app.

It is derived from [VRCT](https://github.com/misyaguziya/VRCT) and developed by [kein5](https://github.com/kein5).

::: warning Not an official VRCT release
VRCT-VOX is not endorsed by the VRCT authors or VRChat. Send questions and bug reports about VRCT-VOX to the [VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues), not to the VRCT authors.
:::

## What VRCT-VOX adds to VRCT

- [Text to speech (TTS)](../features/tts) Speaks your text or its translation into VRChat's microphone. You can hear the same voice on your own speakers.
- [Voice changer (RVC)](../features/voice-conversion) Changes your microphone's voice with RVC or Seed-VC and sends it to VRChat.
- [Realtime captions](../features/transcription) Turns your voice and other players' voices into text with the speech recognition server that comes with the app.
- [Chat reading (OCR)](../features/chat-reading) Reads the text of chatboxes shown on the VRChat screen.
- [Linux build](./install#linux) Global shortcuts on Wayland, a PipeWire virtual microphone, and Japanese input methods (fcitx/Mozc, ibus).
{.feature-rows}

The models are not part of the app. Each one is downloaded only after you check its license and size and agree ([Model downloads](./models)).

## Versions and tested environments

The first stable version is 0.1.0. Versions count from 0.1.0, separately from VRCT (3.x). Betas are published on GitHub Releases as pre-releases.

The Linux build has been tested with real models on CachyOS (KDE Plasma, Wayland). The Windows build has been tested with real models on a Windows 11 PC.

Next, see [Install](./install). To see what it can do first, read [Find what you want to do](./tasks); for how voice and text move through it, read [How voice and text flow](./how-it-works).
