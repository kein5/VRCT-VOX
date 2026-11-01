# Chat reading (OCR)

Reads the text of chatboxes shown on the VRChat screen, so it can be logged or translated. The settings are under Settings → "Chat Transcribe".

## Setup

1. On the "Chat Transcribe" page, download the recognition models. Text recognition uses PaddleOCR's PP-OCR (Apache-2.0). Check the provider, license and size, then agree and download (see [Model downloads](../guide/models)).
2. Start VRChat.
3. When the status at the top of the page says it is ready, turn on "Chat Transcribe" on the main screen.

## Source language

"auto" reads Japanese, English, Chinese and Latin-script languages with one model. Hangul, Cyrillic, Thai, Arabic and Devanagari need a separate model: choose that script and download its model. Arabic is less accurate for now.

## Where to read

- **Reading area**: the part of the VRChat window to read. Enclosing only where chatboxes appear is faster and picks up less world text. The default is the whole window.
- **Only read chatbox-style text**: keeps only light text on a dark panel, as VRChat's chatbox looks. Turn it off if chatboxes are missed; then world signs and menus are read too.

<!-- TODO(#22): VRCT-VOX's own chatbox detector arrives with PR #22. Once it is merged, replace the note below with a description. -->
::: info Chatbox detector (planned)
VRCT-VOX's own chatbox detection model is planned as a consented download. It is not part of this version yet.
:::

## Supported environments

- **Linux**: captures the VRChat window through X11/XWayland. With Proton's defaults VRChat runs under XWayland, so this works as is. Native Wayland windows cannot be captured yet.
- **Windows**: captures the VRChat window.

::: tip If the window is not found
"Window name" is `VRChat` by default. If your client has a different title, change it here.
:::
