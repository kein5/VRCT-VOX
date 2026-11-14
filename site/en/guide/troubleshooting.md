---
outline: [2, 3]
---

# Troubleshooting

Find the heading closest to what you see. If your voice or text does not reach VRChat, start with the first section.

## Nothing reaches VRChat

### Messages do not appear in the VRChat chatbox

- Open Settings → "VRChat". The top of the page says whether a VRChat with OSC enabled was found on this PC. The same line is in "Quick settings" on the main screen.
- If it says none was found, start VRChat, then open its Action Menu and set "Options" → "OSC" to "Enabled". The line changes shortly after.
- A message marked "Not sent to VRChat (off in settings)" in the log was held back because "Send Message To VRChat" is off. Turn it on under Settings → "VRChat".
- Whether VRChat was found is checked with OSCQuery, on this PC only. So when the destination is another PC, it says VRChat cannot be checked, and messages are still sent. If a firewall blocks discovery on this PC (mDNS), it can say none was found while messages still arrive.

### VRChat does not hear the speech

1. If the button at the top of the main screen reads "Muted", the voice is muted. Press "Resume voice" under Settings → "Device" → "Audio route".
2. Check that the output under "Text to speech (TTS)" and the microphone chosen in VRChat match (see [Windows audio route](./windows-audio) or [Linux audio route](./linux-audio)).
3. Check that the bundled server is running. Servers are stopped again after you restart the app.
4. VRChat's microphone test records for a moment and then plays it back. Start the test while VRChat's microphone input meter is moving.

### Text is spoken twice

Turn off any other tool that reads the same chat, such as VRCT-TTS.

## Starting and the microphone

### The microphone cannot be opened (Windows)

Some Windows versions ask whether VRCT-VOX may use the microphone the first time it does. Allow it, then start again.

The microphone also cannot be used while another Windows question is open, such as the firewall's. Answer it, then start again.

The firewall's question asks whether to allow the connections that let VRChat find VRCT-VOX through OSCQuery. Choose Allow access. Cancelling or closing it makes Windows add rules that block VRCT-VOX's incoming traffic.

If VRCT-VOX closes before the microphone question is answered, Windows refuses the microphone from then on, without asking again. Check Settings → Privacy & security → Microphone.

### Starting it again does not open a new window

Only one copy of VRCT-VOX runs. If you start it while it is running, the running window comes to the front.

### The window is black or shows nothing (Linux)

- While the monitor is asleep, the desktop does not draw windows, so the app looks frozen. Wake the monitor and check again.
- On NVIDIA GPUs, the AppImage applies a setting that avoids a display problem. Window transparency is unavailable then.

## Features and models

### It says models are missing

On that feature's page, download the model and press "Apply model path" (see [Model downloads](./models)). For speech and speech recognition, also press "Start server".

### A model you brought does not work

For a file you point to yourself, the app checks only the minimum, such as its extension and format. The messages you may see, and what to check for each feature, are in [Use your own models](./custom-models).

### Chat reading says the window was not found

- Start VRChat before turning on chat reading.
- Check that "Window name" under Settings → "Chat reading (OCR)" matches your client's title. The default is `VRChat`.
- On Linux, VRChat is found by its window name when it runs as an X11/XWayland window (Proton's default). When it runs as a native Wayland window, inside gamescope for example, share the window first (see [Chat reading](../features/chat-reading)).

### Voice Typing Mode does not paste (Linux)

- It pastes into apps that run as X11/XWayland windows, such as VRChat under Proton's defaults. It cannot paste into a native Wayland window. The text is still copied to the clipboard, so you can paste it yourself.
- On KDE, the desktop asks once whether VRCT-VOX may control input devices when it first pastes. Allow it.
- The paste goes to the window of the app that SteamVR is running. When SteamVR is not running, the text is only copied to the clipboard.

### Translation does not turn on after the model downloads (Windows)

This was a bug in the Windows builds up to 0.1.0-beta.6: the download review kept opening and Translation stayed off. Update to 0.1.0 or later.

## Logs and reports

### Where the logs are

| OS | Location |
|---|---|
| Windows | `logs` in the app's folder |
| Linux | `~/.config/vrct-vox/logs` |

### Reporting a problem

Open an issue on the [VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues) with:

- your OS and VRCT-VOX version
- what happened and the steps that led to it
- logs, with personal data, API keys and conversation text removed

::: info Do not report to upstream VRCT
Do not send questions or reports about VRCT-VOX to the upstream VRCT authors.
:::

Report security problems privately, not in a public issue, as described in [SECURITY.md](https://github.com/kein5/VRCT-VOX/blob/develop/SECURITY.md).
