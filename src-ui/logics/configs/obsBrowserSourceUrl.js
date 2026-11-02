export const buildObsBrowserSourceUrl = (host, port, token) => {
    const address = !host || host === "0.0.0.0" ? "127.0.0.1" : String(host);
    const urlHost = address.includes(":") && !address.startsWith("[") ? `[${address}]` : address;
    const base = `http://${urlHost}:${port}/obs`;
    return {
        url: token ? `${base}?token=${encodeURIComponent(token)}` : base,
        // Match the WebSocket row: only the clipboard gets the real token.
        shown: token ? `${base}?token=••••••••` : base,
    };
};
