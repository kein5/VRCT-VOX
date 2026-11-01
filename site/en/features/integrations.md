# OBS and WebSocket

You can pass translations and captions to streaming software or your own tools. The settings are under Settings → "Advanced". By default, both listen only on this PC (`127.0.0.1`).

## OBS browser source

"Enable OBS Browser Source" serves a page that shows translations. Each line fades out after a while.

1. Turn on "Enable OBS Browser Source".
2. Press "OBS URL (click to copy)" to copy the URL. The default is `http://127.0.0.1:2232/obs`.
3. In OBS, add a "Browser" source and paste the URL.

You can change the maximum number of messages, display time, fade-out time, font size and color, and the outline.

## WebSocket

"Enable WebSocket Server" sends translations and captions over WebSocket. The default URL is `ws://127.0.0.1:2231`; copy it with "WebSocket URL (click to copy)".

While the OBS browser source is on, the WebSocket settings cannot be changed. Turn the OBS browser source off first.

::: warning Exposing it to other devices
Setting Host to anything other than `127.0.0.1` lets other devices on your network connect. Change it only when you need to.
:::
