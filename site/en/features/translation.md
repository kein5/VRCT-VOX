# Translation

Translates what you type and what speech recognition turns into text. Turn it on and off with "Translation" on the main screen, and choose the engine under "Translator". The settings are under Settings → "Translation".

![Settings → Translation](/screenshots/en/translation.webp)

## Local translation models (CTranslate2)

Translation runs on your PC, so your text is not sent anywhere. Choose a model under "AI Translation (Local)" and get it with "Download".

| Model | Approximate size | License |
|---|---|---|
| m2m100_418M (default) | 418 MB | MIT (commercial use allowed) |
| m2m100_1.2B | 1.2 GB | MIT (commercial use allowed) |
| nllb-200-distilled-600M | 600 MB | CC-BY-NC-4.0 (non-commercial) |
| nllb-200-distilled-1.3B | 1.3 GB | CC-BY-NC-4.0 (non-commercial) |
| nllb-200-3.3B | 3.3 GB | CC-BY-NC-4.0 (non-commercial) |

::: warning NLLB is non-commercial
NLLB models may not be used for commercial purposes. Selecting or downloading one asks for confirmation, so you can use it only after reading and accepting its license.
:::

Some models cannot translate some languages. For example, M2M100 does not support Basque or Telugu. An unsupported language is reset with a warning so you can choose again.

"Processing device for AI translation" chooses whether translation runs on the CPU or the GPU.

## External translation APIs

You can use DeepL, Plamo, Gemini, OpenAI, Groq and OpenRouter. Register an API key for each, then choose it under "Translator" on the main screen.

- The text to translate is sent to the service you choose.
- API keys are stored in the settings file on this PC (`config.json`).

## Local LLMs and compatible servers

You can use LM Studio, Ollama and OpenAI-compatible endpoints. Check the connection with "Connection Check", then choose a model. If you point the OpenAI-compatible endpoint at a non-official URL, check its pricing, security and compatibility yourself.

## Unavailable engines

The Google, Bing and Papago web translators are unavailable. Upstream VRCT's translator engine code is licensed for official VRCT only.
