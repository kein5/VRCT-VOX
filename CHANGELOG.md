# Changelog

All notable changes to VRCT-VOX, newest first. Only stable releases are listed: each section
covers everything since the previous stable release, its betas included. Betas (`X.Y.Z-beta.N`,
from `develop`) are described in their [GitHub pre-release notes](https://github.com/kein5/VRCT-VOX/releases).
Versions follow [Semantic Versioning](https://semver.org/). The layout follows the ideas of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/): changes that users notice come first, and
changes for developers follow.

A section is written when its release is prepared (`python tools/changelog.py write`), not on
every commit. See [Changelog and releases](CONTRIBUTING.md#changelog-and-releases).

## [0.2.0] - 2026-11-15

Changes since [v0.1.0](https://github.com/kein5/VRCT-VOX/compare/v0.1.0...v0.2.0).

This release includes the changes of 0.2.0-beta.1, listed below.

### User-facing Changes

#### Breaking Changes

- **websocket:** Listen beyond this PC only over TLS, and let the connection key be replaced ([bb0c5fe](https://github.com/kein5/VRCT-VOX/commit/bb0c5fe37c6c34f64171b45ad975f4f7538dba06))
  - a WebSocket host other than 127.0.0.x needs a
certificate and key. A LAN host saved without them goes back to
127.0.0.1 at startup, and the app says so.
- **ocr:** Remove upstream VRCT's chat-bubble model from the repository ([78a1ad2](https://github.com/kein5/VRCT-VOX/commit/78a1ad254a3b6e0331c8288a270200f84723ab85))
  - BubbleDetector() without model_path has no model.
- **ui:** Offer English and Japanese only as UI languages ([87ecf44](https://github.com/kein5/VRCT-VOX/commit/87ecf442a8be5ab9d214d399e565383033c96306))
  - UI_LANGUAGE accepts only "en" and "ja".

#### Features

- **ui:** Link each model setting to how to use your own model ([f215c44](https://github.com/kein5/VRCT-VOX/commit/f215c448d77f91b244fd5832004038bbc462c61d))
- **ui:** Name features by what they do, with the short name in brackets ([6510ebe](https://github.com/kein5/VRCT-VOX/commit/6510ebe9b9ba337ed749ca59d824cf01e8a158b5))
- **flow:** Draw where each input goes as a graph, in the panel, in VR and on the desktop ([cf26e26](https://github.com/kein5/VRCT-VOX/commit/cf26e2684153eacf8976bb268fb10aadb9d11d7e))
- **flow:** Show where your voice and chat go, with the time each step took, in the app, on the desktop and in VR ([cd16585](https://github.com/kein5/VRCT-VOX/commit/cd16585e694df8734c00bcc38d6994ba8a6920b8))
- **flow:** Record where the user's voice and chat go and how long each step takes ([197fb24](https://github.com/kein5/VRCT-VOX/commit/197fb241b588b9ada517de18fe628e521cb6a3b2))
- **voice:** Speak translations in the converted voice (ADR-007) ([8b4f190](https://github.com/kein5/VRCT-VOX/commit/8b4f190fa8d05dfdb4b968b9803c2320bdf8f429))
- **voice:** Stop RVC and Seed-VC at the start when no NVIDIA GPU is there ([9b5453e](https://github.com/kein5/VRCT-VOX/commit/9b5453e66fe4de72229ce90b02ede8582459628c))
- **captions:** Show the desktop caption overlay on Linux under X11 and XWayland ([1528fc5](https://github.com/kein5/VRCT-VOX/commit/1528fc53af2f3d5ba3bc16b5117310cf5af7d23c))

#### Bug Fixes

- **telemetry:** Start sending usage data only from the answer to the notice ([13da826](https://github.com/kein5/VRCT-VOX/commit/13da8260d92c19d2734186a57aec2fd6e68a7608))
- **vr:** Relay only the requests the VR panel sends, and check them in the backend too ([8692fa6](https://github.com/kein5/VRCT-VOX/commit/8692fa69c893e177799a324758632f7be5ccc2b6))
- **site:** Make links to Japanese headings with voiced marks land on the heading ([7abb9d9](https://github.com/kein5/VRCT-VOX/commit/7abb9d96e7b5f2febbcda68746a7c9d63b83f282))
- **site:** Keep the search working in browsers without Intl.Segmenter ([1cd1ad8](https://github.com/kein5/VRCT-VOX/commit/1cd1ad8030f2a68e2a6586b7623a985885757f05))
- **ui:** Explain voice errors on the main screen, and name speech recognition in English hints ([60f4758](https://github.com/kein5/VRCT-VOX/commit/60f4758c7a77c1df6c29291808ff076f7c6a416e))
- **ui:** Keep long feature names whole in the settings menu and the VR panel ([f740307](https://github.com/kein5/VRCT-VOX/commit/f740307fe406966b0f4d0cae858f019649e9bf44))
- **voice:** Say why the voice changer could not start instead of showing its code ([97aa51b](https://github.com/kein5/VRCT-VOX/commit/97aa51b2582ad82fcf35173f9e2133ff0377a2ac))
- **flow:** Fit the panel, the desktop strip and the VR window, and document them ([8888d17](https://github.com/kein5/VRCT-VOX/commit/8888d17033a3fb88c1403357287877e0953d404f))
- **voice:** Keep the router's control frames as before when nothing is suppressed ([3000d35](https://github.com/kein5/VRCT-VOX/commit/3000d35c0ff0c55777f8c98c2b91cc865a6f0852))
- **captions:** Realize the Linux overlay window before making it click-through ([b143251](https://github.com/kein5/VRCT-VOX/commit/b1432518ebac0eaf54bb62115f92278c809f8e9e))
- **downloads:** Never wait longer than asked when stopping a legacy download ([4465fe1](https://github.com/kein5/VRCT-VOX/commit/4465fe13fd539d262c0b5f25e03f3fec0bb16e2f))
- **speech:** Start the bundled servers on a dedicated GPU first, for any vendor ([8c1f74c](https://github.com/kein5/VRCT-VOX/commit/8c1f74c5a60e8f9eb1fabd11da2da5519569ec6b))
- **translation:** Do not treat a model that was never downloaded as an error ([250b4bc](https://github.com/kein5/VRCT-VOX/commit/250b4bc2b046b645f313b8d1331e9c8687421396))
- **ui:** Name the section users can see in speech server messages ([f5f2e08](https://github.com/kein5/VRCT-VOX/commit/f5f2e08a09286fdad925b2445d32e612814d3431))

### Internal Changes

#### Build & CI

- **release:** Keep CHANGELOG.md to stable releases, and make beta notes from their commits ([65a52cf](https://github.com/kein5/VRCT-VOX/commit/65a52cfbfc36437f7724c9c026ddcd9a8637e89f))
- **release:** List the pre-releases' user-facing changes in a stable release's notes ([b7fe1a2](https://github.com/kein5/VRCT-VOX/commit/b7fe1a2b2adad2d4ab96c316531b26b05e9b4611))
- **release:** Check commit messages with a cog hook, and write CHANGELOG.md when a release is prepared ([239b93d](https://github.com/kein5/VRCT-VOX/commit/239b93da434620eb246324d935f0bedcda37a757))

#### Tests

- **websocket:** Give the test Model the same re-entrant OBS lock as the app ([2db2497](https://github.com/kein5/VRCT-VOX/commit/2db2497006bdbd0da052a5871648328f90c868ca))
- **websocket:** Connect over wss with the asyncio client, which does not lose data on Windows ([ba65507](https://github.com/kein5/VRCT-VOX/commit/ba65507710b8c2b50f889c726d071c9b6a918ecf))
- **voice:** Import the controller fixture the way the other voice tests do ([70a6959](https://github.com/kein5/VRCT-VOX/commit/70a6959293631c556ca12a2c20bde9e97399c207))

#### Documentation

- **websocket:** Say "needed" and "cannot connect" in the LAN certificate texts ([86ce481](https://github.com/kein5/VRCT-VOX/commit/86ce4818e403ca9f125eac5c935f1dfb6d9e8a24))
- **site:** Explain using OBS and WebSocket from other PCs, and making a new key ([9b4398a](https://github.com/kein5/VRCT-VOX/commit/9b4398a0ae80cfe27a2e0a1ead7e2e038e30c6bc))
- **site:** Say what each feature does in words a reader can follow ([7e52250](https://github.com/kein5/VRCT-VOX/commit/7e52250eae4b24a96f6bfebcfc403dca4c7139f5))
- **site:** Say a custom Whisper server always needs a key, and fix the last old names ([b2655d4](https://github.com/kein5/VRCT-VOX/commit/b2655d4b287dea423f9c1929b7679b4d99439e14))
- Record how features are named, in the design guide and the use cases ([422313f](https://github.com/kein5/VRCT-VOX/commit/422313f3ca9ed556498e6dd9c89dd0d04cb760aa))
- **site:** Retake the screenshots with the new feature names, and keep names whole in the flow graph ([56aa7b3](https://github.com/kein5/VRCT-VOX/commit/56aa7b3f789e19d086d3abd1d8ac6280d1d3633a))
- **site:** Put every feature and guide page in the common order, with the new feature names ([508f024](https://github.com/kein5/VRCT-VOX/commit/508f024ddee089b8d6187cb850790f0c7abc2772))
- Write down the commit and changelog rules for people and agents ([175d3c2](https://github.com/kein5/VRCT-VOX/commit/175d3c217dff3037eb553056b45f52ca4e8bbc66))
- **site:** Put the text to speech page in the common order ([2733f87](https://github.com/kein5/VRCT-VOX/commit/2733f8717220ff92796be997ed25e3f87f07831a))
- **site:** Add pages for what you want to do, how voice and text flow, and your own models ([12bcb02](https://github.com/kein5/VRCT-VOX/commit/12bcb024cc383c6db24796680640e43522fdfe22))
- **site:** Group pages by what you want to do, and search Japanese by word ([7d7d89d](https://github.com/kein5/VRCT-VOX/commit/7d7d89db248f81e9d76a777a9e465620f2d5eda4))
- **superpowers:** Plan the user docs restructure, the feature names and the own-model guide ([f9caf31](https://github.com/kein5/VRCT-VOX/commit/f9caf31dddbad4395735124de94cad9937847008))
- **site:** Point AMD and Intel GPU users to local LLMs and realtime captions ([17b3281](https://github.com/kein5/VRCT-VOX/commit/17b328177a2a1e144e90cc0b703d729f592c49ab))
- **voice:** Propose speaking translations through voice conversion (ADR-007) ([1240014](https://github.com/kein5/VRCT-VOX/commit/124001460085cf2d3d1504ccce0a258037312c8d))
- **tts:** Use the labels the settings show now in the quickstart ([bd70a52](https://github.com/kein5/VRCT-VOX/commit/bd70a52b463cd12c708eff26e98e888d0f4cf1c4))
- **site:** Show the desktop captions on a screen, and say what the GPU version adds ([d07032a](https://github.com/kein5/VRCT-VOX/commit/d07032a9b93a958223a3cf7cb554592f8d49b8be))
- **release:** Record the 0.1.0 release and the log line the package check always leaves ([d6d347d](https://github.com/kein5/VRCT-VOX/commit/d6d347dfecb1c19974d8dae4719f7dea9ea1c202))
- **site:** Show the app in use, fix stale paths, and let screenshots open larger ([821e911](https://github.com/kein5/VRCT-VOX/commit/821e911f9c99b286d1088353faf4be98589588f8))

#### Maintenance

- Drop the VR UI previews, upstream-era notes and ko/zh logos; run stray unit tests ([f148d04](https://github.com/kein5/VRCT-VOX/commit/f148d040b8d373cb6c8f88e75047faa65680e728))
- Remove files nothing uses ([f5377bb](https://github.com/kein5/VRCT-VOX/commit/f5377bb3fcfdfb231f6c70c3edfd920be32d7523))

## Earlier releases

Releases up to 0.1.0 are described in [GitHub Releases](https://github.com/kein5/VRCT-VOX/releases).
