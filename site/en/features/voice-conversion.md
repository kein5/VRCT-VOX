# Voice conversion (RVC, Seed-VC)

Converts your microphone with an RVC or Seed-VC runtime you prepare, and sends it to the virtual microphone. Both are experimental. Check the quality and latency in your own setup before relying on them.

![Settings → RVC](/screenshots/en/rvc.webp)

::: warning Linux only for now
Voice conversion uses the managed virtual microphone (PipeWire), so it works on Linux only for now.
:::

## RVC

The settings are under Settings → "RVC".

### What you need

An RVC model alone is not enough. You also need:

- an RVC runtime (the RVC-Project engine and a Python environment)
- HuBERT and RMVPE
- a trained model you are allowed to use (`.pth`) and, if needed, its retrieval index (`.index`)

How to set up the runtime is in [integrations/rvc/README.md](https://github.com/kein5/VRCT-VOX/blob/develop/integrations/rvc/README.md) in the repository. The app does not download these for you.

As a default model, you can get Saisho Utane's RVC v2 model (CC BY 4.0, about 0.31 GiB) with "Download a default model". Credit the author when you use it in published work or streams.

### Using it

1. Enter "RVC runtime folder", "Permitted RVC model (.pth)" and the other fields, and save.
2. Press "Prepare and use virtual microphone". When it is ready, press "Resume voice".
3. Under "Input to forward", choose the microphone you speak into. It starts as the "Mic" chosen under "Device".
4. In VRChat, choose "VRCT Managed Virtual Microphone" as your microphone.
5. Turn "RVC" on on the main screen.

## Seed-VC

Under Settings → "Advanced" → "Input forwarding (Linux)", set "Direct voice mode" to "Voice conversion (experimental)". Enter the Seed-VC runtime you installed and a reference WAV you are allowed to use.

Seed-VC is a GPL-3.0 engine and needs a supported NVIDIA GPU.

## Notes

- Using someone else's voice as a model or reference needs their permission.
- To hear the converted voice yourself, turn on "Hear it on my speakers" under "TTS".
