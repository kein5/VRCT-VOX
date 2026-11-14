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
- Under "Tracker", choose whether it follows the HMD, the left hand or the right hand.
- "Send Sample Texts To Overlay" shows how it looks.
- "Show Only Translated Messages" hides the original text and shows only the translation.

## Show captions over the screen (desktop caption overlay)

Turn on "Show captions on the desktop" under Settings → "VR" → "Desktop caption overlay". The lines of the message log are drawn above other windows.

![Captions at the bottom of the screen. Two other voices carry the labels A and B, and your own words are blue](/screenshots/en/captions-on-screen.webp)

The background is a drawing for this page. In use, the captions sit above whatever is on your screen, such as VRChat.

![The desktop caption overlay section of Settings → VR](/screenshots/en/desktop-captions.webp)

- Your own words (microphone or typing) are blue and the other side's (speakers or chat reading) are purple, the same colours as the message log. The bar sits at the right for your own words and at the left for the other side.
- With [speaker labels](transcription#label-who-speaks), a game audio caption starts with the label of who spoke (A, B, …) and each voice has its own colour (purple, amber, green, rose, then over again from the fifth voice).
- Clicks pass through the captions and they never take the focus, so the window underneath stays usable.
- You can change where they appear (bottom or top of the screen), the text size, the display duration and how dark the background is.
- They appear on the monitor that holds VRCT-VOX's main window.
- "Show Only Translated Messages" applies to these captions too.
- The same window can also show where your inputs went and how long they took. See [Inputs and outputs](io-flow#show-it-on-the-desktop).
- They do not appear above an app in exclusive full screen. VRChat's full screen is a borderless window, so they do appear there.
- On Linux they work when you start the AppImage, also on a Wayland desktop, where the app runs through XWayland. Start the tar.gz with `GDK_BACKEND=x11`; without it the app runs on native Wayland and the section is not shown.

## Use VRCT-VOX in VR (VR UI, beta feature)

"Show the VR UI" shows a wrist launcher and windows in VR for turning features on and off and for the log, languages and settings. It works separately from the subtitle overlay. It comes from upstream VRCT.

If you lose the launcher, press "Reset the launcher position and size"; it returns to your left wrist.

::: details What was checked
- On Linux, an automated test on a test X11 screen (no window manager) checked that the caption window is unmanaged and shows a sent line. Its place above VRChat in full screen on KDE Plasma, and transparency on an NVIDIA GPU, have not been checked yet.
- The desktop caption overlay was checked on Windows 11 above VRChat, both windowed and full screen, with test lines. Captions recognized from game audio were seen in the overlay without VRChat running. Microphone captions were not checked.
- On Linux, the VR UI has only been checked against a simulated SteamVR, not with a real headset.
- The subtitle overlay and the VR UI have not been tested in depth in VRCT-VOX.
:::
