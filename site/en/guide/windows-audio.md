---
route: windows-audio
---

# Windows audio route

For VRChat to hear speech or your changed voice, VRCT-VOX's audio has to reach VRChat's microphone input. On Windows the app cannot create a virtual microphone, so you install a virtual cable. This page uses [VB-CABLE](https://vb-audio.com/Cable/) as the example.

VB-CABLE is a VB-Audio product and has nothing to do with VRCT-VOX. Check its terms on its download page.

## Install the virtual cable

1. Download VB-CABLE from its page and install it as the page describes.
2. Restart your PC after installing it.

It adds "CABLE Input" to your output (playback) devices and "CABLE Output" to your input (recording) devices. Whatever plays into CABLE Input comes out of CABLE Output.

## Connect it to VRChat

1. In VRCT-VOX, choose "CABLE Input" as "Output device" under Settings → "Text to speech (TTS)", and save. If it is missing, press "Refresh devices".
2. In VRChat, choose "CABLE Output" as your microphone.
3. Turn on "Text to speech (TTS)" on the main screen and send a short line. If VRChat's microphone meter moves, it is connected.

The voice changer (RVC) plays your changed voice to the same "Output device". Windows mixes the speech and the changed voice into the cable.

::: warning Do not pick the cable's recording end as an input
If "Input to forward" for the voice changer is "CABLE Output", it does not start, because your voice would loop back to you. Realtime captions do not read the cable that carries your voice either.
:::

## Hear it yourself

"Hear it on my speakers" under "Text to speech (TTS)" also plays what goes to VRChat on your own speakers or headphones ([Hear it yourself](../features/tts#hear-it-yourself)).

## Mute

"Mute" at the top of the main screen stops speech and the voice changer together. While it is on, the app plays silence into the cable.

## When it does not work

See [Troubleshooting](./troubleshooting#vrchat-does-not-hear-the-speech).
