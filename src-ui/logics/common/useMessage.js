import {
    useStore_MessageLogs,
    useStore_MessageInputValue,
    store,
    Atom_MessageLogs,
} from "@store";

import { useStore } from "jotai";
import { realtimeStateAtom, realtimeRetiredAtom } from "../transcription/useRealtimeASR";
import { applyRealtimeCaption } from "../transcription/realtimeCaptionState";

import { useStdoutToPython } from "@useStdoutToPython";

const COOLDOWN = 2000; // 2 seconds

export const useMessage = () => {
    const { currentMessageLogs, addMessageLogs, updateMessageLogs } = useStore_MessageLogs();
    const { currentMessageInputValue, updateMessageInputValue } = useStore_MessageInputValue();
    const { asyncStdoutToPython } = useStdoutToPython();
    const atoms = useStore();

    const sendMessage = (message) => {
        const uuid = crypto.randomUUID();
        const send_message_object = {
            id: uuid,
            message: message,
        };
        asyncStdoutToPython("/run/send_message_box", send_message_object);

        addMessageLogs({
            id: uuid,
            category: "sent",
            status: "pending",
            created_at: generateTimeData(),
            messages: {
                original: { message: message, transliteration: [] },
                translations: [],
            },
        });
    };

    const addSystemMessageLog = (message) => {
        const uuid = crypto.randomUUID();
        const date = generateTimeData();

        addMessageLogs({
            id: uuid,
            category: "system",
            status: "system",
            created_at: date,
            messages: {
                original: { message: message, transliteration: [] },
                translations: [],
            },
        });
    };

    const addSystemMessageLog_FromBackend = (payload) => {
        addSystemMessageLog(payload.message);
    };

    const updateSentMessageLogById = (payload) => {
        updateMessageLogs(updateItemById(payload.id, payload));
    };

    const addSentMessageLog = (payload) => {
        const message_object = generateMessageObject(payload, "sent");
        updateMessageLogs((current) => [...current.data, message_object]);
    };

    const addReceivedMessageLog = (payload) => {
        const message_object = generateMessageObject(payload, "received");
        updateMessageLogs((current) => [...current.data, message_object]);
    };

    const updateRealtimeCaption = (payload) => {
        let active = atoms.get(realtimeStateAtom);
        const owner = active[payload?.source];
        // The first caption can beat the first ready-state poll. It may bind
        // only the already accepted backend generation, never revive a stop.
        if (owner?.requested && owner.generation === payload.generation && !owner.namespace) {
            active = { ...active, [payload.source]: { ...owner, namespace: payload.namespace } };
            atoms.set(realtimeStateAtom, active);
        }
        const logs = atoms.get(Atom_MessageLogs);
        const before = { rows: logs.data, retired: atoms.get(realtimeRetiredAtom) };
        const after = applyRealtimeCaption(before, payload, active);
        if (after !== before) {
            atoms.set(Atom_MessageLogs, { ...logs, state: "ok", data: after.rows });
            atoms.set(realtimeRetiredAtom, after.retired);
        }
    };

    const startTyping = () => {
        const now = Date.now();
        if (now - store.last_executed_time_startTyping >= 2000) {
            store.last_executed_time_startTyping = now;
            asyncStdoutToPython("/run/typing_message_box");
        }
    };

    const stopTyping = () => {
        asyncStdoutToPython("/run/stop_typing_message_box");
    };

    return {
        currentMessageLogs,
        sendMessage,
        addSystemMessageLog,
        addSystemMessageLog_FromBackend,
        updateSentMessageLogById,
        addSentMessageLog,
        addReceivedMessageLog,
        updateRealtimeCaption,

        currentMessageInputValue,
        updateMessageInputValue,

        startTyping,
        stopTyping,
    };
};

const generateTimeData = () => {
    return new Date().toLocaleTimeString(
        "ja-JP",
        { hour12: false, hour: "2-digit", minute: "2-digit" }
    );
};

const generateMessageObject = (data, category, status = "ok") => {
    return {
        id: data.id ?? crypto.randomUUID(),
        created_at: generateTimeData(),
        category: category,
        status: status,
        source: data.source,
        messages: {
            original: data.original,
            translations: data.translations ?? [],
        },
    };
};

const updateItemById = (id, updated_data) => (current_items) => {
    return current_items.data.map(item => {
        if (item.id === id) {
            if (updated_data.messages) {
                return { ...item, ...updated_data, created_at: item.created_at };
            }
            return {
                ...item,
                status: "ok",
                messages: {
                    ...item.messages,
                    translations: updated_data.translations ?? item.messages.translations,
                },
            };
        }
        return item;
    });
};