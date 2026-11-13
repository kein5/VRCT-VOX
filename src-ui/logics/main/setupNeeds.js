// What the selected engines still lack before their switches can turn on.
// The UI already knows this from the model lists, so the first screen can say
// it with a way to act, instead of a startup warning that names a settings path.
const missingWeight = (engine, wanted, weights, selected) => {
    if (engine !== wanted) return null;
    const weight = (weights || []).find(item => item.id === selected);
    return weight && !weight.is_downloaded ? weight : null;
};

export const setupNeeds = ({ translationEngine, translationWeights, translationWeight,
    transcriptionEngine, whisperWeights, whisperWeight }) => [
    ["translation", missingWeight(translationEngine, "CTranslate2", translationWeights, translationWeight)],
    ["transcription", missingWeight(transcriptionEngine, "Whisper", whisperWeights, whisperWeight)],
].filter(([, weight]) => weight).map(([id, weight]) => ({ id, weight }));

// "pending" until the first byte, then a whole percentage; null when nothing is being fetched.
export const downloadProgress = weight => Number.isFinite(weight?.progress) ? Math.min(100, Math.floor(weight.progress))
    : weight?.is_pending ? "pending" : null;
