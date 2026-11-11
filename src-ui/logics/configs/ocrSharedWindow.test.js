import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import {
    createSharedWindowActions, endedNotice, INITIAL_SHARED_WINDOW, nextRestoreToken, RESTORE_LIMIT_MS, shareErrorKey,
    sharedWindowView, shouldRestoreSharing, shouldStopSharing, startErrorKey,
} from "./ocrSharedWindow.js";

const locale = name => yaml.load(readFileSync(new URL(`../../../locales/${name}.yml`, import.meta.url), "utf8"));
const lookup = (tree, key) => key.split(".").reduce((node, part) => node?.[part], tree);

// The page's pieces around the actions: the atom, the saved token, and a scripted Tauri side.
const harness = ({ token = "", state = {}, commands = {} } = {}) => {
    const page = { state: { ...INITIAL_SHARED_WINDOW, ...state }, token, calls: [], saved: [] };
    const actions = createSharedWindowActions({
        invoke: async (command, args) => {
            page.calls.push([command, args]);
            const answer = commands[command];
            if (answer instanceof Error) throw answer.message;
            return typeof answer === "function" ? answer(args) : answer;
        },
        read: () => page.state,
        write: next => { page.state = next; },
        token: () => page.token,
        saveToken: value => { page.saved.push(value); page.token = value; },
    });
    return { page, actions };
};

test("the section is only shown where a window can be shared", () => {
    assert.deepEqual(sharedWindowView(null), { visible: false });
    assert.deepEqual(sharedWindowView({ ...INITIAL_SHARED_WINDOW, supported: false }), { visible: false });
    const idle = sharedWindowView({ ...INITIAL_SHARED_WINDOW, supported: true });
    assert.deepEqual(idle, {
        visible: true, statusKey: "config_page.ocr.shared_window.status_idle", tone: "neutral", errorKey: null,
        errorCode: null, shareKey: "config_page.ocr.shared_window.share", canShare: true, canStop: false,
    });
});

test("the section says what is shared and which buttons work", () => {
    const asking = sharedWindowView({ supported: true, active: false, busy: true, error: null });
    assert.equal(asking.statusKey, "config_page.ocr.shared_window.status_asking");
    assert.equal(asking.canShare, false);
    assert.equal(asking.canStop, false);
    const active = sharedWindowView({ supported: true, active: true, busy: false, error: null });
    assert.equal(active.statusKey, "config_page.ocr.shared_window.status_active");
    assert.equal(active.tone, "active");
    assert.equal(active.shareKey, "config_page.ocr.shared_window.share_another");
    assert.equal(active.canStop, true);
    const failed = sharedWindowView({ supported: true, active: false, busy: false, error: "screencast_helper_failed" });
    assert.equal(failed.tone, "failed");
    assert.equal(failed.errorKey, "config_page.ocr.shared_window.error_failed");
    assert.equal(failed.errorCode, "screencast_helper_failed");
    // An old error is not shown over a sharing that works.
    assert.equal(sharedWindowView({ supported: true, active: true, busy: false, error: "portal_timeout" }).errorKey, null);
});

test("cancelling the desktop's dialog is not an error", () => {
    assert.equal(shareErrorKey("portal_cancelled"), null);
    assert.equal(shareErrorKey(null), null);
    assert.equal(shareErrorKey("screencast_unsupported"), "config_page.ocr.shared_window.error_unsupported");
    assert.equal(shareErrorKey("portal_timeout"), "config_page.ocr.shared_window.error_timeout");
    assert.equal(shareErrorKey("screencast_stream_timeout"), "config_page.ocr.shared_window.error_timeout");
    assert.equal(shareErrorKey("portal_unavailable"), "config_page.ocr.shared_window.error_failed");
});

test("the restore token follows what the desktop hands out", () => {
    assert.equal(nextRestoreToken("old", { ok: true, token: "new" }), "new");
    // The user chose not to be remembered: nothing to restore next time.
    assert.equal(nextRestoreToken("old", { ok: true, token: null }), "");
    assert.equal(nextRestoreToken("old", { ok: true }), "");
    // The dialog was shown instead of restoring and was cancelled, or the request was refused.
    assert.equal(nextRestoreToken("old", { ok: false, code: "portal_cancelled" }), "");
    assert.equal(nextRestoreToken("old", { ok: false, code: "portal_request_failed" }), "");
    // The request never reached the desktop: the token is still good.
    for (const code of ["portal_unavailable", "portal_timeout", "screencast_helper_missing", "screencast_unavailable"]) {
        assert.equal(nextRestoreToken("old", { ok: false, code }), "old", code);
    }
    assert.equal(nextRestoreToken(undefined, { ok: false, code: "portal_timeout" }), "");
});

test("sharing sends the saved token and keeps the new one", async () => {
    const { page, actions } = harness({ token: "old", state: { supported: true },
        commands: { screencast_start: { restore_token: "new" } } });
    await actions.share();
    assert.deepEqual(page.calls, [["screencast_start", { restoreToken: "old" }]]);
    assert.deepEqual(page.saved, ["new"]);
    assert.deepEqual(page.state, { supported: true, active: true, busy: false, error: null });
});

test("the first sharing has no token to send, and an unchanged token is not saved again", async () => {
    const first = harness({ commands: { screencast_start: { restore_token: "t1" } } });
    await first.actions.share();
    assert.deepEqual(first.page.calls[0], ["screencast_start", { restoreToken: null }]);
    assert.deepEqual(first.page.saved, ["t1"]);
    const same = harness({ token: "t1", commands: { screencast_start: { restore_token: "t1" } } });
    await same.actions.share();
    assert.deepEqual(same.page.saved, []);
});

test("choosing another window does not restore the saved one", async () => {
    const { page, actions } = harness({ token: "old", state: { supported: true, active: true },
        commands: { screencast_start: { restore_token: "other" } } });
    await actions.share({ choose: true });
    assert.deepEqual(page.calls, [["screencast_start", { restoreToken: null }]]);
    assert.deepEqual(page.saved, ["other"]);
});

test("a cancelled dialog leaves no error, and spends only a token that was sent", async () => {
    const commands = { screencast_start: new Error("portal_cancelled"), screencast_support: { supported: true, active: false } };
    const restored = harness({ token: "old", state: { supported: true }, commands });
    await restored.actions.share();
    assert.deepEqual(restored.page.saved, [""]);
    assert.deepEqual(restored.page.state, { supported: true, active: false, busy: false, error: "portal_cancelled" });
    assert.equal(sharedWindowView(restored.page.state).errorKey, null);
    // "Choose another window…" sent no token, so the saved one still restores the earlier window.
    const chosen = harness({ token: "old", state: { supported: true, active: true }, commands });
    await chosen.actions.share({ choose: true });
    assert.deepEqual(chosen.page.saved, []);
    assert.equal(chosen.page.state.active, false);
});

test("a failure keeps the token and shows its reason", async () => {
    const { page, actions } = harness({ token: "old", state: { supported: true },
        commands: { screencast_start: new Error("screencast_helper_missing"), screencast_support: { supported: true, active: false } } });
    await actions.share();
    assert.deepEqual(page.saved, []);
    assert.equal(page.state.error, "screencast_helper_missing");
    assert.equal(page.state.busy, false);
});

test("a second press while the dialog is open asks nothing", async () => {
    const { page, actions } = harness({ state: { supported: true, busy: true } });
    await actions.share();
    assert.deepEqual(page.calls, []);
});

test("refresh and stop report what the app says", async () => {
    const { page, actions } = harness({ commands: { screencast_support: { supported: true, active: true } } });
    await actions.refresh();
    assert.deepEqual(page.state, { supported: true, active: true, busy: false, error: null });
    await actions.stop();
    assert.deepEqual(page.calls.at(-1), ["screencast_stop", undefined]);
    assert.equal(page.state.active, false);
    actions.ended();
    assert.equal(page.state.active, false);
    // Outside the app (browser preview) or on another OS there is nothing to share from.
    const outside = harness({ commands: { screencast_support: new Error("unavailable") } });
    await outside.actions.refresh();
    assert.deepEqual(sharedWindowView(outside.page.state), { visible: false });
});

test("turning chat reading off ends the sharing, and nothing else does", () => {
    assert.equal(shouldStopSharing(true, false, true), true);
    assert.equal(shouldStopSharing(true, false, false), false);   // nothing is shared
    assert.equal(shouldStopSharing(false, false, true), false);   // a start that failed never was on
    assert.equal(shouldStopSharing(false, true, true), false);
    assert.equal(shouldStopSharing(true, true, true), false);
});

test("the user is told when sharing ends without them", () => {
    assert.deepEqual(endedNotice("ended"), { status: "warning", key: "config_page.ocr.shared_window.notice_ended" });
    assert.deepEqual(endedNotice("failed"), { status: "error", key: "config_page.ocr.shared_window.notice_failed" });
    assert.equal(endedNotice(undefined).status, "error");
});

test("English and Japanese have every string the section uses", () => {
    const keys = ["label", "desc", "share", "share_another", "stop", "status_idle", "status_asking", "status_active",
        "error_unsupported", "error_timeout", "error_failed", "notice_ended", "notice_failed"]
        .map(name => `config_page.ocr.shared_window.${name}`)
        .concat(["config_page.ocr.capture_source.shared", "config_page.ocr.runtime.shared_window_ended",
            "common_error.ocr_window_not_found_wayland"]);
    for (const name of ["en", "ja"]) {
        const tree = locale(name);
        for (const key of keys) assert.equal(typeof lookup(tree, key), "string", `${name}: ${key}`);
        assert.match(lookup(tree, "config_page.ocr.shared_window.error_failed"), /\{\{code\}\}/);
        assert.match(lookup(tree, "config_page.ocr.capture_source.shared"), /\{\{status\}\}/);
    }
});

test("only window-not-found reads differently where a window can be shared", () => {
    const wayland = { supported: true }, elsewhere = { supported: false };
    assert.equal(startErrorKey("OCR_DISABLED_WINDOW_NOT_FOUND", wayland), "common_error.ocr_window_not_found_wayland");
    assert.equal(startErrorKey("OCR_DISABLED_WINDOW_NOT_FOUND", elsewhere), null);
    assert.equal(startErrorKey("OCR_DISABLED_WINDOW_NOT_FOUND", null), null);
    assert.equal(startErrorKey("OCR_DISABLED_MODEL_MISSING", wayland), null);
});

test("the remembered window is shared again only when chat reading found nothing to read and nothing is shared", () => {
    const idle = { ...INITIAL_SHARED_WINDOW, supported: true };
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", idle, "saved"), true);
    assert.equal(shouldRestoreSharing("OCR_DISABLED_CAPTURE_UNAVAILABLE", idle, "saved"), true);
    // Never shared before, or the desktop's answer is used up: the user shares from the settings.
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", idle, ""), false);
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", idle, null), false);
    // Not a desktop that can share, a window already shared, or a request still waiting.
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", { ...idle, supported: false }, "saved"), false);
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", { ...idle, supported: null }, "saved"), false);
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", { ...idle, active: true }, "saved"), false);
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", { ...idle, busy: true }, "saved"), false);
    assert.equal(shouldRestoreSharing("OCR_DISABLED_WINDOW_NOT_FOUND", null, "saved"), false);
    // Other reasons chat reading cannot start have nothing to do with the window.
    for (const code of ["OCR_DISABLED_MODEL_MISSING", "OCR_DISABLED_UNKNOWN", undefined]) {
        assert.equal(shouldRestoreSharing(code, idle, "saved"), false);
    }
});

test("restoring sends the saved token, keeps the new one, and reports that a window is shared", async () => {
    const timers = [];
    const page = { state: { ...INITIAL_SHARED_WINDOW, supported: true }, token: "saved", calls: [], saved: [] };
    const actions = createSharedWindowActions({
        invoke: async (command, args) => { page.calls.push([command, args]); return { restore_token: "next" }; },
        read: () => page.state, write: next => { page.state = next; },
        token: () => page.token, saveToken: value => { page.saved.push(value); page.token = value; },
        later: (run, ms) => { timers.push({ run, ms, cancelled: false }); return timers.length - 1; },
        cancel: handle => { timers[handle].cancelled = true; },
    });
    assert.equal(await actions.restore(), true);
    assert.deepEqual(page.calls, [["screencast_start", { restoreToken: "saved" }]]);
    assert.deepEqual(page.saved, ["next"]);
    assert.equal(page.state.active, true);
    assert.equal(page.state.busy, false);
    // The limit was armed for the request and disarmed when the desktop answered.
    assert.deepEqual(timers.map(({ ms, cancelled }) => [ms, cancelled]), [[RESTORE_LIMIT_MS, true]]);
});

test("restoring never asks the desktop without a saved choice or while another request waits", async () => {
    const none = harness({ token: "", state: { supported: true } });
    assert.equal(await none.actions.restore(), false);
    const waiting = harness({ token: "saved", state: { supported: true, busy: true } });
    assert.equal(await waiting.actions.restore(), false);
    assert.deepEqual([...none.page.calls, ...waiting.page.calls], []);
});

test("a desktop that asks instead of restoring is given a limit, then the request is withdrawn", async () => {
    const timers = [];
    let reject;
    const page = { state: { ...INITIAL_SHARED_WINDOW, supported: true }, token: "saved", calls: [], saved: [] };
    const actions = createSharedWindowActions({
        invoke: (command, args) => {
            page.calls.push([command, args]);
            if (command === "screencast_start") return new Promise((_, fail) => { reject = fail; });
            if (command === "screencast_stop") reject("portal_cancelled");
            return Promise.resolve(command === "screencast_support" ? { supported: true, active: false } : undefined);
        },
        read: () => page.state, write: next => { page.state = next; },
        token: () => page.token, saveToken: value => { page.saved.push(value); page.token = value; },
        later: (run, ms) => { timers.push({ run, ms }); return timers.length - 1; },
        cancel: () => {},
    });
    const restoring = actions.restore({ limit: 5000 });
    await Promise.resolve();
    assert.equal(page.state.busy, true);
    assert.equal(timers[0].ms, 5000);
    timers[0].run();
    assert.equal(await restoring, false);
    assert.deepEqual(page.calls.map(([command]) => command), ["screencast_start", "screencast_stop", "screencast_support"]);
    // The desktop did not restore from the token, so it is not sent again.
    assert.deepEqual(page.saved, [""]);
    assert.equal(page.state.active, false);
    assert.equal(page.state.busy, false);
    // Withdrawing is not an error to show in the settings.
    assert.equal(sharedWindowView(page.state).errorKey, null);
});

test("a failed restore leaves the reason in the settings and the token for the next try", async () => {
    const { page, actions } = harness({ token: "saved", state: { supported: true },
        commands: { screencast_start: new Error("screencast_stream_timeout"), screencast_support: { supported: true, active: false } } });
    assert.equal(await actions.restore(), false);
    assert.deepEqual(page.saved, []);
    assert.equal(sharedWindowView(page.state).errorKey, "config_page.ocr.shared_window.error_timeout");
});
