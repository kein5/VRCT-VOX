import { openai_auth_key_url, groq_auth_key_url, deepgram_auth_key_url } from "../ui_configs.js";

// Cloud transcription engines. `id` is the backend engine name, `base` names
// the generated settings (e.g. GroqWhisperAuthKey), `key` the locale keys
// under config_page.transcription.
export const CLOUD_TRANSCRIPTION_ENGINES = [
    { id: "Groq_Whisper", base: "GroqWhisper", key: "groq_whisper", webpage_url: groq_auth_key_url },
    { id: "OpenAI_Whisper", base: "OpenAIWhisper", key: "openai_whisper", webpage_url: openai_auth_key_url },
    { id: "Custom_Whisper", base: "CustomWhisper", key: "custom_whisper", has_url: true },
    { id: "Deepgram", base: "Deepgram", key: "deepgram", webpage_url: deepgram_auth_key_url },
];
