# First setup

This page sets up translating text and sending it to the VRChat chatbox. Add speech or captions afterwards with the feature guides.

![The VRCT-VOX main screen](/screenshots/en/main.webp)

## 1. Turn on OSC in VRChat

VRCT-VOX sends text to the VRChat chatbox over OSC. In VRChat, open the Action Menu, go to "Options" → "OSC" and choose "Enabled".

By default VRCT-VOX sends to `127.0.0.1` on port `9000`, which is also VRChat's default, so you usually don't need to change it. To change it, use Settings → "Advanced" → "OSC IP Address" and "OSC Port".

## 2. Choose your languages

In "Language Settings" on the left of the main screen, choose:

- **Your Language**: the language you speak or type.
- **Target Language**: the language to translate into. You can choose up to three.

## 3. Choose your microphone and speaker

Open the settings with the gear at the bottom left of the main screen, then choose under "Device":

- **Mic**: the microphone that picks up your voice. On Linux it lists PipeWire inputs.
- **Speaker**: the output used to listen to other players.

"Auto Select" uses the system default device.

## 4. Send a message

Turn on "Translation" on the left of the main screen. Type in the box at the bottom and send; the translation appears in the chatbox.

::: tip Translation models
Without a local translation model, nothing is translated. Download one under Settings → "Translation", or choose an external translation API. See [Translation](../features/translation).
:::

## Next

- To speak your translations: [Text to speech (TTS)](../features/tts)
- To turn speech into text: [Speech recognition and realtime captions](../features/transcription)
- To read other people's chatboxes: [Chat reading](../features/chat-reading)
