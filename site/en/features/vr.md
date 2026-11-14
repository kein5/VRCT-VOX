# VR and overlay

You can read translations and captions inside VR or on top of your desktop. The settings are under Settings → "VR".

| Feature | Use it to | Needs |
|---|---|---|
| Subtitle overlay | show captions in your VR view | SteamVR |
| Desktop caption overlay | show captions above VRChat when you play without a headset | Windows or Linux (AppImage) |
| VR UI (beta feature) | control VRCT-VOX inside VR | SteamVR |

## Show captions in VR (subtitle overlay)

Turn on "Subtitle Overlay" in "Quick settings" at the top right of the main screen to show translations and captions in your VR view. It comes from upstream VRCT.

![Settings → VR](/screenshots/en/vr.webp)

- Switch between "Single line" and "Multiple Lines".
- Adjust position and rotation, opacity, size, display time and fade-out time.
- Under "Tracker", choose whether the captions follow the HMD (your headset), the left hand or the right hand.
- "Send Sample Texts To Overlay" shows how it looks.
- "Show Only Translated Messages" hides the original text and shows only the translation.

## Show captions over the screen (desktop caption overlay)

Turn on "Show captions on the desktop" under Settings → "VR" → "Desktop caption overlay". The lines of the message log are drawn above other windows.

![Captions at the bottom of the screen. Two other speakers are marked A and B, and your own words are blue](/screenshots/en/captions-on-screen.webp)

The background is a drawing for this page. In use, the captions sit above whatever is on your screen, such as VRChat.

![The desktop caption overlay section of Settings → VR](/screenshots/en/desktop-captions.webp)

- Your own words (microphone or typing) are blue and the other side's (speakers or chat reading) are purple, the same colours as the message log. The coloured bar beside each line sits at the right for your own words and at the left for the other side.
- When [telling speakers apart](transcription#tell-speakers-apart) is in use, a game audio caption starts with a letter for who spoke (A, B, …) and each person gets their own colour (purple, amber, green, rose, then the same colours again from the fifth person).
- You can click through the captions to the window underneath, and they never take keyboard input away from it.
- You can change where they appear (bottom or top of the screen), the text size, the display duration and how dark the background is.
- They appear on the monitor that holds VRCT-VOX's main window.
- "Show Only Translated Messages" applies to these captions too.
- Next to the captions, you can also show where your inputs went and how long they took. See [Inputs and outputs](io-flow#show-it-on-the-desktop).
- They do not appear above an app in exclusive full screen (a mode in which the app takes over the whole display). VRChat's full screen is a borderless window, so they do appear there.
- On Linux they work when you start the AppImage, also on a Wayland desktop, where the app runs through XWayland. Start the tar.gz with `GDK_BACKEND=x11`; without it the app runs on native Wayland and the section is not shown.

## Use VRCT-VOX in VR (VR UI, beta feature)

"Show the VR UI" shows a launcher on your wrist (a row of buttons) and windows in VR. From there you can turn features on and off and open the log, languages and settings. It works separately from the subtitle overlay. It comes from upstream VRCT.

If you lose the launcher, press "Reset the launcher position and size"; it returns to your left wrist.

::: details What was checked
- On Linux, an automated test on a test X11 screen (no window manager) checked that the caption window appears without a window manager handling it and shows a sent line. Its place above VRChat in full screen on KDE Plasma, and transparency on an NVIDIA GPU, have not been checked yet.
- The desktop caption overlay was checked on Windows 11 above VRChat, both windowed and full screen, with test lines. Captions recognized from game audio were seen in the overlay without VRChat running. Microphone captions were not checked.
- On Linux, the VR UI has only been checked against a simulated SteamVR, not with a real headset.
- The subtitle overlay and the VR UI have not been tested in depth in VRCT-VOX.
:::
