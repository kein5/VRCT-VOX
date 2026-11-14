# Voice conversion (RVC, Seed-VC)

Converts your microphone with an RVC or Seed-VC runtime you prepare, and sends it to the virtual microphone. Both are experimental. Check the quality and latency in your own setup before relying on them.

![Settings → RVC](/screenshots/en/rvc.webp)

## RVC

The settings are under Settings → "RVC".

### What you need

An RVC model alone is not enough. You also need:

- an RVC runtime (the RVC-Project engine and a Python environment)
- HuBERT and RMVPE
- a trained model you are allowed to use (`.pth`) and, if needed, its retrieval index (`.index`)

The settings page can fetch the runtime, HuBERT and RMVPE. Under "RVC runtime", press "Review download", check the license, size and destination, and agree. Nothing is downloaded before you agree. When it finishes, press "Use this runtime" and save.

Fetching needs an NVIDIA GPU and its driver. Expect a download of about 3.6 GB and 12 GB of free space on Windows, and about 4.9 GB and 16 GB on Linux.

To build the runtime yourself, see [integrations/rvc/README.md](https://github.com/kein5/VRCT-VOX/blob/develop/integrations/rvc/README.md) in the repository.

As a default model, you can get Saisho Utane's RVC v2 model (CC BY 4.0, about 0.31 GiB) with "Download a default model". Credit the author when you use it in published work or streams.

### Using it

1. Enter "RVC runtime folder", "Permitted RVC model (.pth)" and the other fields, and save.
2. Give the converted voice a way out.
   - On Linux, press "Prepare and use virtual microphone". When it is ready, press "Resume voice". In VRChat, choose "VRCT Managed Virtual Microphone" as your microphone.
   - On Windows, install a virtual cable such as VB-CABLE. Choose its playback end as "Output device" under Settings → "TTS", and its recording end as VRChat's microphone.
3. Under "Input to forward", choose the microphone you speak into. It starts as the "Mic" chosen under "Device".
4. Turn "RVC" on on the main screen.

## Seed-VC

Under Settings → "Advanced" → "Input forwarding", set "Direct voice mode" to "Voice conversion (experimental)". Enter the Seed-VC runtime and a reference WAV you are allowed to use. "Seed-VC runtime" on the same page can fetch the runtime: about 5 GB and 14 GB of free space on Windows, and about 6.4 GB and 18 GB on Linux.

Seed-VC is a GPL-3.0 engine and needs a supported NVIDIA GPU.

## Speech in the converted voice

Set "Speak through voice conversion" under Settings → "TTS" to On, and while a voice conversion runs, speech is converted too before it reaches the virtual microphone. Together with speaking the translation of what you say ("Speak final translations"), others hear the translation in your converted voice.

- During speech the conversion takes the speech in place of the microphone, then returns to the microphone. So this cannot go with mixing direct input and speech.
- With "Suppress direct input" chosen, your microphone is not heard and only the converted speech is.
- When no conversion runs, speech plays as before.
- Speech is heard a little later, by the time the conversion takes.

## Notes

- Using someone else's voice as a model or reference needs their permission.
- To hear the converted voice yourself, turn on "Hear it on my speakers" under "TTS".
