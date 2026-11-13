// Who spoke in a caption of the game audio, as the server's diarization labels the voices
// ("A", "B", ...): at most four, in the order they speak. A label is a voice within one
// session, not a person, and the diarization can be wrong about it. Anything else is no speakers.
export const speakerLabels = value => Array.isArray(value) && value.length <= 4 &&
    value.every(label => typeof label === "string" && /^[A-Z]{1,3}$/.test(label)) ? value : [];
