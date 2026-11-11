# What is VRCT-VOX

VRCT-VOX is a desktop app that helps you talk in VRChat. It combines translation, speech recognition, text to speech (TTS), voice conversion (RVC) and chat reading (OCR) in one app.

It is derived from [VRCT](https://github.com/misyaguziya/VRCT) and developed by [kein5](https://github.com/kein5).

::: warning Not an official VRCT release
VRCT-VOX is not endorsed by the VRCT authors or VRChat. Send questions and bug reports about VRCT-VOX to the [VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues), not to the VRCT authors.
:::

## What VRCT-VOX adds to VRCT

| Feature | What it does |
|---|---|
| Speak your translations | Reads your text or its translation with [speech.cpp](https://github.com/nyosegawa/speech.cpp) into a virtual microphone that VRChat uses. Japanese uses Irodori; other languages use Qwen3-TTS. Voice and chatbox text are configured separately. |
| Hear yourself | Optionally plays the same speech on your own speakers or headphones. |
| Voice conversion | Converts your microphone with an RVC or Seed-VC runtime. The settings can fetch the runtime for you after you check its license and size and agree. |
| Realtime captions | Transcribes your microphone and other players with the bundled speech recognition server. |
| Chat reading | Reads the text of chatboxes shown on the VRChat screen. |
| Model downloads | Models are downloaded only after you check their license and size and agree. |
| Linux support | Global shortcuts on Wayland, a PipeWire virtual microphone and Japanese input methods (fcitx/Mozc, ibus). The VR UI, chat reading from a shared native Wayland window, and pasting in Voice Typing Mode work too. |

## Status

VRCT-VOX is in beta. Versions count from 0.1.0, separately from VRCT (3.x). Betas are published from the `develop` branch and stable releases from `main`.

The Linux build has been tested with real models on CachyOS (KDE Plasma, Wayland). The Windows build has been tested with real models on a Windows 11 PC.

Next, see [Install](./install).
