# OBS and WebSocket

You can pass translations and captions to streaming software or your own tools. The settings are under Settings → "Advanced". By default, both listen only on this PC (`127.0.0.1`).

![Settings → Advanced](/screenshots/en/advanced.webp)

## Show captions in a stream (OBS browser source)

"Enable OBS Browser Source" serves a page that shows translations. Each line fades out after a while.

1. Turn on "Enable OBS Browser Source".
2. Press "OBS URL (click to copy)" in the app to copy the URL, including its key. With the default host and port, it has the form `http://127.0.0.1:2232/obs?token=<key>`. The key is masked on screen but included when copied.
3. In OBS, add a "Browser" source and paste the URL.

If you already use an OBS browser source, copy the URL from the app again and replace the URL in OBS. URLs without the key no longer work. Keep the copied URL private: its key grants access to conversation messages.

You can change the maximum number of messages, display time, fade-out time, font size and color, and the outline.

## Receive them in your own tools (WebSocket)

"Enable WebSocket Server" sends translations and captions over WebSocket. With the default host and port, the URL has the form `ws://127.0.0.1:2231/?token=<key>`; copy it with "WebSocket URL (click to copy)". It uses the same key as the OBS URL.

While the OBS browser source is on, the WebSocket settings cannot be changed. Turn the OBS browser source off first.

::: warning Exposing it to other devices
Setting Host to anything other than `127.0.0.1` lets other devices on your network connect. Change it only when you need to.
:::
