import assert from "node:assert/strict";
import { test } from "node:test";
import { loadBridgeRoutes } from "./test/bridgeHarness.js";
import { expectBackendExit } from "./common/sidecarExitExpectation.js";
import { createSidecarSessionOwner } from "./common/sidecarSession.js";

test("null init getter retains its real default, applies later fields, reaches ready and warns once", async context => {
    const errors = context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    const hostAtom = s.stores.dynamicStoreRegistry.Atom_MicHostList;
    const before = s.runtime.store.get(hostAtom);
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selectable_mic_host_list": null,
        "/get/data/selectable_mic_device_list": ["Microphone"],
        "/get/data/selected_mic_host": "System",
    } });
    assert.strictEqual(s.runtime.store.get(hostAtom), before);
    assert.deepEqual(before.data, []);
    assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_MicDeviceList).data, { Microphone: "Microphone" });
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SelectedMicHost).data, "System");
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.deepEqual(s.notices, [{ type: "warning", key: "common_warning.startup_degraded",
        options: { hide_duration: null, category_id: "startup_degraded" } }]);
    const fieldErrors = errors.mock.calls.filter(call => call.arguments[0] === "Sidecar initialization field unavailable");
    assert.equal(fieldErrors.length, 1);
    assert.equal(fieldErrors[0].arguments[1], "/get/data/selectable_mic_host_list");
});

test("malformed arrays and individual handler errors do not abort remaining initialization", async context => {
    const errors = context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selectable_mic_host_list": {},
        // A malformed member throws in the real arrayToObject transform.
        "/get/data/selectable_mic_device_list": [{ toString: null }],
        "/get/data/selected_mic_host": "System",
    } });
    assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_MicDeviceList).data, []);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SelectedMicHost).data, "System");
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.equal(s.notices.length, 1);
    assert.equal(errors.mock.calls.filter(call => call.arguments[0] === "Sidecar initialization field unavailable").length, 2);
});

test("a valid initialization finishes without a degraded notice", async () => {
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selectable_mic_host_list": [], "/get/data/auto_mic_select": false,
    } });
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_EnableAutoMicSelect).data, false);
    assert.deepEqual(s.notices, []);
});

test("unset scalar values (no API key, no model) are applied and do not warn", async context => {
    const errors = context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/deepl_auth_key": null, "/get/data/selected_openai_model": null,
        "/get/data/selectable_mic_host_list": [],
    } });
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.deepEqual(s.notices, []);
    assert.equal(errors.mock.calls.filter(call => call.arguments[0] === "Sidecar initialization field unavailable").length, 0);
});

for (const endpoint of ["/run/update_software", "/run/update_cuda_software"]) {
    for (const status of [400, 404, 409, 423, 500]) test(`${endpoint} ${status} clears expected exit and a later crash is reported`, async context => {
        context.mock.method(console, "error", () => {});
        const s = await loadBridgeRoutes(), events = {}, crashes = [];
        const owner = createSidecarSessionOwner({ store: s.stores.store,
            createCommand: () => ({ on: (name, fn) => { events[name] = fn; },
                stdout: { on: () => {} }, stderr: { on: () => {} }, spawn: async () => ({}) }),
            setInterval: () => 1, clearInterval: () => {},
        });
        const detach = owner.attach(() => ({ setStartupState: () => {}, beginStartup: () => {}, started: () => {},
            backendStopped: s.backendStopped, unexpectedExit: event => crashes.push(event) }));
        await s.stores.store.backend_session.completion;
        const session = s.stores.store.backend_session;
        expectBackendExit(session, endpoint);
        s.runtime.store.set(s.stores.Atom_IsSoftwareUpdating, { state: "ok", data: true });
        s.receiveRoutes({ endpoint, status, result: { error_code: "UPDATE_SOFTWARE_DOWNLOAD" } });
        assert.equal(session.expectedExits.size, 0);
        assert.equal(s.runtime.store.get(s.stores.Atom_IsSoftwareUpdating).data, false);
        events.close({ code: 1 });
        assert.equal(crashes.length, 1);
        detach();
    });
}
