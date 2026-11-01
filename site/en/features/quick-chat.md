# Quick Chat and hotkeys

## Quick Chat

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

Under Settings → "Hotkeys" you can assign keys to:

- toggling VRCT-VOX visibility (minimize or activate)
- turning Translation on and off
- turning Voice2Chatbox on and off
- turning Speaker2Log on and off
- opening Quick Chat

Hotkeys are paused while the settings are open, so they don't fire by accident.
