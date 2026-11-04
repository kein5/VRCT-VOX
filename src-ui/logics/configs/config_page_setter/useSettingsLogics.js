import { useState, useEffect, useCallback, useMemo, useRef, useId } from "react";
import * as stores from "@store";
import { useStdoutToPython } from "@useStdoutToPython";
import { useNotificationStatus } from "@logics_common";
import { deviceOptionsToObject, arrayToObject, arrayToIdLabel, transformToIndexedArray } from "@utils";
import { setSaveBarEntry } from "../../voice/saveBar";

const transformResponse = (transformName, payload) => {
    if (!transformName) return payload;

    switch (transformName) {
        case "deviceOptionsToObject":
            return deviceOptionsToObject(payload);
        case "arrayToObject":
            return arrayToObject(payload);
        case "arrayToIdLabel":
            return arrayToIdLabel(payload);
        case "transformToIndexedArray":
            return transformToIndexedArray(payload);
        default:
            throw new Error(`[transformResponse] Unknown transform name: "${transformName}". Please add it to the switch in useSettingsLogics.js.`);
    }
};

export const useSettingsLogics = (settingsArray, Category) => {
    const { asyncStdoutToPython } = useStdoutToPython();
    const { showNotification_SaveSuccess } = useNotificationStatus();

    const filtered = settingsArray.filter((s) => s.Category === Category);
    const result = {};


    for (const s of filtered) {
        const base = s.Base_Name;
        let storeHook = undefined;

        if (typeof stores.getStoreHook === "function") {
            storeHook = stores.getStoreHook(base);
        }

        if (!storeHook) {
            const hookName = `useStore_${base}`;
            storeHook = stores[hookName];
        }

        if (!storeHook) {
            console.warn(`[useSettingsLogics] store hook not found for ${base}`);
            continue;
        }

        const store = storeHook();

        const currentKey = `current${base}`;
        const updateKey = `update${base}`;
        const pendingKey = `pending${base}`;

        const current = store[currentKey];
        const update = store[updateKey];
        const pending = store[pendingKey];

        const currentExportName = `current${base}`;
        const updateExportName = `update${base}`;
        const updateFromBackendExportName = `updateFromBackend${base}`;
        const getExportName = `get${base}`;
        const setExportName = `set${base}`;
        const deleteExportName = `delete${base}`;
        const toggleExportName = `toggle${base}`;
        const setSuccessExportName = `setSuccess${base}`;
        const deleteSuccessExportName = `deleteSuccess${base}`;

        const runExportName = `runSuccess${base}`;

        // To use by UI------------------------------------
        const buildGet = () => {
            return () => {
                if (pending) pending();
                return asyncStdoutToPython(`/get/data/${s.base_endpoint_name}`);
            };
        };

        const buildSet = () => {
            return (value) => {
                if (pending) pending();
                return asyncStdoutToPython(`/set/data/${s.base_endpoint_name}`, value);
            };
        };

        const buildDelete = () => {
            return (value) => {
                if (pending) pending();
                return asyncStdoutToPython(`/delete/data/${s.base_endpoint_name}`, value);
            };
        };

        const buildRun = () => {
            return () => {
                asyncStdoutToPython(`/run/${s.base_endpoint_name}`);
            };
        };


        // To use a response from backend------------------------------------
        const buildSuccessHandler = (transformName) => {
            return (payload) => {
                const transformed = transformResponse(transformName, payload);
                if (update) update(transformed);
                showNotification_SaveSuccess();
            };
        };

        const buildUpdateFromBackend = (transformName) => {
            return (payload) => {
                const transformed = transformResponse(transformName, payload);
                if (update) update(transformed);
            };
        };


        result[currentExportName] = current;
        result[updateExportName] = update;
        result[updateFromBackendExportName] = buildUpdateFromBackend(s.response_transform ?? null);

        if (s.add_endpoint_run_array?.includes("to_backend")) {
            result[runExportName] = buildRun();
        }


        if (s.logics_template_id === "get_list") {
            result[getExportName] = buildGet();
            continue;
        }

        if (s.logics_template_id === "get_only") {
            result[getExportName] = buildGet();
            continue;
        }

        if (s.logics_template_id === "get_set") {
            result[getExportName] = buildGet();
            result[setExportName] = buildSet();
            result[setSuccessExportName] = buildSuccessHandler(s.response_transform ?? null);
            continue;
        }

        if (s.logics_template_id === "get_set_delete") {
            result[getExportName] = buildGet();
            result[setExportName] = buildSet();
            result[setSuccessExportName] = buildSuccessHandler(s.response_transform ?? null);
            result[deleteExportName] = buildDelete();
            result[deleteSuccessExportName] = buildSuccessHandler(s.response_transform ?? null);
            continue;
        }

        if (s.logics_template_id === "toggle_enable_disable") {
            result[getExportName] = buildGet();
            result[toggleExportName] = () => {
                if (pending) pending();
                const isOn = current && current.data;
                if (isOn) {
                    asyncStdoutToPython(`/set/disable/${s.base_endpoint_name}`);
                } else {
                    asyncStdoutToPython(`/set/enable/${s.base_endpoint_name}`);
                }
            };

            result[setSuccessExportName] = buildSuccessHandler(s.response_transform ?? null);
            continue;
        }

        if (s.logics_template_id === "weight_download_status") {
            result[setSuccessExportName] = buildSuccessHandler(s.response_transform ?? null);

            result[`updateDownloadProgress${base}`] = (payload) => {
                update((old_status) => {
                    return old_status.data.map((item) =>
                        payload.weight_type === item.id && item.is_pending
                            ? { ...item, job_id: payload.job_id, progress: payload.progress * 100 }
                            : item
                    );
                });
            };
            result[`updateDownloaded${base}`] = (downloaded_weight_type_status) => {
                update((old_status) => {
                    return old_status.data.map((item) => ({
                        ...item,
                        is_downloaded: downloaded_weight_type_status[item.id] ?? item.is_downloaded,
                    }));
                });
            };
            result[`pending${base}`] = (id) => {
                update((old_status) => {
                    return old_status.data.map((item) =>
                        id === item.id
                            ? { ...item, is_pending: true, job_id: null }
                            : item
                    );
                });
            };
            result[`downloaded${base}`] = (payload) => {
                const id = typeof payload === "string" ? payload : payload?.weight_type;
                update((old_status) => {
                    return old_status.data.map((item) =>
                        id === item.id && (typeof payload === "string" || payload?.downloaded === true)
                            ? { ...item, is_downloaded: true, is_pending: false, progress: null }
                            : item
                    );
                });
            };

            result[`download${base}`] = (weight_type) => {
                asyncStdoutToPython(`/run/download_${s.base_endpoint_name}`, weight_type);
            };

            continue;
        }
    }

    return { settings: result };
};


export const useConfigFunctions = (Category) => {
    const { asyncStdoutToPython } = useStdoutToPython();

    switch (Category) {
        case "Vr":
            return {
                sendTextToOverlay: (text) => {
                    asyncStdoutToPython("/run/send_text_overlay", text);
                },
            };
        default:
            return {};
    }
};


export const useSliderLogic = ({
    variable,
    state,
    setterFunction,
    postUpdateAction,
    min,
    max,
    step = 1,
    show_label_values = null,
    marks_step,
    setter_timing = "on_change_committed",
}) => {
    const [ui_value, setUiValue] = useState(variable);
    const debounceTimerRef = useRef(null);

    const debouncedSetter = useCallback((value) => {
        if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current);
        }
        debounceTimerRef.current = setTimeout(() => {
            Promise.resolve(setterFunction(value)).then(sent => { if (sent === false) setUiValue(variable); });
            debounceTimerRef.current = null;
        }, 200);
    }, [setterFunction, variable]);

    useEffect(() => {
        return () => {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current);
            }
        };
    }, []);

    const marks = useMemo(() => {
        if (show_label_values === null && marks_step === undefined) {
            return null;
        }

        const markMap = new Map();

        // 1. marks_step が明示的に指定されている場合、min から max まで marks_step 刻みで目盛りを生成
        if (marks_step !== undefined && marks_step > 0) {
            const decimalPlaces = marks_step.toString().includes('.')
                ? marks_step.toString().split('.')[1].length
                : 0;

            let current = min;
            for (let i = 0; i <= 1000; i++) {
                if (current > max + (marks_step / 10)) break;
                const fixedValue = parseFloat(current.toFixed(decimalPlaces));
                const hasLabel = show_label_values && show_label_values.includes(fixedValue);
                markMap.set(fixedValue, {
                    value: fixedValue,
                    label: hasLabel ? `${fixedValue}` : "",
                });
                current += marks_step;
            }
        }

        // 2. show_label_values が指定されている場合、その値は必ず mark として含める（label付き）
        if (show_label_values && Array.isArray(show_label_values)) {
            for (const val of show_label_values) {
                if (val >= min && val <= max) {
                    markMap.set(val, {
                        value: val,
                        label: `${val}`,
                    });
                }
            }
        }

        return Array.from(markMap.values()).sort((a, b) => a.value - b.value);
    }, [min, max, marks_step, show_label_values]);

    // setter_timing の値によってuseCallbackの呼び出し数が変わるとHooksルール違反になるため、
    // 常に同数のuseCallbackを呼び出し、公開する関数だけをsetter_timingで切り替える
    const onChangeForOnChange = useCallback((value) => {
        setUiValue(value);
        debouncedSetter(value);
    }, [debouncedSetter]);

    const onChangeForCommitted = useCallback((value) => {
        setUiValue(value);
    }, []);

    const onChangeCommittedForCommitted = useCallback((value) => {
        Promise.resolve(setterFunction(value)).then(sent => { if (sent === false) setUiValue(variable); });
    }, [setterFunction, variable]);

    let onChangeFunction;
    let onChangeCommittedFunction;

    if (setter_timing === "on_change") {
        onChangeFunction = onChangeForOnChange;
        onChangeCommittedFunction = null;
    } else if (setter_timing === "on_change_committed") {
        onChangeFunction = onChangeForCommitted;
        onChangeCommittedFunction = onChangeCommittedForCommitted;
    } else {
        console.error(`Invalid 'setter_timing' value provided to useSliderLogic. Expected 'on_change' or 'on_change_committed'. Received: ${setter_timing}`);
    }

    useEffect(() => {
        if (state === "pending") return;
        if (variable !== ui_value) {
            setUiValue(variable);
        }
        if (postUpdateAction) {
            postUpdateAction();
        }
    }, [variable, state]);

    return {
        ui_value,
        onChangeFunction,
        onChangeCommittedFunction,
        marks,
    };
};


// A text field saved from the config page top bar, like every other settings
// form; `label` names it in the bar's list of changes. Enter still saves the
// one field.
export const useSaveButtonLogic = ({
    variable,
    state,
    setFunction,
    deleteFunction,
    label,
}) => {
    const [input_value, setInputValue] = useState(variable);
    const [submitted, setSubmitted] = useState(false);

    const onChangeFunction = (value) => {
        setInputValue(value);
    };

    const saveFunction = async () => {
        setSubmitted(true);
        const empty = input_value === "" || input_value === null;
        const sent = await (empty && typeof deleteFunction === "function"
            ? deleteFunction() : setFunction(empty ? "" : input_value));
        // An immediate transport failure can be batched with pending by React.
        // Restore the local draft even when no pending render was committed.
        if (sent === false) { setInputValue(variable); setSubmitted(false); }
        return sent;
    };

    useEffect(() => {
        if (state === "pending") return;
        setInputValue(variable);
        setSubmitted(false);
    }, [variable, state]);

    // Loading is also "pending"; only a save sent from here shows as saving.
    const saving = submitted && state === "pending";
    const dirty = !saving && String(input_value ?? "") !== String(variable ?? "");
    const id = useId();
    const latest = useRef();
    latest.current = { saveFunction, discard: () => setInputValue(variable) };
    useEffect(() => {
        setSaveBarEntry(id, {
            dirty, edited: dirty, saving, saveState: saving ? "saving" : dirty ? "unsaved" : "saved",
            changes: dirty && label ? [label] : [], canSave: state !== "pending",
            save: () => latest.current.saveFunction(), discard: () => latest.current.discard(),
        });
    }, [id, dirty, saving, label, state]);
    useEffect(() => () => setSaveBarEntry(id, null), [id]);

    return {
        variable: input_value,
        onChangeFunction: onChangeFunction,
        saveFunction: saveFunction,
    };
};

const createMarks = (min, max, marks_step = 1, labelFormatter = (value) => value) => {
    const marks = [];
    let current = min;

    const decimalPlaces = marks_step.toString().includes('.')
        ? marks_step.toString().split('.')[1].length
        : 0;

    for (let i = 0; i <= 1000; i++) {
        // Use a small epsilon for the comparison to handle floating point errors
        if (current > max + (marks_step / 10)) break;

        const fixedValue = parseFloat(current.toFixed(decimalPlaces));
        marks.push({ value: fixedValue, label: `${labelFormatter(fixedValue)}` });

        current += marks_step;
    }
    return marks;
};
