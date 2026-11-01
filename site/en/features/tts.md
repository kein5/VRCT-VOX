# Text to speech (TTS)

Speaks your text or its translation into a virtual microphone that VRChat uses. It turns on and off separately from sending text to the chatbox. The settings are under Settings → "TTS".

## Voices

Speech comes from the bundled [speech.cpp](https://github.com/nyosegawa/speech.cpp) servers.

- **Japanese**: Irodori-TTS
- **Other languages**: Qwen3-TTS

Neither model is bundled. Get them with "Download a default model" under "Bundled speech.cpp servers" (see [Model downloads](../guide/models)). You can also point to GGUF files you already have.

## First steps

1. Under Settings → "TTS" → "Bundled speech.cpp servers", download a model or enter a GGUF path.
2. Save with "Save changes" at the top, then press "Start server". Saving alone does not load the model.
3. Set "Chat voice" to "Original text". To speak translations, choose "Translated text" and a "Translation slot".
4. Choose where to play under "Output device". Trying earphones first is a good idea. If a device is missing, press "Refresh devices".
5. Go back to the main screen and turn "TTS" on. Text you send is now spoken.

::: tip Getting your voice into VRChat
For VRChat to hear the speech, set the output to a virtual microphone and choose that microphone in VRChat. On Linux you can use "Managed virtual microphone (Linux)" (see [Linux audio route](../guide/linux-audio)). On Windows, use a virtual cable you install yourself.
:::

## Hear it yourself

"Hear it on my speakers" plays the same speech that goes to VRChat on your own speakers or headphones. What VRChat receives does not change. Use headphones so your microphone does not pick it up.

## Stopping

There are three ways to stop, each with a different scope.

| Action | What stops |
|---|---|
| Turn "TTS" off on the main screen | Accepting, playing and queueing speech. Text sending, RVC and translation continue |
| "Stop playback and clear queue" | The current speech and the queue only |
| "Device" → "Audio route" → "Mute until resumed" | The whole audio route (with the managed microphone, both TTS and voice conversion) |

TTS and the bundled servers are off again after you restart the app.

## Low-latency standby (Japanese, GPU)

"Low-latency standby (Irodori GPU)" shortens the time before speech starts. While it waits, it keeps running short calculations on the GPU, which uses more power and can compete with the game for the GPU. It is off by default.

::: warning If text is spoken twice
Another tool that reads the same chat, such as the upstream author's VRCT-TTS, makes it speak twice. Turn one of them off.
:::
