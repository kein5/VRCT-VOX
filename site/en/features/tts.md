# Text to speech (TTS)

Speaks your text or its translation into VRChat's microphone, through a virtual microphone. The settings are under Settings → "Text to speech (TTS)".

You can turn speech on and off separately from sending text to the chatbox.

## What you need

- A speech model, run by the [speech.cpp](https://github.com/nyosegawa/speech.cpp) servers that come with the app. Japanese is spoken with Irodori-TTS and other languages with Qwen3-TTS. Neither model comes with the app: download one, or point to a file you have ([Model downloads](../guide/models), [Use your own models](../guide/custom-models#tts)).
- A virtual microphone, for VRChat to hear the speech. On Linux you can use "Managed virtual microphone (Linux)" ([Linux audio route](../guide/linux-audio)). On Windows, install a virtual cable such as VB-CABLE.

## First steps

1. Under Settings → "Text to speech (TTS)" → "Models and servers", download a model with "Download a default model", or enter the path of a GGUF file you have.
2. Save with "Save changes" at the top, then press "Start server". Saving alone does not load the model.

   ![Settings → Text to speech (TTS)](/screenshots/en/tts.webp)

3. Set "Chat voice" to "Original text". To speak translations, choose "Translated text", and under "Translation slot" choose which target language's translation is spoken.
4. Under "Output device", choose where the speech plays. Try it with your own earphones first. If a device is missing, press "Refresh devices".
5. Go back to the main screen and turn on "Text to speech (TTS)". Text you send is now spoken.

With a bundled server selected, turning it on from the main screen also starts the server.

## Get your voice into VRChat

Choose the virtual microphone under "Output device", and choose the same one as your microphone in VRChat. Why a virtual microphone is needed is in [How voice and text flow](../guide/how-it-works#why-a-virtual-microphone-is-needed).

## Hear it yourself

"Hear it on my speakers" plays the same speech that goes to VRChat on your own speakers or headphones.

- What VRChat receives does not change.
- Use headphones, so your microphone does not pick up the sound from your speakers.

## Start speaking sooner (Japanese, GPU)

"Low-latency standby (Irodori GPU)" shortens the time before speech starts. It is off by default.

While nothing is being spoken, it keeps running short calculations on the GPU so that speech can start right away. That uses more power and can compete with the game for the GPU.

## Stop

There are three ways to stop, each with a different scope. "Stop speech" and "Mute" are always at the top of the main screen.

| Action | What stops |
|---|---|
| Turn off "Text to speech (TTS)" on the main screen | New speech, the speech playing now and the speech waiting its turn. Text sending, the voice changer and translation continue |
| "Stop speech" | The speech playing now and the speech waiting its turn, nothing else. "Stop playback and clear queue" under Settings → "Text to speech (TTS)" does the same |
| "Mute" | Everything VRCT-VOX sends to VRChat (with the managed virtual microphone, both speech and the voice changer). It lasts until you resume, and the button reads "Muted" meanwhile. "Mute until resumed" under Settings → "Device" → "Audio route" does the same |

All can be assigned to [hotkeys](./quick-chat#hotkeys). After a restart, speech and the bundled servers start off.

## When it does not work

- If VRChat does not hear it, see [Troubleshooting](../guide/troubleshooting#vrchat-does-not-hear-the-speech).
- If the same text is spoken twice, turn off the other tool that reads the same chat, such as VRCT-TTS by upstream VRCT's author.
- If a model you brought does not work, see [Use your own models](../guide/custom-models#tts).
