// Advisory only: measured memory on one GPU plus explicit headroom.
// Never add GPU memories or change the execution device / saved model path.
export function modelAdvice(models, hardware, { now = Date.now(), reserveBytes = 2 * 1024 ** 3, deviceMode = 'auto' } = {}) {
    const result = { recommended: null, reason: 'unknown', device: null, multiple: false };
    if (deviceMode === 'cpu') return { ...result, reason: 'cpu' };
    if (hardware?.phase !== 'ready') return result;
    if (!Number.isFinite(hardware.measured_at_ms) || now - hardware.measured_at_ms > 120000 || now < hardware.measured_at_ms)
        return { ...result, reason: 'stale' };
    const devices = hardware.devices.filter(row => ['gpu', 'igpu'].includes(row.kind));
    const device = devices[0];
    if (!device) return { ...result, reason: hardware.devices.some(row => row.kind === 'cpu') ? 'cpu' : 'unknown' };
    const context = { ...result, device, multiple: devices.length > 1 };
    if (device.kind === 'igpu') return { ...context, reason: 'shared_memory' };
    if (!Number.isSafeInteger(device.memory_free) || !Number.isSafeInteger(device.memory_total) || device.memory_total <= 0)
        return { ...context, reason: 'unknown_memory' };
    const eligible = models.filter(row => row.guidance?.validation?.state === 'passed' && row.guidance.reference_memory_bytes > 0);
    // A 25% model allowance and the user's headroom are guidance, not a reservation.
    const chosen = eligible.find(row => Math.max(row.guidance.reference_memory_bytes,
        row.guidance.validation.sampled_peak_bytes ?? 0) * 1.25 + reserveBytes <= device.memory_free);
    return { ...context, recommended: chosen?.id ?? null, reason: chosen ? 'fits' : eligible.length ? 'low_memory' : 'unverified' };
}
