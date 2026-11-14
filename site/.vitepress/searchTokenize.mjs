// Splits page text and search queries into words for the local search, Japanese included.
// The default splits on spaces and punctuation only, so a word in the middle of a Japanese
// sentence, such as 読み上げ in テキスト読み上げ（TTS）, could not be found.
// VitePress hands this function to the browser as text, so it uses nothing but built-ins.
export function tokenize(text) {
  const words = []
  for (const part of new Intl.Segmenter('ja', { granularity: 'word' }).segment(text)) {
    if (part.isWordLike) words.push(part.segment)
  }
  return words
}
