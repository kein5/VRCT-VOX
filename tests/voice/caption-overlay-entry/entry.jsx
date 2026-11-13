// The desktop caption overlay over a stand-in scene, for the documentation's picture
// (tests/voice/test_docs_screenshots.py). The real overlay is a see-through window over
// whatever is on the screen; here a plain drawn backdrop takes the place of the game, and
// the captions come from the lines below instead of the main window.
import React from "react";
import { createRoot } from "react-dom/client";
import "../../../src-ui/views/caption_overlay/page.css";
import { CaptionOverlay } from "../../../src-ui/views/caption_overlay/CaptionOverlay";
import "./scene.css";

// Two voices of the game audio told apart (A, B), then the user's own words.
const lines = [
    { id: "1", kind: "received", speakers: ["A"], text: "Welcome! Let me show you around.", translations: ["ようこそ！案内しますね。"] },
    { id: "2", kind: "received", speakers: ["B"], text: "The event starts at nine.", translations: ["イベントは9時に始まります。"] },
    { id: "3", kind: "sent", text: "ありがとうございます。楽しみです！", translations: ["Thank you. I'm looking forward to it!"] },
].map(line => ({ ...line, pending: false, until: Infinity }));
// The app's defaults (ui_configs.overlay_desktop_default_settings).
const bridge = {
    snapshot: async () => ({ lines, position: "bottom", font_size: 28, opacity: 0.6, font_family: "Yu Gothic UI" }),
    onChanged: async () => () => {},
};

createRoot(document.getElementById("root")).render(<CaptionOverlay bridge={bridge} now={() => 0} />);
