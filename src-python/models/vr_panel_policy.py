"""What the VR panel may ask the backend to do (security audit SEC-02, SEC-07).

The VR panel window has no sidecar of its own. The main window relays its requests, only the
paths in src-ui/logics/common/vrPanelWire.js (VR_PANEL_RELAY_PATHS), and marks them with
"origin": "vr_panel". The backend checks the mark against this list as well, so a slip in the
UI list or a compromised VR page still cannot reach credentials, network addresses, downloads,
voice settings, telemetry consent, files or shutdown. Anything not listed is refused, new
endpoints included. A test keeps this list equal to the UI's.
"""

VR_PANEL_ORIGIN = "vr_panel"


def _toggle(name):
    return (f"/set/enable/{name}", f"/set/disable/{name}")


VR_PANEL_ENDPOINTS = frozenset({
    # The panel itself: its windows, the log's bar, layout and tooltips.
    "/run/vr_panel_windows", "/run/vr_panel_recall_log", "/run/vr_panel_layout_rendered", "/run/vr_panel_tooltip",
    "/set/data/overlay_vr_panel_anchor", *_toggle("overlay_vr_panel_locked"),
    "/set/data/overlay_vr_panel_opacity", "/set/data/overlay_vr_panel_font_size",
    # The launcher's switches.
    *_toggle("translation"), *_toggle("transcription_send"), *_toggle("transcription_receive"), *_toggle("ocr_capture"),
    # The language window.
    "/set/data/selected_tab_no", "/set/data/selected_your_languages", "/set/data/selected_target_languages",
    "/set/data/selected_translation_engines", "/run/swap_your_language_and_target_language",
    "/get/data/selected_tab_no", "/get/data/selected_your_languages", "/get/data/selected_target_languages",
    "/get/data/selected_translation_engines", "/get/data/selectable_translation_engines",
    # The VR settings window: devices and their meters.
    "/set/data/selected_mic_host", "/set/data/selected_mic_device_id", "/set/data/selected_speaker_device_id",
    "/set/data/mic_threshold", "/set/data/speaker_threshold",
    *_toggle("mic_automatic_threshold"), *_toggle("speaker_automatic_threshold"),
    *_toggle("auto_mic_select"), *_toggle("auto_speaker_select"),
    *_toggle("check_mic_threshold"), *_toggle("check_speaker_threshold"),
    # Translation, speech recognition and chat reading.
    "/set/data/selected_ctranslate2_weight_type", "/set/data/selected_translation_compute_device",
    "/set/data/selected_translation_compute_type",
    "/set/data/selected_transcription_engine", "/set/data/selected_whisper_weight_type",
    "/set/data/selected_transcription_compute_device", "/set/data/selected_transcription_compute_type",
    "/set/data/ocr_source_language", "/set/data/ocr_min_confidence", "/set/data/ocr_poll_interval_ms",
    "/set/data/ocr_bubble_min_text_length",
    # Messages, VR overlays and appearance.
    *_toggle("convert_message_to_hiragana"), *_toggle("convert_message_to_romaji"), *_toggle("vrc_mic_mute_sync"),
    *_toggle("overlay_small_log"), *_toggle("overlay_large_log"), *_toggle("overlay_show_only_translated_messages"),
    *_toggle("overlay_vr_launcher_auto_hide"), *_toggle("overlay_vr_tooltip"), "/set/data/overlay_vr_launcher_hand",
    "/set/data/ui_language", "/set/data/font_family",
})


def request_allowed(origin, endpoint) -> bool:
    """A request from the main window (no origin) may use any endpoint; one relayed for the VR
    panel only the listed ones. Any other origin is refused."""
    if origin is None:
        return True
    return origin == VR_PANEL_ORIGIN and endpoint in VR_PANEL_ENDPOINTS
