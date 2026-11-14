// Render the home page's feature animations into site/public/motion/<lang>/<id>.mp4, with a
// still of the finished scene (<id>.webp) for the poster and for readers who prefer less motion.
//
//   cd site/motion && npm ci && npm run render
//
// REMOTION_BROWSER can point at a Chrome for Testing executable (for example Playwright's) so
// Remotion does not download its own headless shell. Only `npm run render` uses Remotion and
// GSAP; the site ships the rendered files. Remotion is free for individuals and companies of
// up to three people (remotion.dev/license); GSAP is under its no-charge standard license.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { bundle } from '@remotion/bundler'
import { renderMedia, renderStill, selectComposition } from '@remotion/renderer'

const here = path.dirname(fileURLToPath(import.meta.url))
const out = path.resolve(here, '../public/motion')
const browserExecutable = process.env.REMOTION_BROWSER || null
const chromeMode = browserExecutable ? 'chrome-for-testing' : 'headless-shell'
const ids = ['translate', 'captions', 'tts', 'voice-changer', 'chat-reading']
const only = process.argv.slice(2)
// STILLS_DIR=<folder> writes stills through the loop instead of the videos, to check the motion.
const stillsDir = process.env.STILLS_DIR

const serveUrl = await bundle({ entryPoint: path.join(here, 'src/index.ts') })
if (stillsDir) {
  fs.mkdirSync(stillsDir, { recursive: true })
  for (const id of ids.filter((id) => only.length === 0 || only.includes(id))) {
    for (const lang of ['ja', 'en']) {
      const inputProps = { lang }
      const composition = await selectComposition({ serveUrl, id, inputProps, browserExecutable, chromeMode })
      for (const second of [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 6.5, 7.4, 7.9]) {
        const frame = Math.min(composition.durationInFrames - 1, Math.round(second * composition.fps))
        const output = path.join(stillsDir, `${id}-${lang}-${String(frame).padStart(3, '0')}.png`)
        await renderStill({ composition, serveUrl, inputProps, browserExecutable, chromeMode, frame, imageFormat: 'png', output })
      }
    }
  }
  process.exit(0)
}
for (const lang of ['ja', 'en']) {
  fs.mkdirSync(path.join(out, lang), { recursive: true })
  for (const id of ids.filter((id) => only.length === 0 || only.includes(id))) {
    const inputProps = { lang }
    const composition = await selectComposition({ serveUrl, id, inputProps, browserExecutable, chromeMode })
    const video = path.join(out, lang, `${id}.mp4`)
    await renderMedia({
      composition,
      serveUrl,
      inputProps,
      browserExecutable,
      chromeMode,
      codec: 'h264',
      crf: 28,
      x264Preset: 'veryslow',
      pixelFormat: 'yuv420p',
      // BT.709 so browsers show the navy as the page's own (#111b2c), not a darker band.
      colorSpace: 'bt709',
      muted: true,
      outputLocation: video,
    })
    // The finished scene, before it leaves for the loop (POSTER_SECONDS in src/parts.tsx).
    await renderStill({
      composition,
      serveUrl,
      inputProps,
      browserExecutable,
      chromeMode,
      frame: Math.round(6.5 * composition.fps),
      imageFormat: 'webp',
      output: path.join(out, lang, `${id}.webp`),
    })
    console.log(`${lang}/${id}: ${(fs.statSync(video).size / 1024).toFixed(0)} KiB`)
  }
}
