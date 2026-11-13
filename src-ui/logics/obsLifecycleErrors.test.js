import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
import { loadBridgeRoutes } from "./test/bridgeHarness.js";

const failures = [
    ["/set/enable/obs_browser_source", "OBS_BROWSER_SOURCE_PORT_UNAVAILABLE", "EnableObsBrowserSource", false],
    ["/set/enable/obs_browser_source", "OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE", "EnableObsBrowserSource", false],
    ["/set/enable/obs_browser_source", "WEBSOCKET_SERVER_UNAVAILABLE", "EnableObsBrowserSource", false],
    ["/set/data/obs_browser_source_port", "OBS_BROWSER_SOURCE_PORT_INVALID", "ObsBrowserSourcePort", 2232],
    ["/set/data/obs_browser_source_port", "OBS_BROWSER_SOURCE_PORT_UNAVAILABLE", "ObsBrowserSourcePort", 2232],
    ["/set/data/obs_browser_source_port", "OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE", "ObsBrowserSourcePort", 2232],
    ["/set/data/websocket_host", "OBS_BROWSER_SOURCE_HOST_UNAVAILABLE", "WebsocketHost", "127.0.0.1"],
];

for (const language of ["en", "ja"]) {
    const translation = yaml.load(readFileSync(new URL(`../../locales/${language}.yml`, import.meta.url), "utf8"));
    for (const [endpoint, error_code, field, previous] of failures) {
        test(`${language}: ${error_code} on ${endpoint} settles only its initiating field`, async context => {
            context.mock.method(console, "error", () => {});
            const i18n = i18next.createInstance();
            await i18n.init({ lng: language, resources: { [language]: { translation } } });
            const s = await loadBridgeRoutes(undefined, i18n);
            const values = { EnableObsBrowserSource: false, ObsBrowserSourcePort: 2232,
                EnableWebsocket: true, WebsocketHost: "127.0.0.1" };
            const atoms = Object.fromEntries(Object.keys(values).map(name => [name, s.stores.dynamicStoreRegistry[`Atom_${name}`]]));
            for (const [name, atom] of Object.entries(atoms)) {
                s.runtime.store.set(atom, { state: "pending", data: values[name] });
            }
            s.receiveRoutes({ endpoint, status: 400, result: { error_code, data: previous, message: "backend fallback" } });
            for (const [name, atom] of Object.entries(atoms)) {
                assert.deepEqual(s.runtime.store.get(atom), {
                    state: name === field ? "ok" : "pending", data: values[name],
                });
            }
            const key = `backend_errors.${error_code}`;
            assert.equal(i18n.exists(key), true, `missing ${language} cause text`);
            assert.deepEqual(s.notices, [{ type: "error", key: i18n.t(key), options: { category_id: error_code } }]);
            assert.deepEqual(s.reads, ["/get/data/websocket_server", "/get/data/obs_browser_source"]);
            // Failed restoration is reported by the dependent state reads, not
            // by putting a boolean into the failed port/host field.
            s.receiveRoutes({ endpoint: "/get/data/websocket_server", status: 200, result: false });
            s.receiveRoutes({ endpoint: "/get/data/obs_browser_source", status: 200, result: false });
            assert.deepEqual(s.runtime.store.get(atoms.EnableObsBrowserSource), { state: "ok", data: false });
            assert.deepEqual(s.runtime.store.get(atoms.EnableWebsocket), { state: "ok", data: false });
        });
    }
}

test("a standalone WebSocket enable failure still settles its own switch", async context => {
    context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    const ws = s.stores.dynamicStoreRegistry.Atom_EnableWebsocket;
    const obs = s.stores.dynamicStoreRegistry.Atom_EnableObsBrowserSource;
    s.runtime.store.set(ws, { state: "pending", data: false });
    s.runtime.store.set(obs, { state: "pending", data: false });
    s.receiveRoutes({ endpoint: "/set/enable/websocket_server", status: 400,
        result: { error_code: "WEBSOCKET_SERVER_UNAVAILABLE", data: false } });
    assert.deepEqual(s.runtime.store.get(ws), { state: "ok", data: false });
    assert.deepEqual(s.runtime.store.get(obs), { state: "pending", data: false });
    assert.deepEqual(s.reads, []);
});

test("a successful OBS enable re-reads the WebSocket switch it may have started", async () => {
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/set/enable/obs_browser_source", status: 200, result: true });
    assert.deepEqual(s.reads, ["/get/data/websocket_server"]);
});
