import styles from "./ContactsContainer.module.scss";

export const ContactsContainer = () => {
    return (
        <div className={styles.container}>
            <OpenLinkContainer className={styles.github_issues} href_id="github_issues" text="VRCT-TTS Issues"/>
        </div>
    );
};

import dev_github_icon from "@images/about_vrct/dev_github_icon.png";

const contacts_links = {
    github_issues: { img: dev_github_icon, href: "https://github.com/kein5/VRCT-TTS/issues" },
};

const OpenLinkContainer = ({className, href_id, text}) => {
    const href = contacts_links[href_id].href;
    const img = contacts_links[href_id].img;
    return (
        <a className={className} href={href} target="_blank" rel="noreferrer" >
            <img className={styles.contact_button_icon} src={img} />
            <p className={styles.contact_button_label}>{text}</p>
        </a>
    );
};