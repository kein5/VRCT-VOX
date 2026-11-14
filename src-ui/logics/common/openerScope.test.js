import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { test } from "node:test";

// Second security audit SEC-02: the main window may open only the URLs listed in
// src-tauri/capabilities/vrct_capability.json. Every URL written in the UI must be on that list,
// so a new link fails here until it is added on purpose. Templates are cut at their first
// placeholder. The glob matching follows the glob crate with default options (`*` also crosses
// `/`); src-tauri/src/opener_scope_tests.rs checks the list with the crate itself.
const root = new URL("../../../", import.meta.url);
const capability = JSON.parse(readFileSync(new URL("src-tauri/capabilities/vrct_capability.json", root), "utf8"));
const scope = capability.permissions.find(item => typeof item === "object" && item.identifier === "opener:allow-open-url");

const toRegExp = pattern => new RegExp("^" + [...pattern.matchAll(/\*+|\?|\[[^\]]+\]|[^*?[]+/g)].map(([part]) => {
    if (part.startsWith("*")) return ".*";
    if (part === "?") return ".";
    if (part.startsWith("[")) return part;
    return part.replace(/[.+^${}()|\\/]/g, "\\$&");
}).join("") + "$");
const allow = scope.allow.map(item => toRegExp(item.url));
const deny = (scope.deny ?? []).map(item => toRegExp(item.url));
const opens = url => !deny.some(pattern => pattern.test(url)) && allow.some(pattern => pattern.test(url));

// Written in the UI but never opened as a link.
const NOT_LINKS = new Set(["https://api.openai.com/v1"]);

const sources = (folder, found = []) => {
    for (const name of readdirSync(folder)) {
        const path = new URL(name, folder);
        if (statSync(path).isDirectory()) sources(new URL(`${name}/`, folder), found);
        else if (/\.(js|jsx|json)$/.test(name) && !name.includes(".test.")) found.push(path);
    }
    return found;
};

test("every URL the UI shows is on the list of URLs the app may open", () => {
    const urls = new Set();
    for (const path of sources(new URL("src-ui/", root))) {
        for (const [url] of readFileSync(path, "utf8").matchAll(/https?:\/\/[^\s"'`)<>]+/g)) {
            const cut = url.search(/\$\{|\{/);
            urls.add(cut < 0 ? url : `${url.slice(0, cut)}x`);
        }
    }
    assert.ok(urls.size > 20, `found ${urls.size} URLs: the scan no longer reads the UI`);
    const refused = [...urls].filter(url => !NOT_LINKS.has(url) && !opens(url)).sort();
    assert.deepEqual(refused, []);
});

test("other sites, other schemes and paths that climb out are refused", () => {
    for (const url of ["https://example.com/", "http://github.com/kein5/VRCT-VOX", "https://github.com/someone/else",
        "https://github.com/kein5/VRCT-VOX/../../someone", "https://huggingface.co@example.com/", "file:///C:/x.exe",
        "mailto:a@example.com"]) assert.equal(opens(url), false, url);
});
