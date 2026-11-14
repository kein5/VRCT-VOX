# OBS and WebSocket

You can pass translations and captions to streaming software or your own tools. The settings are under Settings → "Advanced". By default, both can be reached only from this PC (`127.0.0.1`).

![Settings → Advanced](/screenshots/en/advanced.webp)

## Show captions in a stream (OBS browser source)

"Enable OBS Browser Source" serves a page for OBS to load, which shows translations. Each line fades out after a while.

1. Turn on "Enable OBS Browser Source".
2. Press "OBS URL (click to copy)" in the app to copy the URL, including its key. With the default host and port, it has the form `http://127.0.0.1:2232/obs?token=<key>`. The key is masked on screen but included when copied.
3. In OBS, add a "Browser" source and paste the URL.

If you already use an OBS browser source, copy the URL from the app again and replace the URL in OBS. URLs without the key no longer work. Keep the copied URL private: its key grants access to conversation messages.

You can change the maximum number of messages, display time, fade-out time, font size and color, and the outline.

## Receive them in your own tools (WebSocket)

"Enable WebSocket Server" sends translations and captions over WebSocket, for your own tools and similar apps. With the default host and port, the URL has the form `ws://127.0.0.1:2231/?token=<key>`; copy it with "WebSocket URL (click to copy)". It uses the same key as the OBS URL.

While the OBS browser source is on, the WebSocket settings cannot be changed. Turn the OBS browser source off first.

## Use it from other PCs

From OBS or tools on other PCs, the connection is encrypted. For that you need a certificate and private key (PEM) for this PC's LAN IP address. Without a certificate, other PCs cannot connect.

![The WebSocket rows under Advanced](/screenshots/en/websocket.webp)

1. Enter the paths under "Certificate file" and "Private key file" and save. A pair that does not work is not saved, and the reason is shown.
2. Enter this PC's LAN IP address (for example `192.168.1.10`) under "WebSocket Host (IPv4)" and save.
3. Copy the WebSocket and OBS URLs again. They now start with `wss://` and `https://`.

The PCs and OBS that connect must trust the certificate. If you made the certificate yourself, add its issuer's certificate on the PCs that connect. A private key with a passphrase cannot be used.

With the host set back to `127.0.0.1`, it works on this PC only, without a certificate. If an earlier version had a LAN address set, the host goes back to `127.0.0.1` at startup and the app tells you.

::: warning Exposing it to other devices
Other devices on your network can then connect too. Change it only when you need to.
:::

## Make a new key

If someone else may have seen a copied URL, press "Make a new connection key". After you confirm, the key changes and the old URLs stop working at once. Open WebSocket connections are closed too.

Afterwards, copy the WebSocket and OBS URLs again and set them in OBS and your tools.
