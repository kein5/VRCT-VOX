export const isSidecarWarning = line => {
    if (typeof line !== "string") return false;
    try {
        const value = JSON.parse(line);
        return value?.type === "vrct_warning" && typeof value.category === "string"
            && typeof value.message === "string" && typeof value.filename === "string"
            && Number.isInteger(value.lineno);
    } catch {
        // Older backends may still use Python's default warning header.
        return /^.+:\d+:\s+[A-Za-z]\w*Warning:\s/.test(line);
    }
};
