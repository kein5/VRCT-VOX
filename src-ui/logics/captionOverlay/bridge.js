import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

// The overlay page's side. The notice carries no data: the captions are read
// through a native command that checks this window's label.
export const captionOverlayBridge = {
    snapshot: () => invoke("caption_overlay_snapshot"),
    onChanged: callback => listen("caption-overlay-changed", callback),
};
