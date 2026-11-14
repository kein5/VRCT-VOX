import yaml from "js-yaml";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en_yml from "./en.yml?raw";
import ja_yml from "./ja.yml?raw";

const translation_en = yaml.load(en_yml);
const translation_ja = yaml.load(ja_yml);


const resources = {
    en: { translation: translation_en },
    ja: { translation: translation_ja },
};

i18n
    .use(initReactI18next) // passes i18n down to react-i18next
    .init({
        resources,
        lng: "en",
        fallbackLng: "en",
        // debug: true,
        interpolation: {
        escapeValue: false, // react already safes from xss
    },
});

// The page language follows the UI, so screen readers pick the right voice and
// shared CJK characters draw in the language's own forms.
i18n.on("languageChanged", (lng) => {
    if (typeof document !== "undefined") document.documentElement.lang = lng;
});

export default i18n;
