# Privacy

## Usage data

VRCT-VOX sends its developers two kinds of events. Turn them off under Settings → "Advanced" → "Send usage data".

| Event | When | What it holds |
|---|---|---|
| The app started | Once a day | The time it was sent, the app version, the OS and its version, the display language, the PC's hardware |
| An error happened | Once a day for each kind of error | The same, and the fixed name of the kind of error (its error code) |

The PC's hardware means:

- the CPU's name and its number of logical cores
- the amount of memory, rounded to a common size such as 8, 16 or 32 GB
- for up to four GPUs: the name, whether it is integrated or discrete, the amount of video memory, and the driver version when it can be read

You can read what is sent in the app itself. The notice shown before anything is sent and Settings → "Advanced" both have "See what is sent", which lists what this PC sends field by field and also shows the data itself. Under "Advanced" you can also read what has been sent so far.

- The text and audio of conversations, the names of microphones and speakers, user names, the PC's name and file locations are never sent.
- The receiver does not keep the sender's IP address or anything that tells one PC from another. It runs on Cloudflare, which handles the sender's address as the other end of the connection.
- No number that identifies a PC is sent, but an unusual combination of hardware can suggest that two events came from the same PC.
- Before anything is sent, a dialog explains what is sent. Nothing is sent until you choose "Send" or "Don't send".
- Starting the app with the environment variable `VRCT_TELEMETRY` set to `off` sends nothing, whatever the setting says.

Upstream VRCT's usage reporting (Aptabase telemetry) is not used. Even when an old key file remains, nothing goes to upstream. The in-app updater is also disabled, so the app does not check for updates at startup.

## What is sent outside

Turning off usage reporting does not make every feature offline. Services you choose receive what they need to work.

| Feature | Sent to | What is sent |
|---|---|---|
| External translation APIs (DeepL, Gemini, OpenAI and others) | The service you choose | The text to translate |
| Google speech recognition engine (Windows) | Google | Your microphone or speaker audio |
| Model downloads | Hugging Face | The download request |
| Sending to the chatbox | VRChat (OSC on this PC) | The text you send |
| Usage data (can be turned off) | The developers of VRCT-VOX (Cloudflare) | That the app started, the kind of an error, and the PC's hardware |

Local translation models, the bundled speech.cpp servers (speech and realtime captions) and chat reading run on this PC. The picture of a window you share for chat reading stays on this PC too.

You choose the speech recognition engine yourself the first time you turn transcription on. Audio is never sent to a service you did not choose, and the app does not switch to Google on its own when a Whisper model is missing.

When you change the URL of an OpenAI-compatible endpoint or Custom Whisper, you enter the API key again. A saved key is never sent to the new URL on its own.

## What is stored on this PC

- The settings file (`config.json`), which also holds your external translation API keys, the key for the OBS browser source and WebSocket, and, on Linux, what the desktop needs to share the same window again without its dialog.
- Logs, recording what the app did. Remove personal data and conversation text before posting them in a report.
- Conversation logs, saved as text files only when "Auto Save Message Logs" under Settings → "Advanced" is on.

For the locations, see [Install](./install) and [Troubleshooting](./troubleshooting).

## Servers that listen

The OBS browser source and WebSocket run only when you turn them on, and by default listen only on this PC (`127.0.0.1`). Connecting needs the key in the URL (see [OBS and WebSocket](../features/integrations)).
