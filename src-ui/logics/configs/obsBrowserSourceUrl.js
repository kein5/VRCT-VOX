// The URLs the settings page copies for OBS and for other apps. Where the servers listen
// decides the scheme: on this PC (127.0.0.0/8) plain http and ws; beyond it only https and
// wss, because the backend refuses a LAN host without a certificate (models/websocket/tls.py).
const LOOPBACK = /^(127(\.\d{1,3}){3}|localhost|::1|\[::1\])$/i;
export const isLoopbackHost = host => LOOPBACK.test(String(host ?? ""));

const urlHostOf = host => {
    const address = !host || host === "0.0.0.0" ? "127.0.0.1" : String(host);
    return address.includes(":") && !address.startsWith("[") ? `[${address}]` : address;
};

// Only the clipboard gets the real token; the screen (screenshots, streams) shows dots.
const withToken = (base, token, separator) => ({
    url: token ? `${base}${separator}token=${encodeURIComponent(token)}` : base,
    shown: token ? `${base}${separator}token=••••••••` : base,
});

export const buildObsBrowserSourceUrl = (host, port, token) => {
    const urlHost = urlHostOf(host);
    return withToken(`${isLoopbackHost(urlHost) ? "http" : "https"}://${urlHost}:${port}/obs`, token, "?");
};

export const buildWebsocketUrl = (host, port, token) => {
    const urlHost = urlHostOf(host);
    return withToken(`${isLoopbackHost(urlHost) ? "ws" : "wss"}://${urlHost}:${port}`, token, "/?");
};
