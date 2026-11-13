# VR and overlay

You can read translations and captions and control features inside VR. The settings are under Settings → "VR". Both use SteamVR and come from upstream VRCT.

![Settings → VR](/screenshots/en/vr.webp)

## Subtitle overlay

Turn it on with "Overlay(VR)" at the top of the main screen to show translations and captions in your VR view.

- Switch between "Single line" and "Multiple Lines".
- Adjust position and rotation, opacity, size, display time and fade-out time.
- Under "Tracker", choose whether it follows the HMD, the left hand or the right hand.
- "Send Sample Texts To Overlay" shows how it looks.
- "Show Only Translated Messages" hides the original text and shows only the translation.

## Desktop caption overlay

When you play VRChat without a headset, the captions can be drawn on the desktop. Turn on "Show captions on the desktop" under Settings → "VR" → "Desktop caption overlay". It is available on Windows.

- The lines of the message log are drawn above other windows. A bar at the left tells your own words from the other side's.
- Clicks pass through the captions and they never take the focus, so the window underneath stays usable.
- You can change where they appear (bottom or top of the screen), the text size, the display duration and how dark the background is.
- They appear on the monitor that holds VRCT-VOX's main window.
- "Show Only Translated Messages" applies to these captions too.

## VR UI (beta feature)

"Show the VR UI" shows a wrist launcher and windows in VR for turning features on and off and for the log, languages and settings. It works separately from the subtitle overlay. If you lose the launcher, press "Reset the launcher position and size"; it returns to your left wrist.

::: warning Testing status
VR features have not been tested in depth in VRCT-VOX. On Linux, the VR UI has only been checked against a simulated SteamVR, not with a real headset. The desktop caption overlay was checked on Windows 11 above other windows; how it looks above the VRChat window has not been checked.
:::
