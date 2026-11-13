# Speech recognition and realtime captions

Turns your voice and other players' voices into text. The settings are under Settings → "Transcription".

![Settings → Transcription](/screenshots/en/transcription.webp)

## Realtime captions

Captions come from the bundled speech.cpp speech recognition (ASR) server. They appear in the message log and in the large overlay if you enable it.

- **Microphone captions**: transcribe your microphone.
- **Game audio captions**: transcribe VRChat's audio. Choose an output dedicated to the game; a shared output also includes other apps' sound.

The "Voice2Chatbox" and "Speaker2Log" switches on the main screen start and stop each kind of caption. If you chose the bundled server, turning a switch on also starts the server. Captions are off again after you restart the app.

::: info Game audio is never resent
Captured game audio is never sent to your microphone or the chatbox.
:::

### What you need

The ASR server needs both a recognition model and Silero VAD. Open "Models and servers" further down the page and get them under "ASR + VAD" (see [Model downloads](../guide/models)).

![The "ASR + VAD" section of "Models and servers" in Settings → Transcription](/screenshots/en/asr-models.webp)

| Model | Languages | Size | License |
|---|---|---|---|
| Haas-ja v1.0 · Q8_0 | Japanese only | 0.61 GiB | Apache-2.0 |
| Qwen3-ASR 0.6B · Q8_0 | 30 languages, detects the language | 0.78 GiB | Apache-2.0 |
| Silero VAD v6.2 · F32 | (finds where speech starts and ends) | about 1.2 MB | MIT |

The bundled server loads one recognition model, shared by the microphone and game audio. If you talk with people who don't speak Japanese, choose Qwen3-ASR. "Detect automatically (auto)" needs a model that can detect the language, such as Qwen3-ASR.

### Speaker labels

Game audio captions can carry a label for who spoke (A, B, …). Download and apply the diarization model (Nemotron 3 Diarization, about 106 MB, OpenMDW-1.1) under "Models and servers" → "ASR + VAD"; it takes effect the next time the server starts. To stop using it, clear "Diarization GGUF path (optional)".

- The log shows "Speaker A". In the desktop caption overlay the label comes before the words, and each voice has its own colour.
- The labels are guessed from the sound of the voices. They do not name anyone, and similar voices can share a label.
- When two people speak with little pause, their words share one caption. It then shows both, as "Speaker A, B".
- Labels start over each time you turn the switch on.
- A caption settles about 0.3 seconds later (measured on an RTX 3060 Ti).
- A GPU is needed. A CPU alone cannot keep up, so while the server runs on the CPU, captions carry no labels even with the model.
- Microphone captions do not use it.

::: info What was checked
Checked on Windows 11 with conversations of two to six synthetic voices, not with human voices. The results are in the developers' [record](https://github.com/kein5/VRCT-VOX/blob/develop/docs/voice-stack/speaker-diarization-2026-11-13.md) (in Japanese).
:::

### Term dictionary

Add words you want recognized, and how to write them, under "Term dictionary". Common VRChat terms are built in.

## Voice Typing Mode

"Voice Typing Mode" under Settings → "VR" pastes what you say, once transcribed, into an input field. It uses the clipboard. While SteamVR is running, it brings the window of the app SteamVR is running (VRChat, for example) to the front and pastes there. When SteamVR is not running, the text is only copied to the clipboard.

On Linux it pastes into apps that run as X11/XWayland windows, such as VRChat under Proton. On KDE, the desktop asks once whether VRCT-VOX may control input devices when it first pastes. It cannot paste into a native Wayland window; the text is copied to the clipboard only.

## Speech recognition on Windows

On Windows you can choose the speech recognition inherited from upstream VRCT (Google, Whisper) under "Transcription Engines". If you turn transcription on before choosing an engine, a "Choose speech recognition" screen opens. Google sends your microphone or speaker audio to Google's speech service. Whisper recognizes audio on this PC. The app never switches from the engine you chose to another one on its own.

Realtime captions work too: choose "Bundled server" for "ASR server" under "Realtime captions", and the main screen's microphone and speaker switches use them.
