import { useState, useMemo, useCallback } from "react";
import { useI18n } from "@useI18n";
import { useStore_SelectedConfigTabId } from "@store";
import { useOcr } from "@logics_configs";
import { useRealtimeASR } from "../../../transcription/useRealtimeASR";
import { createLanguageNames } from "../../../common/languageNames.js";
import { ui_configs } from "@ui_configs";
import i18n from "@root/locales/config.js";
import { requestSettingsNavigation } from "../../../voice/settingsNavigation";

// 検索の元にする config_page 以下の文言の名前空間
const VALID_TABS = [
    "device",
    "appearance",
    "translation",
    "transcription",
    "vrchat",
    "ocr",
    // "vr",
    // "hotkeys",
    "tts", "rvc",
    "advanced_settings",
    "others",
];

// 名前空間と実際のページが違うもの。チャット読み取りと旧「その他」の項目は
// VRChat ページにある。
const NAMESPACE_TAB = {
    ocr: "vrchat",
    others: "vrchat",
};

// 名前空間の既定と違うページに置いた項目。複数のページに置いた項目は、
// 検索結果にもページごとに出す。
const SETTING_TABS = {
    "others.auto_clear_the_message_box": ["appearance"],
    "others.auto_export_message_logs": ["advanced_settings"],
    "others.vrc_mic_mute_sync": ["vrchat", "device"],
    "others.section_label_reading_aids": ["appearance"],
    "others.common_convert_message_hiragana_romaji": ["appearance"],
    "others.convert_message_to_romaji": ["appearance"],
    "others.convert_message_to_hiragana": ["appearance"],
    "others.auto_download_models": ["translation", "transcription"],
    "advanced_settings.section_label_osc": ["vrchat"],
    "advanced_settings.osc_ip_address": ["vrchat"],
    "advanced_settings.osc_port": ["vrchat"],
};

export const settingTabs = (namespace, key) =>
    SETTING_TABS[`${namespace}.${key}`] ?? [NAMESPACE_TAB[namespace] ?? namespace];

const TAB_LABEL_KEYS = {
    vrchat: "config_page.side_menu_labels.vrchat",
    device: "config_page.side_menu_labels.device",
    appearance: "config_page.side_menu_labels.appearance",
    translation: "config_page.side_menu_labels.translation",
    transcription: "config_page.side_menu_labels.transcription",
    // vr: "config_page.side_menu_labels.vr",
    // hotkeys: "config_page.side_menu_labels.hotkeys",
    tts: "config_page.side_menu_labels.tts",
    rvc: "config_page.side_menu_labels.rvc",
    advanced_settings: "config_page.side_menu_labels.advanced_settings",
};

// 親項目（前提条件）の依存関係
const PREREQUISITES = {
    whisper_weight_type: {
        parent_id: "select_transcription_engine",
        required_label: "Whisper",
    },
    transcription_compute_device: {
        parent_id: "select_transcription_engine",
        required_label: "Whisper",
    },
};

// オブジェクト内のすべての文字列値を再帰的に収集
const collectStrings = (obj) => {
    const list = [];
    if (!obj) return list;
    if (typeof obj === "string") {
        list.push(obj);
        return list;
    }
    if (typeof obj === "object") {
        for (const val of Object.values(obj)) {
            list.push(...collectStrings(val));
        }
    }
    return list;
};

// 文字列内の {{variable}} などのテンプレート変数を整理
const cleanTemplateStr = (str) => {
    return typeof str === "string" ? str.replace(/\{\{[^}]+\}\}/g, "").trim() : "";
};

export const useConfigSearch = () => {
    const { t, i18n: i18nHook } = useI18n();
    const { currentSelectedConfigTabId, updateSelectedConfigTabId } = useStore_SelectedConfigTabId();
    const { currentSelectableOcrSourceLanguageList, currentOcrSourceLanguage } = useOcr();
    const { models, settings } = useRealtimeASR();
    const [query, setQuery] = useState("");

    // config_page 以下のリソースから動的に検索インデックスを生成
    const allEntries = useMemo(() => {
        const currentLng = i18nHook.language;
        const curRes = i18n.getResource(currentLng, "translation")?.config_page || {};
        const enRes = i18n.getResource("en", "translation")?.config_page || {};
        const isEn = currentLng === "en";

        const names = createLanguageNames(currentLng);
        const english = createLanguageNames("en");
        const entries = [];

        for (const tab of VALID_TABS) {
            const curTab = curRes[tab] || {};
            const enTab = enRes[tab] || {};
            const allKeys = new Set([...Object.keys(curTab), ...Object.keys(enTab)]);

            for (const key of allKeys) {
                const curVal = curTab[key];
                const enVal = enTab[key];

                if (!curVal && !enVal) continue;
                // A group of texts with no label of its own (status messages, model
                // notes) is not a setting; listing it would show its raw key.
                const labelled = (v) => typeof v === "string" || (v && (v.label || v.label_for_automatic || v.label_for_manual));
                if (!labelled(curVal) && !labelled(enVal)) continue;
                // A section's description string belongs to its title (section_desc
                // → section_title); on its own it would be listed under its full text.
                const descKey = key.replace(/_(title|label)$/, "_desc");
                if (/_desc$/.test(key) && typeof (curVal ?? enVal) === "string" && ["_title", "_label"].some(suffix => { const title = key.replace(/_desc$/, suffix); return curTab[title] || enTab[title]; })) continue;
                const sectionDesc = descKey !== key && typeof (curTab[descKey] ?? enTab[descKey]) === "string" ? { cur: curTab[descKey], en: enTab[descKey] } : null;

                // label の抽出（currentLng → en フォールバック）
                const rawLabel = (typeof curVal === "object" ? (curVal.label || curVal.label_for_automatic || curVal.label_for_manual) : null)
                    ?? (typeof enVal === "object" ? (enVal.label || enVal.label_for_automatic || enVal.label_for_manual) : null)
                    ?? (typeof curVal === "string" ? curVal : (typeof enVal === "string" ? enVal : key));

                // desc の抽出
                const rawDesc = (typeof curVal === "object" ? (curVal.desc || curVal.desc_for_automatic || curVal.desc_for_manual) : null)
                    ?? (typeof enVal === "object" ? (enVal.desc || enVal.desc_for_automatic || enVal.desc_for_manual) : null)
                    ?? sectionDesc?.cur ?? sectionDesc?.en
                    ?? "";

                // 検索対象テキストの収集（現在言語 + en の両方を包含）
                const searchStrings = [];
                if (curVal) {
                    searchStrings.push(...collectStrings(curVal));
                }
                if (!isEn && enVal) {
                    searchStrings.push(...collectStrings(enVal));
                }
                if (sectionDesc) searchStrings.push(...[sectionDesc.cur, isEn ? null : sectionDesc.en].filter(Boolean));

                if (tab === "ocr" && key === "source_language") {
                    const languages = new Set([...Object.keys(currentSelectableOcrSourceLanguageList.data ?? {}), currentOcrSourceLanguage.data]);
                    for (const language of languages) {
                        if (language) searchStrings.push(names.searchText({ language }));
                    }
                }
                if (tab === "appearance" && key === "ui_language") {
                    for (const option of ui_configs.selectable_ui_languages) {
                        searchStrings.push(option.label, names.fromCode(option.id), english.fromCode(option.id));
                    }
                }
                const searchTarget = searchStrings
                    .map((s) => cleanTemplateStr(s).normalize("NFKC").toLowerCase())
                    .filter(Boolean);

                for (const page of settingTabs(tab, key)) {
                    entries.push({
                        tab: page,
                        setting_id: tab === "ocr" && key === "source_language" ? "ocr_source_language" : key,
                        label: cleanTemplateStr(rawLabel),
                        desc: cleanTemplateStr(rawDesc),
                        tab_label: t(TAB_LABEL_KEYS[page] ?? page),
                        searchTarget,
                        prereq: PREREQUISITES[key] || null,
                    });
                }
            }
        }
        const realtimeLanguages = new Set([
            ...(models.models?.flatMap(model => model.languages ?? []) ?? []),
            settings?.mic?.language, settings?.speaker?.language,
        ]);
        entries.push({
            tab: "transcription", setting_id: "realtime_asr", label: t("realtime.title"),
            desc: t("realtime.auto_help"), tab_label: t(TAB_LABEL_KEYS.transcription), prereq: null,
            searchTarget: [t("realtime.title"), t("realtime.mic_language"), t("realtime.speaker_language"),
                ...[...realtimeLanguages].filter(Boolean).flatMap(code => code === "auto"
                    ? [t("realtime.auto_language"), "auto"] : [code, names.fromCode(code), english.fromCode(code)])]
                .map(text => text.normalize("NFKC").toLowerCase()),
        });
        return entries;
    }, [i18nHook.language, t, currentSelectableOcrSourceLanguageList.data, currentOcrSourceLanguage.data, models, settings]);

    const results = useMemo(() => {
        const q = query.normalize("NFKC").trim().toLowerCase();
        if (q.length < 1) return [];

        return allEntries.filter((entry) => {
            return entry.searchTarget.some((text) => text.includes(q));
        });
    }, [query, allEntries]);

    const clearQuery = useCallback(() => setQuery(""), []);

    const navigateToSetting = useCallback((result) => {
        const navigate = () => {
            clearQuery();
            if (currentSelectedConfigTabId.data !== result.tab) {
                updateSelectedConfigTabId(result.tab, { voice_navigation_confirmed: true });
            }

            let attempts = 0;
            const findAndScroll = () => {
                let target =
                    document.querySelector(`[data-setting-id="${CSS.escape(result.setting_id)}"]`) ||
                    document.querySelector(`[data-setting-label="${CSS.escape(result.label)}"]`);

                // 条件付き非表示などでDOMにない場合、親項目へフォールバック
                if (!target && result.prereq) {
                    target = document.querySelector(`[data-setting-id="${CSS.escape(result.prereq.parent_id)}"]`);
                }

                if (target) {
                    // Native details keep their children mounted even when folded.
                    for (let ancestor = target.parentElement; ancestor; ancestor = ancestor.parentElement) {
                        if (ancestor.tagName === "DETAILS") ancestor.open = true;
                    }
                    const controls = target.querySelectorAll("input:not([type='hidden']), select, textarea, button, a[href], summary, [tabindex]");
                    const available = Array.from(controls).filter(node => !node.matches(":disabled, [aria-disabled='true'], [tabindex='-1']") &&
                        !node.closest("[hidden], [inert]") && node.getClientRects().length > 0);
                    // Help disclosures and documentation links may precede the actual field.
                    const control = available.find(node => node.matches("input, select, textarea, [role='switch'], [role='combobox'], [role='slider']")) ?? available[0];
                    if (control) {
                        control.focus({ preventScroll: true });
                    } else {
                        const previousTabIndex = target.getAttribute("tabindex");
                        target.setAttribute("tabindex", "-1");
                        target.addEventListener("blur", () => {
                            if (previousTabIndex === null) target.removeAttribute("tabindex");
                            else target.setAttribute("tabindex", previousTabIndex);
                        }, { once: true });
                        target.focus({ preventScroll: true });
                    }
                    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                    target.scrollIntoView({ behavior: reducedMotion ? "instant" : "smooth", block: "center" });
                    target.classList.remove("search_target_highlight");
                    void target.offsetWidth; // trigger reflow
                    target.classList.add("search_target_highlight");
                    setTimeout(() => {
                        target.classList.remove("search_target_highlight");
                    }, 2500);
                } else if (attempts < 25) {
                    attempts++;
                    setTimeout(findAndScroll, 40);
                }
            };

            setTimeout(findAndScroll, 60);
        };
        if (currentSelectedConfigTabId.data !== result.tab) requestSettingsNavigation(navigate);
        else navigate();
    }, [clearQuery, currentSelectedConfigTabId.data, updateSelectedConfigTabId]);

    return { query, setQuery, results, clearQuery, navigateToSetting };
};
