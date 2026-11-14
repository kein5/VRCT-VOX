# Quick Chat and hotkeys

Quick Chat is a small window for sending text without leaving your game, and hotkeys switch features with a key. Both are set up under Settings → "Hotkeys".

![Settings → Hotkeys](/screenshots/en/hotkeys.webp)

## Send text from a small window (Quick Chat)

Send text from a small window without bringing the main window forward. It works even while the main window is minimized. The small window stays on top while it is open.

- **Open**: assign a key to "Open quick chat" under Settings → "Hotkeys". No key is assigned at first. The "Open input window" button opens it too.
- **Send**: Enter sends, Shift+Enter adds a line break.
- **Close**: Esc closes it. Your draft is kept.

Translation, sending to the chatbox and speech work the same as when you send from the main window.

### Linux (Wayland) notes

On native Wayland, keys are registered through the desktop's shortcut service (GlobalShortcuts portal). The first time, a desktop confirmation appears when you close the settings.

- On desktops without the portal, open it with the button.
- Bringing the small window in front of the game with a shortcut works on KDE (KWin) only.
- Under XWayland, the desktop may restrict keys and focus changes while you use another Wayland app.

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
