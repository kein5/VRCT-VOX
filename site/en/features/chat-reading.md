# Chat reading (OCR)

Reads the text of chatboxes shown on the VRChat screen, so it can be logged or translated. The settings are under Settings → "Chat Transcribe".

![Settings → Chat Transcribe](/screenshots/en/chat-reading.webp)

## Setup

1. On the "Chat Transcribe" page, download the recognition models. Text recognition uses PaddleOCR's PP-OCR (Apache-2.0). Check the provider, license and size, then agree and download (see [Model downloads](../guide/models)).
2. Start VRChat.
3. When the status at the top of the page says it is ready, turn on "Chat Transcribe" on the main screen.

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

- **Linux**: captures the VRChat window through X11/XWayland. With Proton's defaults VRChat runs under XWayland, so this works as is. Native Wayland windows cannot be captured yet.
- **Windows**: captures the VRChat window.

::: tip If the window is not found
"Window name" is `VRChat` by default. If your client has a different title, change it here.
:::
