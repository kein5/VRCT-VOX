import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "@useI18n";
import { useVr } from "@logics_configs";
import { SectionLabelComponent } from "../_components";
import { CheckboxContainer, RadioButtonContainer, SliderContainer } from "../_templates/Templates";
import styles from "./Vr.module.scss";

// Captions over the desktop, for VRChat without a headset. The section is
// shown only where the overlay window exists (Windows for now), so nobody is
// offered a switch that does nothing.
export const DesktopCaptionOverlay = () => {
    const { t } = useI18n();
    const {
        currentIsEnabledOverlayDesktop,
        toggleIsEnabledOverlayDesktop,
        currentOverlayDesktopSettings,
        setOverlayDesktopSettings,
        currentIoFlowOverlaySettings,
        setIoFlowOverlaySettings,
    } = useVr();
    const [supported, setSupported] = useState(false);
    useEffect(() => {
        let disposed = false;
        invoke("caption_overlay_supported").then(value => { if (!disposed) setSupported(value === true); }, () => {});
        return () => { disposed = true; };
    }, []);
    if (!supported) return null;

    const settings = currentOverlayDesktopSettings.data;
    const state = currentOverlayDesktopSettings.state;
    const change = (key, value) => setOverlayDesktopSettings({ ...settings, [key]: value });
    // The flow strip shares the caption window; it can be on while captions are off.
    const flow = currentIoFlowOverlaySettings.data;
    const flowState = currentIoFlowOverlaySettings.state;
    const changeFlow = (key, value) => setIoFlowOverlaySettings({ ...flow, [key]: value });
    return (
        <div className={styles.common_container}>
            <SectionLabelComponent label={t("config_page.vr.section_label_desktop_overlay")} />
            <CheckboxContainer
                setting_id="desktop_overlay"
                label={t("config_page.vr.desktop_overlay.label")}
                desc={t("config_page.vr.desktop_overlay.desc")}
                variable={currentIsEnabledOverlayDesktop}
                toggleFunction={toggleIsEnabledOverlayDesktop}
            />
            <RadioButtonContainer
                setting_id="desktop_overlay_position"
                label={t("config_page.vr.desktop_overlay_position.label")}
                selectFunction={value => change("position", value)}
                name="desktop_overlay_position"
                options={[
                    { id: "bottom", label: t("config_page.vr.desktop_overlay_position.bottom") },
                    { id: "top", label: t("config_page.vr.desktop_overlay_position.top") },
                ]}
                checked_variable={{ data: settings.position, state }}
            />
            <SliderContainer
                setting_id="desktop_overlay_font_size"
                label={t("config_page.vr.desktop_overlay_font_size.label")}
                valueLabelFormat="value px"
                state={state}
                variable={settings.font_size}
                setterFunction={value => change("font_size", value)}
                min={16}
                max={72}
                step={2}
                show_label_values={[16, 28, 40, 56, 72]}
            />
            <SliderContainer
                setting_id="desktop_overlay_display_duration"
                label={t("config_page.vr.desktop_overlay_display_duration.label")}
                valueLabelFormat={value => t("config_page.common.duration_seconds", { count: value })}
                state={state}
                variable={settings.display_duration}
                setterFunction={value => change("display_duration", value)}
                min={1}
                max={60}
                step={1}
                show_label_values={[1, 10, 20, 30, 40, 50, 60]}
            />
            <SliderContainer
                setting_id="desktop_overlay_opacity"
                label={t("config_page.vr.desktop_overlay_opacity.label")}
                desc={t("config_page.vr.desktop_overlay_opacity.desc")}
                valueLabelFormat="value %"
                state={state}
                variable={Math.round(settings.opacity * 100)}
                setterFunction={value => change("opacity", value / 100)}
                min={0}
                max={100}
                step={5}
                show_label_values={[0, 20, 40, 60, 80, 100]}
            />
            <CheckboxContainer
                setting_id="io_flow_overlay"
                label={t("io_flow.settings.desktop")}
                desc={t("io_flow.settings.desktop_description")}
                variable={{ data: flow.desktop === true, state: flowState }}
                toggleFunction={() => changeFlow("desktop", flow.desktop !== true)}
            />
            <RadioButtonContainer
                setting_id="io_flow_overlay_count"
                label={t("io_flow.settings.count")}
                selectFunction={value => changeFlow("count", value)}
                name="io_flow_overlay_count"
                options={[1, 2, 3].map(count => ({ id: count, label: t("io_flow.settings.count_value", { count }) }))}
                checked_variable={{ data: flow.count, state: flowState }}
            />
        </div>
    );
};
