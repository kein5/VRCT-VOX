import assert from "node:assert/strict";
import { test } from "node:test";
import { buildObsBrowserSourceUrl, buildWebsocketUrl, isLoopbackHost } from "./obsBrowserSourceUrl.js";

test("OBS copies the token while the visible URL masks it like the WebSocket row", () => {
    const { url, shown } = buildObsBrowserSourceUrl("127.0.0.1", 2232, "secret-token");
    assert.equal(url, "http://127.0.0.1:2232/obs?token=secret-token");
    assert.equal(shown, "http://127.0.0.1:2232/obs?token=••••••••");
    assert.ok(!shown.includes("secret-token"));
});

test("the copied token survives URL query encoding", () => {
    const token = "test+key&part=# /あ";
    const { url, shown } = buildObsBrowserSourceUrl("localhost", 2233, token);
    const parsed = new URL(url);
    assert.equal(parsed.searchParams.get("token"), token);
    assert.deepEqual([...parsed.searchParams.keys()], ["token"]);
    assert.equal(parsed.hash, "");
    assert.equal(shown, "http://localhost:2233/obs?token=••••••••");
});

test("OBS uses the configured host and port and preserves the wildcard fallback", () => {
    for (const [host, expected] of [["127.0.0.2", "http://127.0.0.2"], ["0.0.0.0", "http://127.0.0.1"],
        ["192.168.1.10", "https://192.168.1.10"]]) {
        const { url } = buildObsBrowserSourceUrl(host, 2345, "key");
        assert.equal(url, `${expected}:2345/obs?token=key`);
    }
});

test("beyond this PC both URLs are encrypted, on this PC they stay plain", () => {
    for (const [host, secure] of [["127.0.0.1", false], ["127.10.0.1", false], ["localhost", false],
        ["10.0.0.5", true], ["192.168.1.10", true], ["100.64.0.1", true], ["128.0.0.1", true]]) {
        assert.equal(isLoopbackHost(host), !secure, host);
        assert.equal(buildObsBrowserSourceUrl(host, 2232, "key").url.startsWith(secure ? "https://" : "http://"), true, host);
        assert.equal(buildWebsocketUrl(host, 2231, "key").url.startsWith(secure ? "wss://" : "ws://"), true, host);
    }
});

test("the WebSocket URL masks its token like the OBS one", () => {
    assert.deepEqual(buildWebsocketUrl("192.168.1.10", 2231, "a+b"), {
        url: "wss://192.168.1.10:2231/?token=a%2Bb",
        shown: "wss://192.168.1.10:2231/?token=••••••••",
    });
    assert.deepEqual(buildWebsocketUrl("127.0.0.1", 2231, ""), { url: "ws://127.0.0.1:2231", shown: "ws://127.0.0.1:2231" });
});

test("IPv6 hosts produce a usable token URL", () => {
    for (const host of ["::1", "[::1]"]) {
        const { url, shown } = buildObsBrowserSourceUrl(host, 2232, "key");
        assert.equal(new URL(url).hostname, "[::1]");
        assert.equal(shown, "http://[::1]:2232/obs?token=••••••••");
    }
});

test("an unloaded token uses the same bare-URL fallback as the WebSocket row", () => {
    for (const token of [undefined, null, ""]) {
        assert.deepEqual(buildObsBrowserSourceUrl("127.0.0.1", 2232, token), {
            url: "http://127.0.0.1:2232/obs",
            shown: "http://127.0.0.1:2232/obs",
        });
    }
});
