import styles from "./AboutVrct.module.scss";
import logo_en from "@images/brand/logo-en.svg";
import logo_ja from "@images/brand/logo-ja.svg";
import logo_ko from "@images/brand/logo-ko.svg";
import logo_zh_hant from "@images/brand/logo-zh-Hant.svg";
import logo_zh_hans from "@images/brand/logo-zh-Hans.svg";

import dev_section_title from "@images/about_vrct/dev_section_title.png";
import dev_misya from "@images/about_vrct/dev_misya.png";
import dev_shiina from "@images/about_vrct/dev_shiina.png";
import vrct_logo_for_about_vrct from "@images/about_vrct/vrct_logo_for_about_vrct.png";

import contributors_section_title from "@images/about_vrct/contributors_section_title.png";
import contributor_done from "@images/about_vrct/contributor_done.png";
import contributor_iya from "@images/about_vrct/contributor_iya.png";
import contributor_rera from "@images/about_vrct/contributor_rera.png";
import contributor_poposuke from "@images/about_vrct/contributor_poposuke.png";
import contributor_kumaguma from "@images/about_vrct/contributor_kumaguma.png";
import contributor_riku from "@images/about_vrct/contributor_riku.png";

import special_thanks_section_title from "@images/about_vrct/special_thanks_section_title.png";
import special_thanks_members from "@images/about_vrct/special_thanks_members.png";
import special_thanks_message_en from "@images/about_vrct/special_thanks_message_en.png";
import special_thanks_message_ja from "@images/about_vrct/special_thanks_message_ja.png";

import clsx from "clsx";
import { useI18n } from "@useI18n";
import { useAppearance } from "@logics_configs";
import { useSoftwareVersion } from "@logics_common";

import { generateLocalizedDocumentUrl } from "@ui_configs";

const logos = { en: logo_en, ja: logo_ja, ko: logo_ko, "zh-Hant": logo_zh_hant, "zh-Hans": logo_zh_hans };

const vrct_vox_url = "https://github.com/kein5/VRCT-VOX";
const vrct_vox_links = [
    { id: "repository", href: vrct_vox_url },
    { id: "releases", href: `${vrct_vox_url}/releases` },
    { id: "issues", href: `${vrct_vox_url}/issues` },
    { id: "licenses", href: `${vrct_vox_url}/blob/main/NOTICE.md` },
];

export const AboutVrct = () => {
    const { t, i18n } = useI18n();
    const { currentUiLanguage } = useAppearance();
    const { currentSoftwareVersion } = useSoftwareVersion();
    return (
        <div className={styles.container}>
            <section className={styles.vrct_vox_section}>
                <img src={logos[i18n.language] ?? logo_en} className={styles.vrct_vox_logo} alt="VRCT-VOX" />
                {currentSoftwareVersion.data && (
                    <p className={styles.vrct_vox_version}>{t("config_page.common.version", { version: currentSoftwareVersion.data })}</p>
                )}
                <p className={styles.vrct_vox_text}>{t("config_page.about_vrct.summary")}</p>
                <p className={styles.vrct_vox_text}>{t("config_page.about_vrct.fork_notice")}</p>
                <div className={styles.vrct_vox_links}>
                    {vrct_vox_links.map(link => (
                        <a key={link.id} className={styles.vrct_vox_link} href={link.href} target="_blank" rel="noreferrer">
                            {t(`config_page.about_vrct.links.${link.id}`)}
                        </a>
                    ))}
                </div>
            </section>

            <h2 className={styles.original_heading}>{t("config_page.about_vrct.original_heading")}</h2>
            <p className={styles.vrct_vox_text}>{t("config_page.about_vrct.original_desc")}</p>
            <div className={styles.dev_section}>
                <img src={dev_section_title} className={clsx(styles.section_title, styles.the_developers)} />
                <div className={styles.dev_section_wrapper}>
                    <div className={styles.dev_card_wrapper}>
                        <img src={dev_misya} className={styles.dev_card_img} />
                        <OpenLinkContainer className={styles.dev_misya_x} href_id="dev_misya_x" />
                        <OpenLinkContainer className={styles.dev_misya_github} href_id="dev_misya_github" />
                    </div>
                    <div className={styles.dev_card_wrapper}>
                        <img src={dev_shiina} className={styles.dev_card_img} />
                        <OpenLinkContainer className={styles.dev_shiina_x} href_id="dev_shiina_x" />
                    </div>
                </div>
            </div>

            <div className={styles.project_links_and_logo_section}>
                <div className={styles.about_vrct_logo_wrapper}>
                    <img src={vrct_logo_for_about_vrct} className={styles.about_vrct_logo} />
                </div>
                <div className={styles.project_links_wrapper}>
                    <OpenLinkContainer className={styles.project_link} href_id="project_link_documents" />
                    <OpenLinkContainer className={styles.project_link} href_id="project_link_vrct_github" />
                </div>
            </div>

            <div className={styles.contributors_section}>
                <img src={contributors_section_title} className={clsx(styles.section_title, styles.contributors)} />
                <div className={styles.contributors_img_wrapper}>
                    <div className={styles.contributor_card_wrapper}>
                        <img src={contributor_done} className={clsx(styles.contributors_img, styles.contributors)} />
                        <OpenLinkContainer className={styles.contributors_done_san_x} href_id="contributors_done_san_x" />
                    </div>
                    <div className={styles.contributor_card_wrapper}>
                        <img src={contributor_iya} className={clsx(styles.contributors_img, styles.contributors)} />
                        <OpenLinkContainer className={styles.contributors_iya_x} href_id="contributors_iya_x" />
                    </div>
                    <div className={styles.contributor_card_wrapper}>
                        <img src={contributor_rera} className={clsx(styles.contributors_img, styles.contributors)} />
                        <OpenLinkContainer className={styles.contributors_rera_x} href_id="contributors_rera_x" />
                        <OpenLinkContainer className={styles.contributors_rera_github} href_id="contributors_rera_github" />
                    </div>
                    <div className={styles.contributor_card_wrapper}>
                        <img src={contributor_poposuke} className={clsx(styles.contributors_img, styles.contributors)} />
                        <OpenLinkContainer className={styles.contributors_poposuke_x} href_id="contributors_poposuke_x" />
                    </div>
                    <div className={styles.contributor_card_wrapper}>
                        <img src={contributor_kumaguma} className={clsx(styles.contributors_img, styles.contributors)} />
                        <OpenLinkContainer className={styles.contributors_kumaguma_x} href_id="contributors_kumaguma_x" />
                    </div>
                    <div className={styles.contributor_card_wrapper}>
                        <img src={contributor_riku} className={clsx(styles.contributors_img, styles.contributors)} />
                        <OpenLinkContainer className={styles.contributors_riku_x} href_id="contributors_riku_x" />
                    </div>
                </div>
            </div>

            <div className={styles.special_thanks_section}>
                <img src={special_thanks_section_title} className={clsx(styles.section_title, styles.special_thanks)} />
                <img src={special_thanks_members} className={styles.special_thanks_members_img} />
                {
                    currentUiLanguage.data === "ja"
                    ? <img src={special_thanks_message_ja} className={styles.special_thanks_message_img} />
                    : <img src={special_thanks_message_en} className={styles.special_thanks_message_img} />
                }
            </div>


            <div className={styles.vrchat_disclaimer_section}>
                <p className={styles.vrchat_disclaimer}>VRCT-VOX and VRCT are not endorsed by VRChat and do not reflect the views or opinions of VRChat or anyone officially involved in producing or managing VRChat properties. VRChat and all associated properties are trademarks or registered trademarks of VRChat Inc. VRChat © VRChat Inc.</p>
            </div>


        </div>
    );
};

import dev_x_icon from "@images/about_vrct/dev_x_icon.png";
import dev_github_icon from "@images/about_vrct/dev_github_icon.png";
import contributors_x_icon from "@images/about_vrct/contributors_x_icon.png";
import contributors_github_icon from "@images/about_vrct/contributors_github_icon.png";

import project_link_documents from "@images/about_vrct/project_link_documents.png";
import project_link_vrct_github from "@images/about_vrct/project_link_vrct_github.png";

const about_vrct_links = {
    dev_misya_x: { img: dev_x_icon, href: "https://twitter.com/misya_ai" },
    dev_misya_github: { img: dev_github_icon, href: "https://github.com/misyaguziya" },
    dev_shiina_x: { img: dev_x_icon, href: "https://twitter.com/Shiina_12siy" },

    project_link_documents: { img: project_link_documents, href: (lang) => generateLocalizedDocumentUrl(lang).vrct_document_home_url },
    project_link_vrct_github: { img: project_link_vrct_github, href: "https://github.com/misyaguziya/VRCT" },

    contributors_done_san_x: { img: contributors_x_icon, href: "https://twitter.com/done_vrc" },
    contributors_iya_x: { img: contributors_x_icon, href: "https://twitter.com/IYAA_HHHH" },
    contributors_rera_x: { img: contributors_x_icon, href: "https://twitter.com/rerassi" },
    contributors_rera_github: { img: contributors_github_icon, href: "https://github.com/soumt-r" },
    contributors_poposuke_x: { img: contributors_x_icon, href: "https://twitter.com/sig_popo" },
    contributors_kumaguma_x: { img: contributors_x_icon, href: "https://twitter.com/K_kumaguma_A" },
    contributors_riku_x: { img: contributors_x_icon, href: "https://twitter.com/Riku7302" },
};

const OpenLinkContainer = ({className, href_id}) => {
    const { currentUiLanguage } = useAppearance();
    const link = about_vrct_links[href_id];
    const href = typeof link.href === "function" ? link.href(currentUiLanguage.data) : link.href;
    const img = link.img;
    return (
        <a className={className} href={href} target="_blank" rel="noreferrer" >
            {/* for adjust size to their parent component's width. */}
            <img style={ {height: "100%", width: "100%", "objectFit": "contain" }} src={img} />
        </a>
    );
};