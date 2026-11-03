import { atom } from "jotai/vanilla";
import { hooks, loadModule } from "./hookHarness.js";
import * as recovery from "../common/pendingRequestRecovery.js";
import * as initialization from "../common/initializationFields.js";
import * as exitExpectation from "../common/sidecarExitExpectation.js";
import * as meterValue from "../common/meterValue.js";
import * as utils from "../utils.js";

export const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};
export const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

export const loadBridgeStore = async (runtime = hooks()) => {
    const subscriptions = [];
    const jotai = { atom, getDefaultStore: () => runtime.store,
        useAtomValue: target => { subscriptions.push(target); return runtime.store.get(target); },
        useSetAtom: target => value => runtime.store.set(target, value),
    };
    const stores = await loadModule(new URL("../store.js", import.meta.url), runtime, {
        jotai,
        "./_test_data.js": {}, "@ui_configs": {},
        "./common/vrPanelTooltip": { keepNewestVrLayout: (_, next) => next },
        "./voice/settingsNavigation": { requestSettingsNavigation: action => action() },
        "./common/pendingRequestRecovery.js": recovery,
        "./common/meterValue.js": meterValue,
    });
    return { runtime, stores, jotai, subscriptions };
};

const noop = () => {};
const stubApi = (values = {}) => new Proxy({ __esModule: true, ...values }, {
    get: (target, key) => key in target ? target[key] : typeof key === "string" && key.startsWith("use") ? () => stubApi() : noop,
});

export const loadBridgeRoutes = async () => {
    const subject = await loadBridgeStore();
    const { runtime, stores, jotai } = subject;
    const notices = [], reads = [];
    const notification = {
        showNotification_Error: (key, options) => notices.push({ type: "error", key, options }),
        showNotification_Warning: (key, options) => notices.push({ type: "warning", key, options }),
        showNotification_Success: noop, showNotification_SaveSuccess: noop, dismissNotification: noop,
    };
    const common = stubApi({
        useNotificationStatus: () => notification,
        useIsBackendReady: stores.useStore_IsBackendReady,
        useIsSoftwareUpdating: stores.useStore_IsSoftwareUpdating,
    });
    const send = async endpoint => { reads.push(endpoint); return true; };
    const settingsLogics = await loadModule(new URL("../configs/config_page_setter/useSettingsLogics.js", import.meta.url), runtime, {
        "@store": stores, "@utils": utils, "@logics_common": common,
        "../../voice/saveBar": { setSaveBarEntry: noop },
    });
    const settings = await loadModule(new URL("../configs/config_page_setter/ui_config_setter.js", import.meta.url), runtime, {
        jotai, "@store": stores, "../../common/pendingRequestRecovery.js": recovery,
        "../../../views/vr/vr_layout.json": {},
        "@ui_configs": { ui_configs: {}, ctranslate2_weight_type_status: [], whisper_weight_type_status: [] },
        "./useSettingsLogics": settingsLogics,
    });
    const configs = stubApi(Object.fromEntries([...new Set(settings.SETTINGS_ARRAY.map(setting => setting.Category))]
        .map(category => [`use${category}`, settings.createCategoryHook(category)])));
    const main = stubApi();
    const errors = await loadModule(new URL("../_useBackendErrorHandling.js", import.meta.url), runtime, {
        "@logics_common": common, "@logics_main": main, "@logics_configs": configs,
        "@useI18n": { useI18n: () => ({ t: key => key, i18n: { exists: () => false } }) },
        "./ui_configs": { ui_configs: {} }, "./configs/cloudTranscription": { CLOUD_TRANSCRIPTION_ENGINES: [] },
    });
    const feature = values => stubApi({ send, reset: noop, backendStopped: noop, ...values });
    const voice = { useVoice: () => feature({ settings: null, status: {} }) };
    const speech = { useSpeechServers: () => feature({ state: {}, pending: {} }) };
    const downloads = { useModelDownloads: () => feature({ state: { jobs: {} }, hardware: {}, pending: null }) };
    const realtime = { useRealtimeASR: () => feature({ state: {} }) };
    const routes = await loadModule(new URL("../useReceiveRoutes.js", import.meta.url), runtime, {
        "@store": stores, "@logics_common": common, "@logics_main": main, "@logics_configs": configs,
        "./transcription/useRealtimeASR": realtime, "./voice/useVoice": voice,
        "./voice/useSpeechServers": speech, "./voice/useModelDownloads": downloads,
        "./_useBackendErrorHandling": errors,
        "./configs/config_page_setter/ui_config_setter": settings,
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: send }) },
        "./common/pendingRequestRecovery.js": recovery,
        "./common/initializationFields.js": initialization,
        "./common/sidecarExitExpectation.js": exitExpectation,
        "./main/languageMutations": { receiveLanguageMutation: noop, resetLanguageMutations: noop, isLanguageMutation: () => false },
    });
    return { ...subject, notices, reads, ...runtime.render(routes.useReceiveRoutes) };
};
