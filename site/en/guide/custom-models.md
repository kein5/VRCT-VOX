# Use your own models

Besides the default models you can download from the settings, you can use models you bring yourself: models you trained, models published elsewhere, and models you bought.

What you can use depends on the feature.

| Feature | What you can use | Where to set it |
|---|---|---|
| Text to speech (TTS) | A GGUF model, and a voice GGUF (optional). Or a server you run on this computer | "Text to speech (TTS)" → "Models and servers" |
| Speech recognition (ASR) | A GGUF recognition model, VAD and diarization (optional). Or a server you run on this computer | "Speech recognition (ASR)" → "Models and servers" → "ASR + VAD" |
| Whisper | A Whisper server of your own (OpenAI compatible) | "Speech recognition (ASR)" → "Cloud speech recognition" → "Custom Whisper server" |
| Voice changer (RVC) | A `.pth` model and a `.index` (optional) | "Voice changer (RVC)" |
| Seed-VC | A reference WAV | "Advanced" → "Input forwarding" |
| Translation | A model you load into LM Studio, Ollama or an OpenAI-compatible server | "Translation" → "Local LLM & Compatible Server" |
| Chat reading (OCR) | Not possible | — |

Each model setting has a "How to use your own model" link that opens its section of this page.

::: warning The app does not check the terms of use
Before a model is downloaded from the settings, the app shows its provider, license and size and asks for your consent. For a file you point to yourself, the app does not check the terms of use. Make sure you may use it ([Models you bought or found published](#bought-models)).
:::

## Text to speech (TTS) {#tts}

### What you can use

- A speech GGUF model that the bundled speech.cpp can load, such as Irodori-TTS or Qwen3-TTS.
- A voice GGUF (optional): a voice made from reference recordings, for Irodori-TTS. How to make one is in [speech.cpp](https://github.com/nyosegawa/speech.cpp), under `speech voice`.

### Set it

1. Open "Models and servers" near the bottom of Settings → "Text to speech (TTS)".
2. Enter the file's location in "Model GGUF path" of "Japanese TTS" or "Multilingual TTS". Japanese speech uses "Japanese TTS"; other languages use "Multilingual TTS".
3. For a voice GGUF, enter its location in "Voice GGUF path (optional)".
4. Press "Save changes".
5. For a voice GGUF, enter `custom` as the "Japanese voice name" or "Other languages voice name" above, and save.
6. Turn on "Text to speech (TTS)" on the main screen. The server starts then.

### Use a server you run yourself

If you run a speech.cpp server on this computer yourself, choose "External server" in "Japanese server" (or the other languages one) and enter its URL. The URL can only be `127.0.0.1`, `localhost` or `::1`.

### When it does not work

| Message | What to check |
|---|---|
| The bundled TTS server for this language has no usable model | That the file location is right and ends in `.gguf` |
| This model does not fit this server's task (speech or recognition) | That a recognition model was not entered for speech |

A wrong voice name gives an error with a number when speech plays. For a voice GGUF, check that the voice name is `custom`.

## Speech recognition (ASR) {#asr}

### What you can use

- A recognition GGUF model that the bundled speech.cpp can load, such as Qwen3-ASR or Haas-ja.
- A VAD GGUF, which finds where speech starts and ends. It is always needed with the recognition model.
- A diarization GGUF (optional).

### Set it

1. Open "Models and servers" near the bottom of Settings → "Speech recognition (ASR)", and look at "ASR + VAD".
2. Enter the file locations in "Model GGUF path" and "VAD GGUF path". For diarization, also enter "Diarization GGUF path (optional)".
3. Press "Save changes".
4. Turn on "Mic input" or "Listening" on the main screen.

If you run a recognition server of your own on this computer, choose the external server under "ASR server" in "Realtime captions", and enter its URL.

### When it does not work

| Message | What to check |
|---|---|
| A model file of the bundled ASR server is missing or is not a GGUF file | That the model and VAD locations are right and end in `.gguf` |
| This model does not fit this server's task (speech or recognition) | That a speech model was not entered for recognition |
| The ASR model does not recognize the selected language | That the model supports the language spoken |

## A Whisper server {#whisper-server}

The app's own Whisper models are the listed ones only. To use another Whisper model, run an OpenAI-compatible Whisper server (`/v1/audio/transcriptions`) yourself and connect to it.

1. Open "Custom Whisper server" in Settings → "Speech recognition (ASR)" → "Cloud speech recognition".
2. Enter the URL, and a key if it needs one, and save. Saving checks that the server can be reached and reads its list of models.
3. Choose a model, and choose "Custom Whisper server" as the engine above.

Use HTTPS. HTTP works only for this computer (localhost) or an IP address on your local network.

## Voice changer (RVC) {#rvc}

### What you can use

- An RVC model (`.pth`): v1 or v2, with a sample rate of 32k, 40k or 48k.
- A retrieval index (`.index`), optional. It is needed when "Retrieval blend" is above 0.

RVC also needs its runtime, which you can download from the settings ([Voice changer](../features/voice-conversion)). It needs an NVIDIA GPU.

### Set it

1. Open Settings → "Voice changer (RVC)".
2. Open "Models and runtime" below, and enter the model's location in "Permitted RVC model (.pth)". If you have an index, enter it in "RVC retrieval index (.index, optional)".
3. Press "Save changes".
4. Turn on "Voice changer (RVC)" on the main screen.

### When it does not work

| Message | What to check |
|---|---|
| This model's format is not supported | That the model is v1 or v2, at 32k, 40k or 48k |
| The RVC model (.pth) or the index (.index) was not found | That the file locations are right |
| The index (.index) could not be read | Choose another `.index`, or set "Retrieval blend" to 0 |
| The model or the base model (HuBERT) is incomplete or does not match | That the model file is not damaged. Set the runtime up again |

## Seed-VC {#seed-vc}

Seed-VC changes your voice towards the voice in a reference WAV.

- The WAV is PCM and 1 to 30 seconds long.
- In Settings → "Advanced" → "Input forwarding", set "Direct voice mode" to "Voice conversion (experimental)" and enter the file in "Permitted reference WAV".

A reference recording of anyone else's voice needs that person's permission.

## Translation {#translation}

The models of local AI translation are the listed ones only. To translate with another model, load it into LM Studio, Ollama or an OpenAI-compatible server and connect to that.

1. Load the model into the server and start it.
2. In Settings → "Translation" → "Local LLM & Compatible Server", press that server's connection check.
3. Choose the model, and choose the server as the translation engine on the main screen.

See [Translation](../features/translation#local-llms-and-compatible-servers) for more.

## Models you bought or found published {#bought-models}

Before you use a model you did not train yourself, read its provider's terms of use. Check in particular:

- whether you may use it in VRChat;
- whether you may use it in streams and recordings;
- whether credit is needed, and if so, what to write where;
- whether you may modify it;
- whether you may share it.

Also:

- A model or reference recording of a real person's voice needs that person's permission.
- Give a model file to someone else only when its terms allow it.
- Keep the license text you got when you bought it, so you can check it later.

## What cannot be replaced

Chat reading (OCR) uses only the recognition models and the chatbox detector downloaded from the settings. It loads a file only when its size and hash match, so it cannot use a model of your own.
