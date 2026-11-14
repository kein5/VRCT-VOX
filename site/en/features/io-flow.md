# Inputs and outputs

See where your voice and your chat go with the current settings. For your latest speech and chat, it also shows how long each step took. Every time is in ms (milliseconds).

It only shows things. It changes no setting and no audio route.

## The panel on the main screen

Press "Inputs and outputs" in the bar at the top of the main screen. A panel opens above the conversation log. Press the button again, or "Close", to close it.

![The "Inputs and outputs" panel: your voice on the left, chat on the right, each with where it goes and how long it took](/screenshots/en/io-flow.webp)

Your voice is on the left and chat on the right. Each shows:

- the speech recognition and translation settings (for example, Realtime, Japanese → English);
- where it goes and what happens there: what the chatbox gets (the original, the translation or both), and for speech, which voice and where it plays;
- the outputs not used, with the reason (for example, off in the settings, TTS is off);
- the times of the latest one: a bar for each step and the moment each output was reached, on the same scale;
- recent totals and their median.

While the microphone is off, the panel still shows where your voice would go once it is on.

### What the times mean

| Item | Meaning |
|---|---|
| Speech recognition | How long recognizing the cut-out speech took. Shown only without realtime speech recognition. |
| Waiting | From receiving the realtime recognition result to starting on it |
| Translation | How long translation took |
| Handing to outputs | From the end of translation until the message was handed to the chatbox, captions and the rest |
| Chatbox | When the message was sent to VRChat |
| Speech | When the first sound of speech was played. Through voice conversion, when it began going to the conversion. |
| Voice conversion (guide) | The conversion's round trip: the recent median, not this message's own time |

### Where the count starts

Times count from a point that depends on the input. The panel says which.

- A chat counts from when the app accepted it.
- Realtime speech recognition counts from its final result. The app does not know when you stopped speaking, so the time from then to the final result is not included.
- Other speech recognition counts from the start of recognition.

## On the desktop

Under Settings → "VR" → "Desktop caption overlay", turn on "Show inputs and outputs on the desktop". Where your latest inputs went, and how long each took, appear on the left of the caption window. It works with the captions turned off too.

![Inputs and outputs at the lower left of the screen, with captions on the right](/screenshots/en/flow-on-screen.webp)

The background is a drawing for this page.

- "Inputs shown on the desktop" picks 1 to 3 inputs. It starts at 1.
- While voice conversion runs, its round trip is shown as well.
- Like the captions, it lets clicks through and never takes the focus. It works where the desktop caption overlay works.

## In VR

With the VR UI on, press "Inputs and outputs" on the wrist launcher to open its window. It shows where your voice and chat go, and the times of your newest input.

![The "Inputs and outputs" window in VR](/screenshots/en/vr-io-flow.webp)

## What is kept

The times are used only inside the app. They are not written to a file or sent anywhere. Only the recent ones are kept, and they are gone when the app closes.

## What has been checked

- On Windows 11, with a development build, sending a chat showed its times in the panel and on the desktop. Translation and sending to VRChat were off.
- That the time of speech is added to its message was checked by an automated test with a test speech server.
- Microphone speech, voice conversion and the view in VR have not been checked on real hardware yet. The VR window was checked on a test page of the same size.
