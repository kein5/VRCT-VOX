// Heading ids and the [[toc]] links that point at them.
//
// VitePress's default slugify (vitepress/dist/node, the same as @mdit-vue/shared) decomposes
// the text with NFKD. A Japanese heading with a voiced mark, such as 仮想マイクが必要な理由,
// then gets an id that holds か plus a combining mark, while the links written in the pages
// hold the composed が: the browser finds no such id and the link lands at the top of the
// page. This is the same slugify, composed again at the end (NFC). Headings without voiced
// marks, and every English heading, keep the ids they had.
const rControl = /[\u0000-\u001f]/g
const rSpecial = /[\s~`!@#$%^&*()\-_+=[\]{}|\\;:"'“”‘’<>,.?/]+/g
const rCombining = /[̀-ͯ]/g

export function slugify(text) {
  return text
    .normalize('NFKD')
    .replace(rCombining, '')
    .replace(rControl, '')
    .replace(rSpecial, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/^(\d)/, '_$1')
    .toLowerCase()
    .normalize('NFC')
}
