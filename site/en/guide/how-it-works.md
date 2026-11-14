# How voice and text flow

VRCT-VOX takes in voice and text, turns them into text, translates them or speaks them, and hands them to VRChat or to your screen. This page shows the whole flow in one picture.

![How voice and text flow. The top lane: your voice and typed chat go through speech recognition and translation to the VRChat chatbox and the virtual microphone. The bottom lane: their voice and their chatbox go through speech recognition or chat reading and translation to the captions and log, and to OBS](/diagrams/how-it-works-en.svg)

## From you to them

The top lane of the picture.

- Typed chat goes through translation to the VRChat chatbox.
- Your voice becomes text through speech recognition (ASR), and goes the same way through translation to the chatbox.
- Text to speech (TTS) can speak the translated text into the virtual microphone.
- The voice changer (RVC) can change your voice and send it to the virtual microphone.
- Speech sent through the voice changer carries your translated words in your changed voice (the dotted line).

With translation off, the original text goes on as it is.

## From them to you

The bottom lane of the picture.

- Their voice (the game's sound) becomes text through speech recognition (ASR).
- The text in their chatbox becomes text through chat reading (OCR).
- Both go through translation to the main screen's log and the captions. They can also go to OBS and WebSocket.

What you hear from them, and the text made from it, is never sent on to your microphone or the chatbox.

## Why a virtual microphone is needed

VRChat hears only the microphone you choose in VRChat. For the voice VRCT-VOX makes (speech, or your changed voice) to reach VRChat, VRChat has to receive it as a microphone. A virtual microphone does that: it passes the sound an app plays to other apps as if it came from a microphone.

- On Linux, VRCT-VOX can prepare a virtual microphone it manages ([Linux audio route](./linux-audio)).
- On Windows, install a virtual cable such as VB-CABLE separately.

In VRChat, choose the virtual microphone (the recording end of the virtual cable) as the microphone.

## Which switch joins which line

The switches on the main screen join or cut the lines of the picture.

| Switch | Line it joins |
|---|---|
| Translation | Text through translation |
| Mic input | Your voice → speech recognition (ASR) |
| Listening | Their voice → speech recognition (ASR) |
| Chat reading (OCR) | Their chatbox → chat reading |
| Text to speech (TTS) | Text → text to speech → the output (a virtual microphone, for example) |
| Voice changer (RVC) | Your voice → voice changer → virtual microphone |

Whether text goes to the chatbox is set by "Send Message To VRChat" under Settings → "VRChat".

## Check where things go with your settings

Press "Inputs and outputs" in the bar at the top of the main screen. A graph shows where your voice and chat go with your settings now, and how long each step took.

![The "Inputs and outputs" panel](/screenshots/en/io-flow.webp)

See [Inputs and outputs](../features/io-flow).
