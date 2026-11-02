import assert from "node:assert/strict";
import { test } from "node:test";
import { buildObsBrowserSourceUrl } from "./obsBrowserSourceUrl.js";

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
    for (const [host, expected] of [["192.168.1.10", "192.168.1.10"], ["0.0.0.0", "127.0.0.1"]]) {
        const { url } = buildObsBrowserSourceUrl(host, 2345, "key");
        assert.equal(url, `http://${expected}:2345/obs?token=key`);
    }
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
