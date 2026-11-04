// Keep the reviewed manifest with the request; a saved selection is not consent.
export const legacyDownloadRequest = (entry, consent) => {
    if (consent !== true || !entry?.manifest_version || !entry?.weight_type) return null;
    return { weight_type: entry.weight_type, consent: true, manifest_version: entry.manifest_version };
};

export const legacyReviewSize = (entry, t) => {
    // Match the legacy list's binary MB/GB convention and compact precision
    // (141 MB, 1.42 GB), while deriving the value from the pinned total.
    const gigabytes = entry.total_bytes >= 1024 ** 3;
    const amount = Number((entry.total_bytes / 1024 ** (gigabytes ? 3 : 2)).toPrecision(3));
    return t("legacy_model_downloads.size_with_approx", {
        bytes: t("legacy_model_downloads.exact_bytes", { bytes: entry.total_bytes.toLocaleString("en-US") }),
        size: `${amount.toLocaleString("en-US")} ${gigabytes ? "GB" : "MB"}`,
    });
};

export const clearLegacyConsentPending = (rows, weight_type) => rows.map(item =>
    item.id === weight_type ? { ...item, is_pending: false, progress: null } : item);
