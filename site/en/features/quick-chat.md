# Quick Chat and hotkeys

Quick Chat is a small window for sending text while you stay in your game, and hotkeys switch features with a key press. Both are set up under Settings → "Hotkeys".

![Settings → Hotkeys](/screenshots/en/hotkeys.webp)

## Send text from a small window (Quick Chat)

You can send text from the Quick Chat window without bringing VRCT-VOX's main window forward. It works even while the main window is minimized. While Quick Chat is open, it stays in front of other windows.

- To open it, assign a key to "Open quick chat" under Settings → "Hotkeys". No key is assigned at first. The "Open input window" button opens it too.
- Enter sends the text, and Shift+Enter adds a line break.
- Esc closes it. Your draft is kept.

Translation, sending to the chatbox and speech work the same as when you send from the main window.

### Linux (Wayland) notes

On native Wayland, keys are registered through the desktop's shortcut service (GlobalShortcuts portal). The first time, the desktop asks you to confirm when you close the settings.

- On desktops without this service, open Quick Chat with the "Open input window" button.
- Bringing the small window in front of the game with a shortcut works on KDE (KWin) only.
- Under XWayland, while you use another Wayland app, hotkeys may not reach VRCT-VOX and Quick Chat may not come to the front.

## Hotkeys

Under Settings → "Hotkeys" you can assign keys to the actions below. None has a key assigned at first.

| Action | What it does |
|---|---|
| Open quick chat | Opens the Quick Chat window |
| Toggle VRCT-VOX visibility | Minimizes the main window; the same key brings it back |
| Toggle Translation, Mic input, Listening | Flips the switch of the same name on the main screen |
| Stop speech | The same as "Stop speech" at the top of the main screen |
| Mute or resume the voice | The same as "Mute" at the top of the main screen |
| Toggle Text to speech (TTS), Voice changer (RVC) | Flips the switch of the same name on the main screen |

Hotkeys are paused while the settings are open, so they don't fire by accident.

On Wayland, a window minimized with the visibility hotkey comes back with the same key. Only KDE (KWin) can bring it in front of other windows.
