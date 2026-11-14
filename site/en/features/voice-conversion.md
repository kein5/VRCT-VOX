# Voice changer (RVC, Seed-VC)

Changes your microphone's voice with an RVC or Seed-VC runtime you prepare, and sends it to the virtual microphone. The settings are under Settings → "Voice changer (RVC)".

Both are experimental. Check the quality and latency in your own setup before relying on them.

## What you need

- An NVIDIA GPU and its driver
- A virtual microphone for the changed voice to go out through ([How voice and text flow](../guide/how-it-works#why-a-virtual-microphone-is-needed))
- For RVC:
  - an RVC runtime (the RVC-Project engine and a Python environment)
  - HuBERT and RMVPE
  - a trained model you are allowed to use (`.pth`) and, if needed, its retrieval index (`.index`)
- For Seed-VC, a Seed-VC runtime and a reference WAV you are allowed to use

Models you trained or bought work too ([Use your own models](../guide/custom-models#rvc)).

## Set up RVC

The settings page can fetch the runtime, HuBERT and RMVPE.

1. Open "Models and runtime" near the bottom of Settings → "Voice changer (RVC)".
2. Under "RVC runtime", press "Review download". Check the license, size and destination, and agree. Nothing is downloaded before you agree.
3. When it finishes, press "Use this runtime" and save.

Expect a download of about 3.6 GB and 12 GB of free space on Windows, and about 4.9 GB and 16 GB on Linux. To build the runtime yourself, see [integrations/rvc/README.md](https://github.com/kein5/VRCT-VOX/blob/develop/integrations/rvc/README.md) in the repository.

As a default model, you can get Saisho Utane's RVC v2 model (CC BY 4.0, about 0.31 GiB) with "Download a default model". Credit the author when you use it in published work or streams.

## Change your voice with RVC

1. Enter "RVC runtime folder" and "Permitted RVC model (.pth)", and save.

   ![Settings → Voice changer (RVC)](/screenshots/en/rvc.webp)

2. Give the changed voice a way out.
   - On Linux, press "Prepare and use virtual microphone". When it is ready, press "Resume voice". In VRChat, choose "VRCT Managed Virtual Microphone" as your microphone.
   - On Windows, install a virtual cable such as VB-CABLE. Choose its playback end as "Output device" under Settings → "Text to speech (TTS)", and its recording end as VRChat's microphone.
3. Under "Input to forward", choose the microphone you speak into. It starts as the "Mic" chosen under "Device".
4. Turn on "Voice changer (RVC)" on the main screen.

## Change your voice with Seed-VC

1. Under Settings → "Advanced" → "Input forwarding", set "Direct voice mode" to "Voice conversion (experimental)".
2. Enter the Seed-VC runtime and a reference WAV you are allowed to use. "Seed-VC runtime" on the same page can fetch the runtime.

Expect about 5 GB and 14 GB of free space on Windows, and about 6.4 GB and 18 GB on Linux. Seed-VC is a GPL-3.0 engine and needs a supported NVIDIA GPU.

## Speak in your changed voice

Set "Speak through voice conversion" under Settings → "Text to speech (TTS)" to On. While the voice changer runs, speech is changed too before it reaches the virtual microphone.

Together with speaking the translation of what you say ("Speak final translations"), others hear the translation in your changed voice.

- During speech the voice changer takes the speech in place of the microphone, then returns to the microphone. So this cannot go with mixing direct input and speech.
- With "Suppress direct input" chosen, your microphone is not heard and only the changed speech is.
- When the voice changer is not running, speech plays as before.
- Speech is heard a little later, by the time the change takes.

## Hear the changed voice yourself

Turn on "Hear it on my speakers" under "Text to speech (TTS)".

## Stop

Turn off "Voice changer (RVC)" on the main screen. "Mute" stops both speech and the voice changer ([how to stop text to speech](./tts#stop)).

## Before you use it

Using someone else's voice as a model or reference needs their permission. For a model you bought, also check the provider's terms ([Models you bought or found published](../guide/custom-models#bought-models)).

## When it does not work

If it cannot start, the main screen says why. For a problem with a model's format or location, see the table in [Use your own models](../guide/custom-models#rvc).
