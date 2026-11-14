# Text to speech (TTS)

Speaks your text or its translation into a virtual microphone that VRChat uses. The settings are under Settings → "Text to speech (TTS)".

It turns on and off separately from sending text to the chatbox.

## What you need

- A speech model, run by the bundled [speech.cpp](https://github.com/nyosegawa/speech.cpp) servers. Japanese is spoken with Irodori-TTS and other languages with Qwen3-TTS. Neither is bundled: download one, or point to a file you have ([Model downloads](../guide/models), [Use your own models](../guide/custom-models#tts)).
- A virtual microphone, for VRChat to hear the speech. On Linux you can use "Managed virtual microphone (Linux)" ([Linux audio route](../guide/linux-audio)). On Windows, use a virtual cable you install yourself.

## First steps

1. Under Settings → "Text to speech (TTS)" → "Models and servers", download a model with "Download a default model", or enter the path of a GGUF file you have.
2. Save with "Save changes" at the top, then press "Start server". Saving alone does not load the model.

   ![Settings → Text to speech (TTS)](/screenshots/en/tts.webp)

3. Set "Chat voice" to "Original text". To speak translations, choose "Translated text" and a "Translation slot".
4. Choose where to play under "Output device". Trying earphones first is a good idea. If a device is missing, press "Refresh devices".
5. Go back to the main screen and turn on "Text to speech (TTS)". Text you send is now spoken.

With a bundled server selected, turning it on from the main screen also starts the server.

## Get your voice into VRChat

Set the output to a virtual microphone and choose that microphone in VRChat. Why a virtual microphone is needed is in [How voice and text flow](../guide/how-it-works#why-a-virtual-microphone-is-needed).

## Hear it yourself

"Hear it on my speakers" plays the same speech that goes to VRChat on your own speakers or headphones.

- What VRChat receives does not change.
- Use headphones so your microphone does not pick it up.

## Start speaking sooner (Japanese, GPU)

"Low-latency standby (Irodori GPU)" shortens the time before speech starts. It is off by default.

While it waits, it keeps running short calculations on the GPU. That uses more power and can compete with the game for the GPU.

## Stop

There are three ways to stop, each with a different scope. "Stop speech" and "Mute" are always at the top of the main screen.

| Action | What stops |
|---|---|
| Turn off "Text to speech (TTS)" on the main screen | Accepting, playing and queueing speech. Text sending, the voice changer and translation continue |
| "Stop speech" | The current speech and the queue only. "Stop playback and clear queue" under Settings → "Text to speech (TTS)" does the same |
| "Mute" | The whole audio route (with the managed microphone, both speech and the voice changer). It lasts until you resume, and the button reads "Muted" meanwhile. "Mute until resumed" under Settings → "Device" → "Audio route" does the same |

All can be assigned to [hotkeys](./quick-chat#hotkeys). Speech and the bundled servers are off again after you restart the app.

## When it does not work

- If VRChat does not hear it, see [Troubleshooting](../guide/troubleshooting#vrchat-does-not-hear-the-speech).
- If text is spoken twice, turn off the other tool that reads the same chat, such as the upstream author's VRCT-TTS.
- If a model you brought does not work, see [Use your own models](../guide/custom-models#tts).
