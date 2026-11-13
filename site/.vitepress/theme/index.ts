import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import { LOCALE_KEY } from './locale'
import './custom.css'

export default {
  extends: DefaultTheme,
  enhanceApp() {
    if (typeof document === 'undefined') return
    // Remember a language picked in the nav's language menu, so / opens it next time.
    document.addEventListener('click', (event) => {
      const link = (event.target as Element | null)?.closest?.('.VPNavBarTranslations a, .VPNavScreenTranslations a')
      const locale = link?.getAttribute('href')?.match(/\/(ja|en)\//)?.[1]
      if (locale) {
        try {
          localStorage.setItem(LOCALE_KEY, locale)
        } catch {
          // Storage can be blocked; the browser language decides then.
        }
      }
    })
  },
} satisfies Theme
