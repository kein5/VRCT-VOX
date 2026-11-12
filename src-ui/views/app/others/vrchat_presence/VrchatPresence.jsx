import { useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import { useOthers } from "@logics_configs";
import { EnvReadout } from "../../config_page/setting_section/setting_box/_components/env_readout/EnvReadout";

// "Sent" in the log only means the message left: VRChat does not answer. A
// VRChat on this PC advertises OSC while its OSC is enabled, and the app can
// see that. This says it in words: found, not found (with the step that turns
// OSC on), or that this PC cannot tell. It asks again every few seconds while
// it is on screen, so starting VRChat or enabling OSC shows up by itself.
export const VrchatPresence = ({ className }) => {
    const { t } = useI18n();
    const { currentVrchatOscPresence, getVrchatOscPresence, currentEnableSendMessageToVrc } = useOthers();
    // The hook hands out a new function on every render; keep the latest without restarting the timer.
    const ask = useRef(getVrchatOscPresence);
    ask.current = getVrchatOscPresence;
    const sends = currentEnableSendMessageToVrc.data !== false;
    useEffect(() => {
        if (!sends) return;
        ask.current();
        const timer = setInterval(() => ask.current(), 5000);
        return () => clearInterval(timer);
    }, [sends]);
    if (!sends) return <EnvReadout className={className}><p>{t("vrchat_presence.sending_off")}</p></EnvReadout>;
    const state = ["found", "not_found", "unknown"].includes(currentVrchatOscPresence.data) ? currentVrchatOscPresence.data : "checking";
    return (
        <EnvReadout className={className} tone={{ found: "active", not_found: "warning" }[state] ?? "neutral"}>
            <p>{t(`vrchat_presence.${state}`)}</p>
            {state === "not_found" && <p>{t("vrchat_presence.not_found_hint")}</p>}
        </EnvReadout>
    );
};
