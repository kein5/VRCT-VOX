# Model downloads

VRCT-VOX packages contain no models for speech, speech recognition, voice conversion or text recognition. Download the models you use from the settings, or point to files you already have.

## How a download works

1. Under "Download a default model" on a page, press "Review download".
2. Check the provider, model name, exact size, links to the terms and where it will be saved.
3. Tick the agreement and press "Agree and download". You can cancel while it downloads.
4. When the download and check finish, press "Apply model path". Stop the server or input it belongs to first.

Downloading or applying does not start a server, speech or the microphone.

::: info File checks
Downloaded files are checked by size and SHA-256 before use. They come only from pinned Hugging Face repositories and revisions.
:::

## Available models

| Use | Model | Size | License |
|---|---|---|---|
| Japanese speech | Irodori-TTS v4.1 Small MF · F16 | 1.79 GiB | MIT + Apache-2.0 |
| Japanese speech (lighter) | Irodori-TTS v4.1 Small MF · Q8_0 | 1.12 GiB | MIT + Apache-2.0 |
| Other languages' speech | Qwen3-TTS 12Hz 0.6B CustomVoice · Q8_0 | 1.13 GiB | Apache-2.0 |
| Other languages' speech (lighter) | Qwen3-TTS 12Hz 0.6B CustomVoice · Q5_K | 0.81 GiB | Apache-2.0 |
| Speech recognition (Japanese) | Haas-ja v1.0 · Q8_0 | 0.61 GiB | Apache-2.0 |
| Speech recognition (30 languages) | Qwen3-ASR 0.6B · Q8_0 | 0.78 GiB | Apache-2.0 |
| Speech detection | Silero VAD v6.2 · F32 | 1.2 MB | MIT |
| Voice conversion (RVC) | Saisho Utane · RVC v2 | 0.31 GiB | CC BY 4.0 (credit required) |
| Text recognition | PP-OCRv6 small (Japanese, English, Chinese, Latin) | about 30 MB | Apache-2.0 |
| Text recognition | PP-OCRv5 mobile (Korean, Cyrillic, Thai, Arabic, Devanagari) | 8–14 MB each | Apache-2.0 |

Translation models are downloaded under Settings → "Translation" (see [Translation](../features/translation)).

## GPU and memory guidance

The TTS page shows your GPU's name and its total and free memory, and suggests the standard or the lighter model for that free memory. This is guidance only; it does not reserve memory or guarantee that it runs. Leave more headroom when you use VRChat at the same time.

## Where models are saved

Downloaded models go to `downloaded_models` in the same folder as the settings file (`config.json`). On Linux that is `~/.config/vrct-vox/downloaded_models`.

## Downloading at startup

"Download translation and transcription models at startup" under Settings → "Other" downloads missing built-in translation and transcription models at the next start. It is off by default. Models you already have work either way.
