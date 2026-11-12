// The voice controls a hotkey can reach. The main window's switches and stop
// actions publish their current handlers here on every render, so a shortcut
// that was registered earlier acts on the state of the moment it is pressed,
// with the same checks and notices as the control on screen.
export const voiceActions = { toggleTts: null, toggleRvc: null, stop: null, toggleMute: null };
