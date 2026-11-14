// Checks that the built user guide can be searched by words in the middle of a Japanese
// sentence: loads each locale's search index as the browser does, with the same word splitter,
// and searches for words that only appear inside longer Japanese text.
//
//   node tools/check_site_search.mjs site/.vitepress/dist
//
// Exits 1 and names the word when a search finds nothing, or when the built pages do not carry
// the word splitter to the browser.
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(process.argv[2] ?? join(root, "site/.vitepress/dist"));
const { default: MiniSearch } = await import(pathToFileURL(join(root, "site/node_modules/minisearch/dist/es/index.js")));
const { tokenize } = await import(pathToFileURL(join(root, "site/.vitepress/searchTokenize.mjs")));

const WORDS = {
    ja: ["読み上げ", "仮想マイク", "ボイスチェンジャー", "自分のモデル"],
    en: ["voice changer", "virtual microphone", "own model"],
};
const chunks = join(dist, "assets", "chunks");
const files = readdirSync(chunks);
const failures = [];

// The browser gets the splitter from the site data in the built pages; without it, queries
// would be split the default way and miss the words the index holds.
const assets = readdirSync(join(dist, "assets")).filter(name => name.endsWith(".js"))
    .map(name => readFileSync(join(dist, "assets", name), "utf8"));
const pages = [readFileSync(join(dist, "ja", "index.html"), "utf8"), ...assets];
if (!pages.some(text => text.includes("Intl.Segmenter"))) failures.push("the built pages do not carry the word splitter (Intl.Segmenter)");

for (const [locale, words] of Object.entries(WORDS)) {
    const file = files.find(name => name.startsWith(`@localSearchIndex${locale}.`));
    if (!file) { failures.push(`${locale}: no search index in ${chunks}`); continue; }
    const { default: json } = await import(pathToFileURL(join(chunks, file)));
    const index = MiniSearch.loadJSON(json, {
        fields: ["title", "titles", "text"], storeFields: ["title", "titles"], tokenize,
        searchOptions: { fuzzy: 0.2, prefix: true, boost: { title: 4, text: 2, titles: 1 } },
    });
    for (const word of words) {
        const hits = index.search(word, { combineWith: "AND" });
        if (hits.length === 0) failures.push(`${locale}: nothing found for "${word}"`);
        else console.log(`${locale}: "${word}" → ${hits.length} (${hits.slice(0, 3).map(hit => hit.id).join(", ")})`);
    }
}
if (failures.length) {
    for (const failure of failures) console.error(failure);
    process.exit(1);
}
console.log("search ok");
