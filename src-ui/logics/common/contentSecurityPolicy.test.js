import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { parse } from "@babel/parser";

// Static only: no DOM, application startup, network, or execution of bundle code.
// @babel/parser is already installed by @vitejs/plugin-react (package-lock.json).
const root = fileURLToPath(new URL("../../../", import.meta.url));
const read = name => readFileSync(path.join(root, name), "utf8");
const config = JSON.parse(read("src-tauri/tauri.conf.json"));
const security = config.app.security;
const sources = (policy, directive) => {
    assert.ok(policy && typeof policy === "object", "Use the Tauri v2 directive map");
    const value = policy[directive];
    assert.ok(value, `Missing ${directive}`);
    return Array.isArray(value) ? value : value.trim().split(/\s+/);
};
const hash = css => `'sha256-${createHash("sha256").update(css).digest("base64")}'`;
const injectedStyles = [
    ["node_modules/react-colorful/dist/index.mjs", ".react-colorful{"],
    ["node_modules/react-toastify/dist/index.mjs", ":root{--toastify-"],
];
function files(directory) {
    return readdirSync(path.join(root, directory), { withFileTypes: true }).flatMap(entry => {
        const name = `${directory}/${entry.name}`;
        return entry.isDirectory() ? files(name) : [name];
    });
}
function walk(node, visit) {
    if (!node || typeof node !== "object") return;
    if (node.type) visit(node);
    for (const [key, value] of Object.entries(node)) {
        if (["loc", "comments", "tokens"].includes(key)) continue;
        if (Array.isArray(value)) value.forEach(child => walk(child, visit));
        else if (value && typeof value === "object") walk(value, visit);
    }
}
const ast = code => parse(code, { sourceType: "unambiguous", plugins: ["jsx"], createImportExpressions: true });
const literal = node => node?.type === "StringLiteral" ? node.value
    : node?.type === "TemplateLiteral" && !node.expressions.length ? node.quasis[0].value.cooked : null;
const member = node => node?.type === "Identifier" ? node.name
    : ["MemberExpression", "OptionalMemberExpression"].includes(node?.type)
        ? node.computed ? literal(node.property) : node.property.name : null;
const remote = value => /^(?:[a-z][\w+.-]*:|\/\/)/i.test(value);
function cssProblems(css) {
    const problems = [];
    // Includes @font-face src, @import and CSS embedded in JSX string values.
    for (const match of css.matchAll(/(?:url\(\s*|@import\s+)["']?([^\s"')]+)/gi)) {
        if (remote(match[1]) && !match[1].startsWith("data:image/")) problems.push(`external CSS resource ${match[1]}`);
    }
    // CSS escapes can conceal a scheme; require an explicit review of such URLs.
    if (/(?:url\(|@import)[^;\n]*\\/i.test(css)) problems.push("escaped CSS resource URL");
    return problems;
}
function jsProblems(code, application = true) {
    const problems = [];
    walk(ast(code), node => {
        const fail = message => problems.push(`${node.loc.start.line}: ${message}`);
        // Check references too, so aliases and indirect eval cannot evade this guard.
        if ((node.type === "Identifier" && ["eval", "Function", "WebAssembly"].includes(node.name))
            || (["MemberExpression", "OptionalMemberExpression"].includes(node.type)
                && ["eval", "Function", "WebAssembly"].includes(member(node)))) fail("dynamic code generation");
        if (["CallExpression", "OptionalCallExpression", "NewExpression"].includes(node.type)) {
            const name = member(node.callee);
            if (["Worker", "SharedWorker"].includes(name)) fail("worker requires a policy review");
            if (["setTimeout", "setInterval"].includes(name) && literal(node.arguments[0]) !== null) fail("string timer");
            if (application) {
                if (["fetch", "XMLHttpRequest", "WebSocket", "EventSource", "FontFace", "importScripts", "convertFileSrc", "createObjectURL", "toDataURL"].includes(name)) fail(`new resource loader: ${name}`);
                if (name === "createElement" && ["script", "style", "link", "iframe"].includes(literal(node.arguments[0]))) fail("dynamic resource element");
                if (["insertAdjacentHTML", "write", "writeln"].includes(name)
                    && member(node.callee.object) === "document") fail("HTML injection");
                if (name === "setAttribute" && ["src", "href", "style"].includes(literal(node.arguments[0]))) fail("resource/style attribute setter");
            }
        }
        if (["ImportDeclaration", "ExportNamedDeclaration", "ExportAllDeclaration", "ImportExpression"].includes(node.type) && node.source) {
            const value = literal(node.source);
            if (value === null || remote(value)) fail("non-local module import");
            if (application && value === "@tauri-apps/plugin-http") fail("HTTP plugin needs a separate native permission review");
        }
        const value = literal(node);
        if (value !== null) problems.push(...cssProblems(value));
        if (!application) return;
        if (node.type === "AssignmentExpression" && ["src", "href", "innerHTML", "outerHTML"].includes(member(node.left))) fail("dynamic resource/HTML assignment");
        if (node.type === "JSXOpeningElement" && ["script", "style", "link", "iframe", "audio", "video"].includes(node.name.name)) fail("new JSX resource element");
        if (node.type === "JSXAttribute") {
            if (node.name.name === "dangerouslySetInnerHTML") fail("HTML injection");
            const value = literal(node.value?.expression ?? node.value);
            if (["src", "srcSet"].includes(node.name.name) && value && remote(value) && !value.startsWith("data:image/")) fail("external JSX resource");
        }
    });
    return problems;
}
function htmlProblems(html) {
    const problems = [];
    for (const tag of html.matchAll(/<(script|link|img|base|iframe|audio|video)\b[^>]*>/gi)) {
        for (const attribute of tag[0].matchAll(/(?:src|href)\s*=\s*["']([^"']*)["']/gi)) {
            if (remote(attribute[1])) problems.push(`external HTML resource ${attribute[1]}`);
        }
    }
    if (/<style\b|\sstyle\s*=|\son\w+\s*=|<script\b(?![^>]*\bsrc=)/i.test(html)) problems.push("inline HTML code/style");
    return problems;
}
function styleHashes(code) {
    const values = [];
    walk(ast(code), node => {
        const value = literal(node);
        if (value && injectedStyles.some(([, prefix]) => value.startsWith(prefix))) values.push(hash(value));
    });
    return values;
}

test("production CSP allows only the reviewed resources and keeps Tauri CSP injection enabled", () => {
    const expected = {
        "default-src": ["'self'"], "script-src": ["'self'"], "style-src-attr": ["'none'"],
        "img-src": ["'self'", "data:"], "font-src": ["'self'"],
        "connect-src": ["'self'", "ipc:", "http://ipc.localhost", "https://ipc.localhost"],
        "media-src": ["'none'"], "worker-src": ["'none'"], "frame-src": ["'none'"],
        "object-src": ["'none'"], "base-uri": ["'self'"], "frame-ancestors": ["'none'"], "form-action": ["'none'"],
    };
    for (const [directive, allowed] of Object.entries(expected)) assert.deepEqual(sources(security.csp, directive), allowed, directive);
    assert.deepEqual(Object.keys(security.csp).sort(), [...Object.keys(expected), "style-src"].sort());
    assert.equal(security.dangerousDisableAssetCspModification ?? false, false);
    assert.equal(security.assetProtocol?.enable ?? false, false);
    for (const file of readdirSync(path.join(root, "src-tauri")).filter(name => /tauri\.[^/]+\.conf\.json$/.test(name)).map(name => `src-tauri/${name}`)) {
        assert.equal(JSON.parse(read(file)).app?.security, undefined, `${file} overrides the reviewed policy`);
    }
});

test("style hashes match the two installed runtime injectors, without unsafe-inline", () => {
    const hashes = injectedStyles.flatMap(([file]) => {
        const result = styleHashes(read(file));
        assert.equal(result.length, 1, `${file}: review the stylesheet injector after dependency changes`);
        return result;
    });
    assert.deepEqual(sources(security.csp, "style-src"), ["'self'", ...hashes]);
});

test("development relaxations are confined to Vite inline code/styles and loopback HMR", () => {
    assert.equal(config.build.devUrl, "http://localhost:1420");
    assert.deepEqual(sources(security.devCsp, "script-src"), ["'self'", "'unsafe-inline'"]);
    assert.deepEqual(sources(security.devCsp, "style-src"), ["'self'", "'unsafe-inline'"]);
    assert.deepEqual(sources(security.devCsp, "connect-src"), [
        ...sources(security.csp, "connect-src"), "ws://localhost:1420", "ws://127.0.0.1:1420", "ws://localhost:1421", "ws://127.0.0.1:1421",
    ]);
    for (const directive of Object.keys(security.csp)) {
        if (!["script-src", "style-src", "connect-src"].includes(directive)) assert.deepEqual(security.devCsp[directive], security.csp[directive]);
    }
});

test("production sources have no dynamic code or unreviewed resource loaders", () => {
    for (const file of [...files("src-ui"), ...files("locales")]) {
        if (/\.test\.[cm]?js$|\/test\//.test(file)) continue;
        if (!/\.(?:[cm]?jsx?|css|scss|html|svg)$/.test(file)) continue;
        const code = read(file);
        const problems = /\.[cm]?jsx?$/.test(file) ? jsProblems(code)
            : /\.(?:css|scss)$/.test(file) ? cssProblems(code)
                : /\.(?:html|svg)$/.test(file) ? htmlProblems(code) : [];
        assert.deepEqual(problems, [], `${file}: update the CSP inventory and policy before adding resources`);
    }
});

test("guards detect direct, indirect and computed eval and remote script/style/font loading", () => {
    for (const code of ["eval('x')", "(0, eval)('x')", "const run = window['eval']; run('x')", "new Function('x')", "Function('x')", "new globalThis['Function']('x')", "WebAssembly.compile(bytes)", "setTimeout('x', 1)", "import('https://cdn.invalid/a.js')", "const s = document.createElement('script')", "element.src = url", "const x = <script src={url} />", "const x = <img src='https://cdn.invalid/a.png' />", "new FontFace('remote', url)", "fetch(url)"]) {
        assert.notEqual(jsProblems(code).length, 0, code);
    }
    for (const css of ["@import 'https://cdn.invalid/a.css';", "@font-face{src:url(https://cdn.invalid/a.woff2)}", "body{background:url(//cdn.invalid/a.svg)}"]) assert.notEqual(cssProblems(css).length, 0, css);
    assert.notEqual(htmlProblems('<link rel="stylesheet" href="https://cdn.invalid/a.css">').length, 0);
    assert.deepEqual(jsProblems('const help = "https://example.invalid"; element.style.setProperty("color", "red");'), []);
});

test("emitted production dependencies and HTML agree with the policy (run after vite-build)", context => {
    if (!existsSync(path.join(root, "dist/index.html"))) {
        context.skip("No dist: run npm run vite-build, then run this test again for the bundle check");
        return;
    }
    const built = files("dist");
    assert.deepEqual(built.filter(file => file.endsWith(".html")).sort(), ["dist/index.html", "dist/quick-chat.html", "dist/vr.html"]);
    const hashes = [];
    let styleInjectors = 0;
    for (const file of built) {
        if (file.endsWith(".js")) {
            assert.deepEqual(jsProblems(read(file), false), [], file);
            hashes.push(...styleHashes(read(file)));
            walk(ast(read(file)), node => {
                if (node.type === "CallExpression" && member(node.callee) === "createElement"
                    && literal(node.arguments[0]) === "style") styleInjectors++;
            });
        } else if (file.endsWith(".css")) assert.deepEqual(cssProblems(read(file)), [], file);
        else if (file.endsWith(".html")) assert.deepEqual(htmlProblems(read(file)), [], file);
        assert.ok(!/\.(?:wasm|woff2?|ttf|otf|mp[34]|wav|ogg|webm)$/.test(file), `${file}: new resource class needs review`);
    }
    assert.equal(styleInjectors, injectedStyles.length, "Review new or changed runtime style injectors");
    assert.deepEqual(hashes.sort(), sources(security.csp, "style-src").filter(value => value !== "'self'").sort());
});
