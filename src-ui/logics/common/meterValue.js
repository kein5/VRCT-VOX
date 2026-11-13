export const updateMeterValue = (previous, data, state = "ok") => {
    if (previous.state === state && Object.is(previous.data, data)) return previous;
    return { state, data };
};
