// Display only. The backend validates both saved values and save requests.
const isPrivateLanHost = (host) => {
    if (host.startsWith("[")) {
        // URL canonicalizes IPv6; unique-local fc00::/7 and link-local fe80::/10.
        return /^\[(?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f]):/i.test(host);
    }
    const octets = host.split(".").map(Number);
    if (octets.length !== 4 || !octets.every(value => Number.isInteger(value) && value >= 0 && value <= 255)) return false;
    const [first, second] = octets;
    return first === 10 || (first === 172 && second >= 16 && second <= 31)
        || (first === 192 && second === 168) || (first === 169 && second === 254);
};

export const endpointDescription = (url, description, t) => {
    const notices = [description, t("network_privacy.save_notice")];
    try {
        const endpoint = new URL(url);
        if (endpoint.protocol === "http:" && isPrivateLanHost(endpoint.hostname)) notices.push(t("network_privacy.http_warning"));
    } catch { /* Incomplete drafts are validated when saved. */ }
    return notices.filter(Boolean).join(" ");
};

export const isNetworkDisconnected = (value) => value === false;
