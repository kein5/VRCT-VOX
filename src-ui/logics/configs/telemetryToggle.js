// The usage data switch on the settings page (Settings → Advanced).
//
// The backend starts sending only from the answer to the one-time notice (SEC-07):
// /set/enable/telemetry alone is not consent. While the notice is unanswered, turning the
// switch on here sends that answer ("send"): this page shows what is sent, as the notice does.
// Turning it off is an answer of its own, so it goes through the usual switch.
export const toggleTelemetryOrAnswer = ({ currentTelemetry, currentTelemetryNotice, toggleTelemetry, setTelemetryNotice, getTelemetry }) => {
    if (currentTelemetryNotice?.data?.pending === true && currentTelemetry?.data !== true) {
        return Promise.resolve(setTelemetryNotice({ send: true })).then(() => getTelemetry());
    }
    return toggleTelemetry();
};
