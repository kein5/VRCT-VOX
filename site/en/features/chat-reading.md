# Chat reading (OCR)

Reads the text of chatboxes shown on the VRChat screen, so it can be logged or translated. The settings are under Settings → "Chat reading (OCR)".

## What you need

- The text recognition models: PaddleOCR's PP-OCR (Apache-2.0). They are not bundled; download them from the settings ([Model downloads](../guide/models)). Models of your own cannot replace them.
- VRChat

## First steps

1. Under Settings → "Chat reading (OCR)", download the recognition models. Check the provider, license and size, then agree and download.

   ![Settings → Chat reading (OCR)](/screenshots/en/chat-reading.webp)

2. Start VRChat.
3. When the status under the "Reading VRChat's chat" heading at the top of the page says it is ready, turn on "Chat reading (OCR)" on the main screen.

## Choose the source language

"auto" reads Japanese, English, Chinese and Latin-script languages with one model. Hangul, Cyrillic, Thai, Arabic and Devanagari need a separate model: choose that script and download its model. Arabic is less accurate for now.

## Narrow where to read

- "Reading area" is the part of the VRChat window to read. Enclosing only where chatboxes appear is faster and picks up less world text. The default is the whole window.
- "Only read chatbox-style text" keeps only light text on a dark panel, as VRChat's chatbox looks. Turn it off if chatboxes are missed; then world signs and menus are read too.

## Find each chatbox before reading it

With "Use the chatbox detector (recommended when installed)" on, VRCT-VOX's own detection model finds each chatbox before it is read. Fewer chatboxes are missed and less world text is misread.

- The model is optional. Without it, chatboxes are found within the reading area.
- The model is a YOLOX-Tiny (about 19 MB, MIT) published on [Hugging Face](https://huggingface.co/kein5/vrct-vox-chatbox-detector). It was trained on VRCT-VOX's own screenshots; it is not the upstream VRCT model.
- Download it from "Chatbox detector" on the same page after reviewing its terms and agreeing ([Model downloads](../guide/models)). The file is used only when its hash matches.
- It runs on this computer's CPU; screen contents are never sent anywhere.
- The reading area and "Only read chatbox-style text" still apply when the detector is used.

## Supported environments

- On Linux it captures the VRChat window through X11/XWayland. With Proton's defaults VRChat runs under XWayland, so this works as is. A native Wayland window is read after you share it (see below). While SteamVR runs, the headset view is read as well; this has only been checked against a simulated SteamVR.
- On Windows it captures the VRChat window.

## Share a native Wayland window (Linux)

When VRChat runs as a native Wayland window (inside gamescope, or with Wine's Wayland driver), it cannot be found by its name. On a Wayland desktop, the Chat reading (OCR) page then offers "Share a window (Wayland)" under "Capture target".

1. Press "Share a window…". Your desktop opens its own dialog; pick the VRChat window there.
2. Turn on Chat reading (OCR). It reads the shared window instead of looking for one by name.

- VRCT-VOX asks the desktop when you press the button, and when you turn chat reading on again. It never asks at start-up.
- The desktop remembers your choice if you leave that option checked in its dialog, so the next "Share a window…" needs no dialog. "Choose another window…" opens the dialog again.
- Sharing ends when you press "Stop sharing", turn chat reading off, or close VRCT-VOX.
- When you turn chat reading on again and no VRChat window is found by its name, the window your desktop remembers is shared again. If the desktop remembers it, no dialog appears. If a dialog stays open for 15 seconds, VRCT-VOX gives up and tells you; share from "Share a window…" in that case.
- If the shared window is closed, or you stop sharing from the desktop, VRCT-VOX tells you. Share a window again and reading continues.
- The picture stays on this computer. A few frames per second are copied, and the desktop is asked to leave the mouse pointer out.
- The shared picture includes the window's title bar. The reading area is the same setting used when the window is found by name, applied to the picture with the title bar in it.

## Stop

Turn off "Chat reading (OCR)" on the main screen. Sharing a Wayland window ends with it.

## When it does not work

- "Window name" is `VRChat` by default. If your client has a different title, change it here.
- If it says the window was not found, see [Troubleshooting](../guide/troubleshooting).
