// A usage event as rows a person can read. Every field of the event becomes a row: a field
// this file does not know is shown under its own name with its raw value, never left out,
// so what is listed here cannot fall behind what is sent.

const PLAIN = ["timestamp", "app_version", "os", "os_version", "locale", "error_code", "v"];
const GPU_KNOWN = ["name", "kind", "vram_gb", "driver"];

const raw = value => typeof value === "string" ? value : JSON.stringify(value);

const gpuText = (gpu, t) => {
    if (!gpu || typeof gpu !== "object" || Array.isArray(gpu)) return raw(gpu);
    const parts = [];
    if ("name" in gpu) parts.push(String(gpu.name));
    if ("kind" in gpu) parts.push(t(`telemetry_contents.gpu_kind.${gpu.kind}`, { defaultValue: String(gpu.kind) }));
    if ("vram_gb" in gpu) parts.push(`${gpu.vram_gb} GB`);
    if ("driver" in gpu) parts.push(t("telemetry_contents.gpu_driver", { version: gpu.driver }));
    for (const [key, value] of Object.entries(gpu)) {
        if (!GPU_KNOWN.includes(key)) parts.push(`${key}: ${raw(value)}`);
    }
    return parts.join(" / ");
};

export const telemetryRows = (body, t) => {
    const rows = [];
    const field = (key, value) => rows.push({ key, label: t(`telemetry_contents.fields.${key}`), value });
    const unknown = (path, value) => rows.push({ key: path, label: path, value: raw(value) });
    if (!body || typeof body !== "object" || Array.isArray(body)) return rows;
    for (const [key, value] of Object.entries(body)) {
        if (key === "event") field("event", t(`telemetry_contents.events.${value}`, { defaultValue: String(value) }));
        // The timestamp is shown as it is sent (ISO 8601, UTC).
        else if (PLAIN.includes(key)) field(key, String(value));
        else if (key === "hw" && value && typeof value === "object" && !Array.isArray(value)) {
            for (const [name, part] of Object.entries(value)) {
                if (name === "cpu" || name === "cores") field(`hw_${name}`, String(part));
                else if (name === "ram_gb") field("hw_ram_gb", `${part} GB`);
                else if (name === "gpus" && Array.isArray(part)) {
                    part.forEach((gpu, index) => rows.push({
                        key: `hw_gpu_${index}`, label: t("telemetry_contents.fields.hw_gpu", { number: index + 1 }), value: gpuText(gpu, t),
                    }));
                } else unknown(`hw.${name}`, part);
            }
        } else unknown(key, value);
    }
    return rows;
};

// One line for an event that was sent: its kind, and its error code when it has one.
export const sentSummary = (body, t) => {
    const kind = t(`telemetry_contents.events.${body?.event}`, { defaultValue: String(body?.event) });
    return typeof body?.error_code === "string" ? `${kind} (${body.error_code})` : kind;
};
