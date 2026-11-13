import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync(0, "utf8");
const start = html.indexOf("<script>") + "<script>".length;
const script = html.slice(start, html.indexOf("</script>", start));
const styles = new Map();
// Inspect the production page's settings updater without a browser or socket.
const context = { window: {}, location: { hostname: "localhost" },
    document: { getElementById: () => ({}), documentElement: { style: { setProperty: (key, value) => styles.set(key, value) } } },
    WebSocket: class { addEventListener() {} },
};
vm.runInNewContext(script.replace("const addMessage =", "window.settings = SETTINGS; window.apply = applySettings; const addMessage ="), context);
for (const [wire, minimum, maximum, css, unit] of [
    ["maxMessages", 1, 50, null, ""],
    ["displayDuration", 1, 120, "--display-duration", "s"],
    ["fadeoutDuration", 0, 120, "--fadeout-duration", "s"],
    ["fontSize", 10, 200, "--font-size", "px"],
    ["outlineThickness", 0, 20, "--outline-size", "px"],
]) {
    const current = () => css ? styles.get(css) : context.window.settings.maxMessages;
    for (const value of [minimum, maximum]) {
        context.window.apply({ [wire]: value });
        assert.equal(current(), css ? `${value}${unit}` : value);
    }
    for (const value of [minimum - 1, maximum + 1, 1.5, true, null, "20"]) {
        const previous = current();
        context.window.apply({ [wire]: value });
        assert.equal(current(), previous, `${wire} must reject ${value}`);
    }
}
