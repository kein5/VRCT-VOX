import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { test } from "node:test";

// Security audit SEC-05: the windows get only the native permissions the UI uses. The UI reads
// and writes no files and makes no HTTP requests of its own, so the fs and http plugins are not
// in the app at all; the shell plugin only starts the backend sidecar, with no arguments, writes
// to its stdin and stops it. Script injected into a window then cannot write or delete files,
// start the sidecar in another mode (`--voice-router-worker`, `--self-check`) or open a site
// the link list does not allow. These tests fail when a permission comes back without a use.
const root = new URL("../../../", import.meta.url);
const read = path => readFileSync(new URL(path, root), "utf8");
const capabilityFolder = new URL("src-tauri/capabilities/", root);
const capabilities = readdirSync(capabilityFolder).filter(name => name.endsWith(".json"))
    .map(name => ({ name, ...JSON.parse(readFileSync(new URL(name, capabilityFolder), "utf8")) }));
const id = permission => typeof permission === "string" ? permission : permission.identifier;
const plugin = permission => id(permission).split(":")[0];

const sources = (folder, found = []) => {
    for (const name of readdirSync(folder)) {
        const path = new URL(name, folder);
        if (statSync(path).isDirectory()) sources(new URL(`${name}/`, folder), found);
        else if (/\.(js|jsx)$/.test(name) && !name.includes(".test.")) found.push(path);
    }
    return found;
};
const ui = sources(new URL("src-ui/", root)).map(path => ({ path: path.pathname, text: readFileSync(path, "utf8") }));

test("no window may use the file system or make HTTP requests through a plugin", () => {
    const granted = capabilities.flatMap(capability => capability.permissions
        .filter(permission => ["fs", "http"].includes(plugin(permission)))
        .map(permission => `${capability.name}: ${id(permission)}`));
    assert.deepEqual(granted, []);
    const native = read("src-tauri/src/lib.rs") + read("src-tauri/Cargo.toml");
    assert.doesNotMatch(native, /tauri[-_]plugin[-_](fs|http)\b/);
    const packages = JSON.parse(read("package.json"));
    assert.deepEqual(Object.keys({ ...packages.dependencies, ...packages.devDependencies })
        .filter(name => /^@tauri-apps\/plugin-(fs|http)$/.test(name)), []);
    const imports = ui.filter(file => /@tauri-apps\/plugin-(fs|http)|plugin:(fs|http)\|/.test(file.text));
    assert.deepEqual(imports.map(file => file.path), []);
});

test("only the main window gets the shell, to start, feed and stop the sidecar", () => {
    const shell = capabilities.flatMap(capability => capability.permissions
        .filter(permission => plugin(permission) === "shell").map(permission => ({ capability, permission })));
    assert.deepEqual([...new Set(shell.map(({ capability }) => capability.identifier))], ["vrct-capability"]);
    assert.deepEqual(shell[0].capability.windows, ["main"]);
    // No execute (run and wait) and no open (the default scope opens any http(s) URL,
    // around the opener's list of sites).
    assert.deepEqual(shell.map(({ permission }) => id(permission)).sort(),
        ["shell:allow-kill", "shell:allow-spawn", "shell:allow-stdin-write"]);
});

test("the sidecar may be started only as the backend, with no arguments", () => {
    const spawn = capabilities.flatMap(capability => capability.permissions)
        .find(permission => id(permission) === "shell:allow-spawn");
    // With `args: false` the shell plugin starts the sidecar with no arguments whatever a window
    // passes (a list is dropped, a single string is refused); `true` or a validator would let a
    // window pick a mode.
    assert.deepEqual(spawn.allow, [{ name: "bin/vrct-vox-sidecar", sidecar: true, args: false }]);
});

test("the UI starts the sidecar the way the scope allows: by name, without arguments", () => {
    const calls = ui.flatMap(file => [...file.text.matchAll(/Command\.(sidecar|create)\(([^)]*)\)/g)]
        .map(match => ({ path: file.path, kind: match[1], args: match[2].trim() })));
    assert.equal(calls.length, 1, JSON.stringify(calls));
    assert.deepEqual({ kind: calls[0].kind, args: calls[0].args }, { kind: "sidecar", args: '"bin/vrct-vox-sidecar"' });
    // Nothing else reaches the shell plugin: no execute, no open, no direct IPC call.
    const other = ui.filter(file => /plugin:shell\||\bopen\s*\}\s*from\s*["']@tauri-apps\/plugin-shell|\.execute\(\)/.test(file.text));
    assert.deepEqual(other.map(file => file.path), []);
});
