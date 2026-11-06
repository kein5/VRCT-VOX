import { useI18n } from "@useI18n";
import styles from "./AdvancedSettings.module.scss";
import { DirectVoiceSettings } from "./DirectVoiceSettings";
import { AutoExportMessageLogsContainer } from "../shared_items/SharedItems";
import { Description } from "../_components/description/Description";
import { parsePortInput, PORT_INPUT_LIMITS } from "../../../../../../logics/configs/networkPortInput";
import { buildObsBrowserSourceUrl } from "../../../../../../logics/configs/obsBrowserSourceUrl";

import { useCopyToClipboard, useOpenFolder } from "@logics_common";
import {
    useAdvancedSettings,
    useSaveButtonLogic,
} from "@logics_configs";

import {
    CheckboxContainer,
    ActionButtonContainer,
    EntryWithSaveButtonContainer,
    ColorEntryWithSaveButtonContainer,
} from "../_templates/Templates";

import {
    SectionLabelComponent,
} from "../_components";

import OpenFolderSvg from "@images/open_folder.svg?react";
import CopyThinSvg from "@images/copy_thin.svg?react";
import CheckMarkSvg from "@images/check_mark.svg?react";

export const AdvancedSettings = () => {
    const { t } = useI18n();

    return (
        <div className={styles.container}>
            {/* OSC moved to the VRChat page, which it addresses. */}
            <div>
                <SectionLabelComponent label={t("config_page.advanced_settings.section_label_logs")} />
                <AutoExportMessageLogsContainer />
            </div>
            <div>
                <SectionLabelComponent label={t("config_page.advanced_settings.section_label_config_file")} />
                <OpenConfigFolderContainer />
            </div>
            <WebsocketContainer />
            <DirectVoiceSettings variant="legacy" />
            <ObsBrowserSourceContainer />
        </div>
    );
};

export const OscIpAddressContainer = () => {
    const { t } = useI18n();
    const { currentOscIpAddress, setOscIpAddress } = useAdvancedSettings();

    const { variable, onChangeFunction, saveFunction } = useSaveButtonLogic({
        variable: currentOscIpAddress.data,
        state: currentOscIpAddress.state,
        setFunction: setOscIpAddress,
        label: t("config_page.advanced_settings.osc_ip_address.label"),
    });

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.osc_ip_address.label")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentOscIpAddress.state}
            width="14rem"
        />
    );
};

export const OscPortContainer = () => {
    const { t } = useI18n();
    const { currentOscPort, setOscPort } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentOscPort.data,
        state: currentOscPort.state,
        setFunction: (value) => setOscPort(parsePortInput(value)),
        label: t("config_page.advanced_settings.osc_port.label"),
    });

    const onChangeFunction = (value) => {
        if (value === "" || parsePortInput(value) !== null) rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.osc_port.label")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentOscPort.state}
            width="10rem"
            type="number"
            {...PORT_INPUT_LIMITS}
        />
    );
};

const OpenConfigFolderContainer = () => {
    const { t } = useI18n();
    const { openFolder_ConfigFile } = useOpenFolder();

    return (
        <>
            <ActionButtonContainer
                label={t("config_page.advanced_settings.open_config_filepath.label")}
                IconComponent={OpenFolderSvg}
                ClickedIconComponent={CheckMarkSvg}
                clicked_duration={1000}
                onclickFunction={openFolder_ConfigFile}
            />
        </>
    );
};

const WebsocketContainer = () => {
    return (
        <div>
            <SectionLabelComponent label="WebSocket" />
            <EnableWebsocketContainer />
            <WebsocketHostContainer />
            <WebsocketPortContainer />
            <WebsocketUrlContainer />
        </div>
    );
};

const EnableWebsocketContainer = () => {
    const { t } = useI18n();
    const { currentEnableWebsocket, toggleEnableWebsocket, currentEnableObsBrowserSource } = useAdvancedSettings();

    const is_locked = currentEnableObsBrowserSource.data === true;
    const add_warnings = [];
    if (is_locked) {
        add_warnings.push({ label: t("config_page.advanced_settings.enable_websocket.locked_by_obs_browser_source") });
    }

    return (
        <CheckboxContainer
            label={t("config_page.advanced_settings.enable_websocket.label")}
            variable={currentEnableWebsocket}
            toggleFunction={toggleEnableWebsocket}
            is_available={!is_locked}
            add_warnings={add_warnings}
        />
    );
};

const WebsocketHostContainer = () => {
    const { t } = useI18n();
    const { currentWebsocketHost, setWebsocketHost } = useAdvancedSettings();

    const { variable, onChangeFunction, saveFunction } = useSaveButtonLogic({
        variable: currentWebsocketHost.data,
        state: currentWebsocketHost.state,
        setFunction: setWebsocketHost,
        label: t("config_page.advanced_settings.websocket_host.label"),
    });

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.websocket_host.label")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentWebsocketHost.state}
            width="14rem"
        />
    );
};

const WebsocketPortContainer = () => {
    const { t } = useI18n();
    const { currentWebsocketPort, setWebsocketPort } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentWebsocketPort.data,
        state: currentWebsocketPort.state,
        setFunction: (value) => setWebsocketPort(parsePortInput(value)),
        label: t("config_page.advanced_settings.websocket_port.label"),
    });

    const onChangeFunction = (value) => {
        if (value === "" || parsePortInput(value) !== null) rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.websocket_port.label")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentWebsocketPort.state}
            width="10rem"
            type="number"
            {...PORT_INPUT_LIMITS}
        />
    );
};


const WebsocketUrlContainer = () => {
    const { t } = useI18n();
    const { copyToClipboard } = useCopyToClipboard();
    const { currentWebsocketHost, currentWebsocketPort, currentWebsocketAuthToken } = useAdvancedSettings();

    const host = currentWebsocketHost.data === "0.0.0.0" ? "127.0.0.1" : currentWebsocketHost.data;
    const token = currentWebsocketAuthToken.data;
    const base = `ws://${host}:${currentWebsocketPort.data}`;
    const url = token ? `${base}/?token=${encodeURIComponent(token)}` : base;
    // The token stays off screen (screenshots, streams); the copy has it.
    const shown = token ? `${base}/?token=••••••••` : base;

    return (
        <ActionButtonContainer
            label={t("config_page.advanced_settings.websocket_url.label")}
            desc={shown}
            IconComponent={CopyThinSvg}
            ClickedIconComponent={CheckMarkSvg}
            clicked_duration={1000}
            onclickFunction={() => copyToClipboard(url)}
        />
    );
};

const ObsBrowserSourceContainer = () => {
    const { t } = useI18n();

    return (
        <div>
            <SectionLabelComponent label={t("config_page.advanced_settings.obs_browser_source.section_label")} />
            <EnableObsBrowserSourceContainer />
            <ObsBrowserSourceUrlContainer />
            <ObsBrowserSourcePortContainer />
            <ObsBrowserSourceMaxMessagesContainer />
            <ObsBrowserSourceDisplayDurationContainer />
            <ObsBrowserSourceFadeoutDurationContainer />
            <ObsBrowserSourceFontSizeContainer />
            <ObsBrowserSourceFontColorContainer />
            <ObsBrowserSourceFontOutlineThicknessContainer />
            <ObsBrowserSourceFontOutlineColorContainer />
        </div>
    );
};

const EnableObsBrowserSourceContainer = () => {
    const { t } = useI18n();
    const { currentEnableObsBrowserSource, toggleEnableObsBrowserSource } = useAdvancedSettings();

    return (
        <CheckboxContainer
            label={t("config_page.advanced_settings.enable_obs_browser_source.label")}
            desc={t("config_page.advanced_settings.enable_obs_browser_source.desc")}
            variable={currentEnableObsBrowserSource}
            toggleFunction={toggleEnableObsBrowserSource}
        />
    );
};

const ObsBrowserSourceUrlContainer = () => {
    const { t } = useI18n();
    const { copyToClipboard } = useCopyToClipboard();
    const { currentWebsocketHost, currentObsBrowserSourcePort, currentWebsocketAuthToken } = useAdvancedSettings();

    const { url, shown } = buildObsBrowserSourceUrl(
        currentWebsocketHost.data, currentObsBrowserSourcePort.data, currentWebsocketAuthToken.data,
    );

    return (
        <>
            <ActionButtonContainer
                label={t("config_page.advanced_settings.obs_browser_source_url.label")}
                desc={shown}
                IconComponent={CopyThinSvg}
                ClickedIconComponent={CheckMarkSvg}
                clicked_duration={1000}
                onclickFunction={() => copyToClipboard(url)}
            />
            <Description
                text={t("config_page.advanced_settings.obs_browser_source_url.desc")}
                className={styles.obs_url_description}
                fold={false}
            />
        </>
    );
};

const ObsBrowserSourcePortContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourcePort, setObsBrowserSourcePort } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourcePort.data,
        state: currentObsBrowserSourcePort.state,
        setFunction: (value) => setObsBrowserSourcePort(parsePortInput(value)),
        label: t("config_page.advanced_settings.obs_browser_source_port.label"),
    });

    const onChangeFunction = (value) => {
        if (value === "" || parsePortInput(value) !== null) rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_port.label")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourcePort.state}
            width="10rem"
            type="number"
            {...PORT_INPUT_LIMITS}
        />
    );
};

const ObsBrowserSourceMaxMessagesContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourceMaxMessages, setObsBrowserSourceMaxMessages } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourceMaxMessages.data,
        state: currentObsBrowserSourceMaxMessages.state,
        setFunction: setObsBrowserSourceMaxMessages,
        label: t("config_page.advanced_settings.obs_browser_source_max_messages.label"),
    });

    const onChangeFunction = (value) => {
        rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_max_messages.label")}
            desc={t("config_page.advanced_settings.obs_browser_source_max_messages.desc")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourceMaxMessages.state}
            width="10rem"
            type="number"
            min={1} max={50} step={1}
        />
    );
};

const ObsBrowserSourceDisplayDurationContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourceDisplayDuration, setObsBrowserSourceDisplayDuration } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourceDisplayDuration.data,
        state: currentObsBrowserSourceDisplayDuration.state,
        setFunction: setObsBrowserSourceDisplayDuration,
        label: t("config_page.advanced_settings.obs_browser_source_display_duration.label"),
    });

    const onChangeFunction = (value) => {
        rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_display_duration.label")}
            desc={t("config_page.advanced_settings.obs_browser_source_display_duration.desc")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourceDisplayDuration.state}
            width="10rem"
            type="number"
            min={1} max={120} step={1}
        />
    );
};

const ObsBrowserSourceFadeoutDurationContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourceFadeoutDuration, setObsBrowserSourceFadeoutDuration } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourceFadeoutDuration.data,
        state: currentObsBrowserSourceFadeoutDuration.state,
        setFunction: setObsBrowserSourceFadeoutDuration,
        label: t("config_page.advanced_settings.obs_browser_source_fadeout_duration.label"),
    });

    const onChangeFunction = (value) => {
        rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_fadeout_duration.label")}
            desc={t("config_page.advanced_settings.obs_browser_source_fadeout_duration.desc")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourceFadeoutDuration.state}
            width="10rem"
            type="number"
            min={0} max={120} step={1}
        />
    );
};

const ObsBrowserSourceFontSizeContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourceFontSize, setObsBrowserSourceFontSize } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourceFontSize.data,
        state: currentObsBrowserSourceFontSize.state,
        setFunction: setObsBrowserSourceFontSize,
        label: t("config_page.advanced_settings.obs_browser_source_font_size.label"),
    });

    const onChangeFunction = (value) => {
        rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_font_size.label")}
            desc={t("config_page.advanced_settings.obs_browser_source_font_size.desc")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourceFontSize.state}
            width="10rem"
            type="number"
            min={10} max={200} step={1}
        />
    );
};

const ObsBrowserSourceFontColorContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourceFontColor, setObsBrowserSourceFontColor } = useAdvancedSettings();

    const { variable, onChangeFunction, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourceFontColor.data,
        state: currentObsBrowserSourceFontColor.state,
        setFunction: setObsBrowserSourceFontColor,
        label: t("config_page.advanced_settings.obs_browser_source_font_color.label"),
    });

    return (
        <ColorEntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_font_color.label")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourceFontColor.state}
            width="10rem"
        />
    );
};

const ObsBrowserSourceFontOutlineThicknessContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourceFontOutlineThickness, setObsBrowserSourceFontOutlineThickness } = useAdvancedSettings();

    const { variable, onChangeFunction: rawOnChange, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourceFontOutlineThickness.data,
        state: currentObsBrowserSourceFontOutlineThickness.state,
        setFunction: setObsBrowserSourceFontOutlineThickness,
        label: t("config_page.advanced_settings.obs_browser_source_font_outline_thickness.label"),
    });

    const onChangeFunction = (value) => {
        rawOnChange(value);
    };

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_font_outline_thickness.label")}
            desc={t("config_page.advanced_settings.obs_browser_source_font_outline_thickness.desc")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourceFontOutlineThickness.state}
            width="10rem"
            type="number"
            min={0} max={20} step={1}
        />
    );
};

const ObsBrowserSourceFontOutlineColorContainer = () => {
    const { t } = useI18n();
    const { currentObsBrowserSourceFontOutlineColor, setObsBrowserSourceFontOutlineColor } = useAdvancedSettings();

    const { variable, onChangeFunction, saveFunction } = useSaveButtonLogic({
        variable: currentObsBrowserSourceFontOutlineColor.data,
        state: currentObsBrowserSourceFontOutlineColor.state,
        setFunction: setObsBrowserSourceFontOutlineColor,
        label: t("config_page.advanced_settings.obs_browser_source_font_outline_color.label"),
    });

    return (
        <ColorEntryWithSaveButtonContainer
            label={t("config_page.advanced_settings.obs_browser_source_font_outline_color.label")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentObsBrowserSourceFontOutlineColor.state}
            width="10rem"
        />
    );
};
