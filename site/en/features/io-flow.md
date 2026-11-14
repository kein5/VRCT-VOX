# Inputs and outputs

See, as a graph, where your voice and your chat go with the current settings. For your latest speech and chat, it also shows how long each step took. Every time is in ms (milliseconds).

It only shows things. It changes no setting and no audio route.

## The panel on the main screen

Press "Inputs and outputs" in the bar at the top of the main screen. A panel opens above the conversation log. Press the button again, or "Close", to close it.

![The "Inputs and outputs" panel: lines run from your voice and chat on the left, through translation and speech, to the outputs on the right](/screenshots/en/io-flow.webp)

Inputs are on the left, the steps in the middle and the outputs on the right, joined by lines. Lines from your voice are blue, lines from chat purple.

- Each step shows its setting and time (for example, Translation Japanese → English, 212 ms).
- Speech and voice conversion are shared by voice and chat. A line also runs from your microphone straight into the voice conversion.
- Each output shows the latest time from each input, and what it does: what the chatbox gets (the original, the translation or both), and whether the voice VRChat hears is converted.
- Outputs not used are dashed boxes with no line into them. The reasons are listed under the graph (for example, off in the settings, TTS is off).
- The lines your latest message took are lit. When a new message arrives, a light runs along them once.
- When VRChat uses your microphone without going through VRCT-VOX, a dotted line runs from the microphone.

Under the graph, a timeline for each of your voice and chat shows the latest message's steps as bars, with recent totals and their median.

While the microphone is off, the graph still shows where your voice would go once it is on. In a narrow window the graph scrolls sideways.

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

Under Settings → "VR" → "Desktop caption overlay", turn on "Show inputs and outputs on the desktop". The path your latest inputs took, and how long each step took, appear on the left of the caption window: the input, translation and the outputs, joined by arrows. It works with the captions turned off too.

![Inputs and outputs at the lower left of the screen, with captions on the right](/screenshots/en/flow-on-screen.webp)

The background is a drawing for this page.

- "Inputs shown on the desktop" picks 1 to 3 inputs. It starts at 1.
- While voice conversion runs, its round trip is shown as well.
- Like the captions, it lets clicks through and never takes the focus. It works where the desktop caption overlay works.

## In VR

With the VR UI on, press "Inputs and outputs" on the wrist launcher to open its window. It shows the same graph as the main screen and the times of your newest input. VR cannot scroll, so the boxes show only names and times.

![The "Inputs and outputs" window in VR](/screenshots/en/vr-io-flow.webp)

## What is kept

The times are used only inside the app. They are not written to a file or sent anywhere. Only the recent ones are kept, and they are gone when the app closes.

## What has been checked

- On Windows 11, with a development build, sending a chat showed its times in the panel and on the desktop. Translation and sending to VRChat were off.
- That the time of speech is added to its message was checked by an automated test with a test speech server.
- Microphone speech, voice conversion and the view in VR have not been checked on real hardware yet. The VR window was checked on a test page of the same size.
