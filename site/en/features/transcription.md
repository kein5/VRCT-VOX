# Speech recognition and realtime captions

Turns your voice and other players' voices into text. The settings are under Settings → "Transcription".

![Settings → Transcription](/screenshots/en/transcription.webp)

## Realtime captions (Linux)

On Linux, captions come from the bundled speech.cpp speech recognition (ASR) server. They appear in the message log and in the large overlay if you enable it.

- **Microphone captions**: transcribe your microphone.
- **Game audio captions**: transcribe VRChat's audio. Choose an output dedicated to the game; a shared output also includes other apps' sound.

The "Voice2Chatbox" and "Speaker2Log" switches on the main screen start and stop each kind of caption. If you chose the bundled server, turning a switch on also starts the server. Captions are off again after you restart the app.

::: info Game audio is never resent
Captured game audio is never sent to your microphone or the chatbox.
:::

### What you need

The ASR server needs both a recognition model and Silero VAD. Get them under "Bundled speech.cpp servers" → "ASR + VAD" (see [Model downloads](../guide/models)).

| Model | Languages | Size | License |
|---|---|---|---|
| Haas-ja v1.0 · Q8_0 | Japanese only | 0.61 GiB | Apache-2.0 |
| Qwen3-ASR 0.6B · Q8_0 | 30 languages, detects the language | 0.78 GiB | Apache-2.0 |
| Silero VAD v6.2 · F32 | (finds where speech starts and ends) | about 1.2 MB | MIT |

The bundled server loads one recognition model, shared by the microphone and game audio. If you talk with people who don't speak Japanese, choose Qwen3-ASR. "Detect automatically (auto)" needs a model that can detect the language, such as Qwen3-ASR.

### Term dictionary

Add words you want recognized, and how to write them, under "Term dictionary". Common VRChat terms are built in.

## Speech recognition on Windows

Windows uses the speech recognition inherited from upstream VRCT (Google, Whisper). Choose it under "Transcription Engines". Realtime captions are Linux only for now.
