export const LOCALE_KEY = 'vrct-vox-docs-locale'

// The language / opens: a choice made in the language menu, else the browser's languages.
export function preferredLocale(): 'ja' | 'en' {
  try {
    const saved = localStorage.getItem(LOCALE_KEY)
    if (saved === 'ja' || saved === 'en') return saved
  } catch {
    // Storage can be blocked; fall through to the browser language.
  }
  const languages = navigator.languages?.length ? navigator.languages : [navigator.language]
  return languages.some((language) => language?.toLowerCase().startsWith('ja')) ? 'ja' : 'en'
}
