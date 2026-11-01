# Troubleshooting

## Chat reading says the window was not found

- Start VRChat before turning on Chat Transcribe.
- Check that "Window name" under Settings → "Chat Transcribe" matches your client's title. The default is `VRChat`.
- On Linux, VRChat must run as an X11/XWayland window (Proton's default).

## It says models are missing

On that feature's page, download the model and press "Apply model path" (see [Model downloads](./models)). For speech and speech recognition, also press "Start server".

## VRChat does not hear the speech

1. Check that "Device" → "Audio route" is not muted. If it is, press "Resume voice".
2. Check that the output under "TTS" and the microphone chosen in VRChat match (see [Linux audio route](./linux-audio)).
3. Check that the bundled server is running. Servers are stopped again after you restart the app.
4. VRChat's microphone test records briefly and then plays back. Start the test while the input meter is moving.

## Text is spoken twice

Turn off any other tool that reads the same chat, such as VRCT-TTS.

## The window is black or shows nothing (Linux)

- While the monitor is asleep, the desktop does not draw windows, so the app looks frozen. Wake the monitor and check again.
- On NVIDIA GPUs, the AppImage applies a setting that avoids a display problem. Window transparency is unavailable then.

## Where the logs are

| OS | Location |
|---|---|
| Linux | `~/.config/vrct-vox/logs` |
| Windows | `logs` in the app's folder |

## Reporting a problem

Open an issue on the [VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues) with:

- your OS and VRCT-VOX version
- what happened and the steps that led to it
- logs, with personal data, API keys and conversation text removed

::: danger Do not report to upstream VRCT
Do not send questions or reports about VRCT-VOX to the upstream VRCT authors.
:::

Report security problems privately, not in a public issue, as described in [SECURITY.md](https://github.com/kein5/VRCT-VOX/blob/develop/SECURITY.md).
