export const PORT_INPUT_LIMITS = { min: 1, max: 65535, step: 1 };

// Keep the draft as text, but send exact integers over IPC. Never turn a
// decimal, exponent, sign or blank into a different valid port.
export function parsePortInput(value) {
    if (typeof value === "string" && !/^[0-9]+$/.test(value)) return null;
    if (typeof value !== "string" && typeof value !== "number") return null;
    const port = Number(value);
    return Number.isInteger(port) && port >= PORT_INPUT_LIMITS.min && port <= PORT_INPUT_LIMITS.max ? port : null;
}
