# What is VRCT-VOX

VRCT-VOX is a desktop app that helps you talk in VRChat. It combines translation, speech recognition, text to speech (TTS), voice conversion (RVC) and chat reading (OCR) in one app.

It is derived from [VRCT](https://github.com/misyaguziya/VRCT) and developed by [kein5](https://github.com/kein5).

::: warning Not an official VRCT release
VRCT-VOX is not endorsed by the VRCT authors or VRChat. Send questions and bug reports about VRCT-VOX to the [VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues), not to the VRCT authors.
:::

## What VRCT-VOX adds to VRCT

- **Speak your translations**: reads your text or its translation with [speech.cpp](https://github.com/nyosegawa/speech.cpp) into a virtual microphone that VRChat uses. Japanese uses Irodori; other languages use Qwen3-TTS. Voice and chatbox text are configured separately.
- **Hear yourself**: optionally plays the same speech on your own speakers or headphones.
- **Voice conversion**: converts your microphone with an RVC or Seed-VC runtime that you prepare.
- **Realtime captions (Linux)**: transcribes your microphone and other players with the bundled speech recognition server.
- **Chat reading**: reads the text of chatboxes shown on the VRChat screen.
- **Model downloads**: models are downloaded only after you check their license and size and agree.
- **Linux support**: global shortcuts on Wayland, a PipeWire virtual microphone and Japanese input methods (fcitx/Mozc, ibus).

## Status

VRCT-VOX is in beta. Versions count from 0.1.0, separately from VRCT (3.x). Betas are published from the `develop` branch and stable releases from `main`.

- **Linux**: tested with real models on CachyOS (KDE Plasma, Wayland).
- **Windows**: built and package-checked automatically only; not yet tested on a real Windows PC.

Next, see [Install](./install).
