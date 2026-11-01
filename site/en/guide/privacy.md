# Privacy

## No usage data is sent

Upstream VRCT's usage reporting (Aptabase telemetry) is disabled in VRCT-VOX, even when an old key file remains. The in-app updater is also disabled, so the app does not check for updates at startup.

## What is sent outside

Turning off usage reporting does not make every feature offline. Services you choose receive what they need to work.

| Feature | Sent to | What is sent |
|---|---|---|
| External translation APIs (DeepL, Gemini, OpenAI and others) | The service you choose | The text to translate |
| Google speech recognition engine (Windows) | Google | Your microphone audio |
| Model downloads | Hugging Face | The download request |
| Sending to the chatbox | VRChat (OSC on this PC) | The text you send |

Local translation models, the bundled speech.cpp servers (speech and realtime captions) and chat reading run on this PC.

## What is stored on this PC

- The settings file (`config.json`), which also holds your external translation API keys.
- Logs, recording what the app did. Remove personal data and conversation text before posting them in a report.
- Conversation logs, saved as text files only when "Auto Save Message Logs" under Settings → "Other" is on.

For the locations, see [Install](./install) and [Troubleshooting](./troubleshooting).

## Servers that listen

The OBS browser source and WebSocket run only when you turn them on, and by default listen only on this PC (`127.0.0.1`) (see [OBS and WebSocket](../features/integrations)).
