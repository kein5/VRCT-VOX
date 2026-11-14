// Checks that every link to a heading in the built user guide finds that heading.
//
//   node tools/check_site_anchors.mjs site/.vitepress/dist
//
// VitePress fails the build on links to missing pages, but not on links to a missing
// #heading on a page that exists. Japanese headings broke that way: the default slugify
// decomposes voiced marks, so 「…が…」 in a link never matched the id (site/.vitepress/slugify.mjs).
// This reads every page, collects its ids, and looks up every same-site link with a #fragment.
// Exits 1 and lists the links whose heading is missing.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, posix, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(process.argv[2] ?? join(root, "site/.vitepress/dist"));
const BASE = "/VRCT-VOX/";

const walk = dir => readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
});
const pages = new Map();
for (const file of walk(dist).filter(path => path.endsWith(".html"))) {
    const html = readFileSync(file, "utf8");
    const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(match => match[1]));
    pages.set(relative(dist, file).split("\\").join("/"), { html, ids });
}

const pageFor = (from, path) => {
    let target = path.startsWith(BASE) ? path.slice(BASE.length) : posix.join(posix.dirname(from), path);
    if (target === "" || target.endsWith("/")) target += "index";
    return target.endsWith(".html") ? target : `${target}.html`;
};

const failures = [];
let checked = 0;
for (const [from, { html, ids }] of pages) {
    for (const [, href] of html.matchAll(/<a\s[^>]*href="([^"]*#[^"]+)"/g)) {
        if (/^[a-z]+:/i.test(href)) continue; // Another site.
        const [path, fragment] = href.split("#");
        const target = path ? pageFor(from, path) : from;
        const page = path ? pages.get(target) : { ids };
        if (!page) continue; // A missing page fails the VitePress build itself.
        const id = decodeURIComponent(fragment);
        checked++;
        if (!page.ids.has(id)) failures.push(`${from}: #${id} is not a heading in ${target}`);
    }
}
for (const failure of [...new Set(failures)]) console.error(failure);
if (failures.length) process.exit(1);
console.log(`anchors ok (${checked} links)`);
