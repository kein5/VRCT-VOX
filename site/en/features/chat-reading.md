# Chat reading (OCR)

Reads the text of chatboxes shown on the VRChat screen, so it can be logged or translated. The settings are under Settings → "VRChat", in "VRChat Chat Transcribe".

![Settings → VRChat, VRChat Chat Transcribe](/screenshots/en/chat-reading.webp)

## Setup

1. In "VRChat Chat Transcribe" on the "VRChat" page, download the recognition models. Text recognition uses PaddleOCR's PP-OCR (Apache-2.0). Check the provider, license and size, then agree and download (see [Model downloads](../guide/models)).
2. Start VRChat.
3. When the status under the "VRChat Chat Transcribe" heading says it is ready, turn on "Chat Transcribe" on the main screen.

## Source language

"auto" reads Japanese, English, Chinese and Latin-script languages with one model. Hangul, Cyrillic, Thai, Arabic and Devanagari need a separate model: choose that script and download its model. Arabic is less accurate for now.

## Where to read

- **Reading area**: the part of the VRChat window to read. Enclosing only where chatboxes appear is faster and picks up less world text. The default is the whole window.
- **Only read chatbox-style text**: keeps only light text on a dark panel, as VRChat's chatbox looks. Turn it off if chatboxes are missed; then world signs and menus are read too.

## Chatbox detector

With "Use the chatbox detector (recommended when installed)" on, VRCT-VOX's own detection model finds each chatbox before it is read. Fewer chatboxes are missed and less world text is misread.

- The model is optional. Without it, chatboxes are found within the reading area.
- The model is a YOLOX-Tiny (about 19 MB, MIT) published on [Hugging Face](https://huggingface.co/kein5/vrct-vox-chatbox-detector). It was trained on VRCT-VOX's own screenshots; it is not the upstream VRCT model.
- Download it from "Chatbox detector" on the same page after reviewing its terms and agreeing ([Model downloads](../guide/models)). The file is used only when its hash matches.
- It runs on this computer's CPU; screen contents are never sent anywhere.
- The reading area and "Only read chatbox-style text" still apply when the detector is used.

## Supported environments

- **Linux**: captures the VRChat window through X11/XWayland. With Proton's defaults VRChat runs under XWayland, so this works as is. A native Wayland window is read after you share it (see below). While SteamVR runs, the headset view is read as well; this has only been checked against a simulated SteamVR.
- **Windows**: captures the VRChat window.

## Sharing a native Wayland window (Linux)

When VRChat runs as a native Wayland window (inside gamescope, or with Wine's Wayland driver), it cannot be found by its name. On a Wayland desktop, the Chat Transcribe page then offers "Share a window (Wayland)" under "Capture target".

1. Press "Share a window…". Your desktop opens its own dialog; pick the VRChat window there.
2. Turn on Chat Transcribe. It reads the shared window instead of looking for one by name.

- VRCT-VOX asks only when you press the button. It does not ask at start-up or on its own.
- The desktop remembers your choice if you leave that option checked in its dialog, so the next "Share a window…" needs no dialog. "Choose another window…" opens the dialog again.
- Sharing ends when you press "Stop sharing", turn Chat Transcribe off, or close VRCT-VOX.
- If the shared window is closed, or you stop sharing from the desktop, VRCT-VOX tells you. Share a window again and reading continues.
- The picture stays on this computer. A few frames per second are copied, and the desktop is asked to leave the mouse pointer out.
- The shared picture includes the window's title bar. The reading area is the same setting used when the window is found by name, applied to the picture with the title bar in it.

::: tip If the window is not found
"Window name" is `VRChat` by default. If your client has a different title, change it here.
:::
