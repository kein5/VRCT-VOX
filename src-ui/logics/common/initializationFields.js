// Python sends null both for a failed getter and for a value that is simply
// unset (no API key, no model selected), so null is passed on as before. Only
// a field that must be an array, or a setter that throws, keeps its UI default.
export const applyInitializationFields = (result, routes, arrayFields, invalidEndpoint) => {
    const failed = [];
    const report = (endpoint, reason) => {
        failed.push(endpoint);
        // Getter values can contain credentials. Log the name and reason only.
        console.error("Sidecar initialization field unavailable", endpoint, reason);
    };
    if (!result || typeof result !== "object" || Array.isArray(result)) {
        report("/run/initialization_complete", "expected an object");
        return failed;
    }
    for (const [endpoint, value] of Object.entries(result)) {
        if (!Object.hasOwn(routes, endpoint)) {
            invalidEndpoint({ endpoint, result: value });
            continue;
        }
        if (arrayFields.has(endpoint) && !Array.isArray(value)) {
            report(endpoint, value == null ? "missing value" : "expected an array");
            continue;
        }
        try {
            routes[endpoint](value);
        } catch {
            report(endpoint, "could not apply value");
        }
    }
    return failed;
};
