# VRCT-VOX

## Platform
web

## Product purpose
A desktop communication application built with Tauri, React 18 and Python. It combines chat translation, transcription, text-to-speech and optional voice conversion for VRChat. The interface is a desktop WebView, not a marketing website.

## Users and operating context
The user tests on Linux and Steam Frame, communicates in Japanese, and uses the application alongside VRChat. Fast access to text input, TTS/RVC enable state, audio routes and a reliable stop/mute action matters during a conversation. Windows distribution remains a separate validation target.

## Capabilities and constraints
Preserve existing backend contracts, settings, translations, OSC routes, hotkeys, Quick Chat, VR panels, model-download consent, and independent TTS/RVC controls. A visual redesign must not enable a microphone, download models, send messages, or change audio routes on its own. Model guidance is advisory; performance results are hardware- and workload-specific.

## Brand commitments
The user requested the name VRCT-VOX and a full application redesign on 2026-10-30. The chosen visual direction is a dark studio: deep navy and blue, calm and appropriate to an audio tool. Retain upstream licensing and acknowledgements. Japanese prose uses yomiyasu.

## Evidence
The current components live under src-ui/views. Functional tests cover voice settings, model downloads, Quick Chat and native AppImage startup. Historical acceptance reports are under docs/voice-stack; their old artifact names and measurement boundaries remain factual.

## Accessibility and implementation
Keyboard access, visible focus, readable contrast, reduced motion, long Japanese labels, window resizing, and existing font/size preferences are part of acceptance. Keep React 18, CSS modules, Jotai and i18next; do not migrate frameworks or add remote fonts.
