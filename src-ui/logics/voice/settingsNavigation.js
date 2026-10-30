// A page change is deferred while a voice form has an unsaved draft.
export function requestSettingsNavigation(proceed) {
    const event = new CustomEvent("vrct:settings-leave", { cancelable: true, detail: { proceed } });
    if (window.dispatchEvent(event)) proceed();
}
