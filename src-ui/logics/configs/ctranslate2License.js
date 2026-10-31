// Opt-in rules for CTranslate2 weights with a non-commercial license
// (NLLB, CC-BY-NC-4.0). Kept free of React/aliases so node --test can load it.
// The backend enforces the same rule (Controller._ctranslate2LicenseConsentError).

export const isNonCommercialWeight = (weight) => weight?.non_commercial === true;

// The weight that is already selected never asks again: it was either
// confirmed before or saved by an older version, and the backend accepts it
// without the opt-in flag too.
export const needsLicenseConfirmation = (weight, selected_id) =>
    isNonCommercialWeight(weight) && weight.id !== selected_id;

// Payload for /set/data/selected_ctranslate2_weight_type and
// /run/download_ctranslate2_weight. A bare id keeps the old payload for
// everything that doesn't need the opt-in.
export const weightRequest = (id, accepted = false) =>
    accepted ? { weight_type: id, accept_non_commercial_license: true } : id;

export const weightIdOfRequest = (request) =>
    (request !== null && typeof request === "object") ? request.weight_type : request;
