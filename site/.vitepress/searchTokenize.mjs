// Splits page text and search queries into words for the local search, Japanese included.
// The default splits on spaces and punctuation only, so a word in the middle of a Japanese
// sentence, such as 読み上げ in テキスト読み上げ（TTS）, could not be found.
// VitePress hands this function to the browser as text, so it uses nothing but built-ins.
// A browser without Intl.Segmenter (Firefox before 125) gets the default split instead of an
// error, so the search still works there, for whole words.
export function tokenize(text) {
  if (typeof Intl === 'undefined' || typeof Intl.Segmenter !== 'function') {
    return text.split(/[\n\r\p{Z}\p{P}]+/u).filter(Boolean)
  }
  const words = []
  for (const part of new Intl.Segmenter('ja', { granularity: 'word' }).segment(text)) {
    if (part.isWordLike) words.push(part.segment)
  }
  return words
}
