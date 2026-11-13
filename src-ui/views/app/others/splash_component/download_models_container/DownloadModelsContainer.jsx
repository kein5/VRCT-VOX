import styles from "./DownloadModelsContainer.module.scss";
// VRCT-VOX's own logo, in English as on the startup screen beside it.
import brand_logo from "@images/brand/logo-en.svg";
import vrct_now_downloading from "@images/VRCT_now_downloading.png";

import {
    useTranslation,
    useTranscription,
} from "@logics_configs";

export const DownloadModelsContainer = () => {
    const { currentCTranslate2WeightTypeStatus } = useTranslation();
    const { currentWhisperWeightTypeStatus } = useTranscription();

    const downloadingCTranslate2 = currentCTranslate2WeightTypeStatus.data.filter(d => d.progress !== null);
    const downloadingWhisper = currentWhisperWeightTypeStatus.data.filter(d => d.progress !== null);

    if (downloadingCTranslate2.length === 0 && downloadingWhisper.length === 0) return null;

    return (
        <div className={styles.container}>
            <div className={styles.progress_container}>
                {downloadingCTranslate2.map((model) => (
                    <DownloadModelsProgress key={model.id} progress={model.progress} type_label={`Translation: ${model.id}`} />
                ))}
                {downloadingWhisper.map((model) => (
                    <DownloadModelsProgress key={model.id} progress={model.progress} type_label={`Transcription: ${model.id}`} />
                ))}
            </div>
            <div className={styles.labels_wrapper}>
                <img src={brand_logo} className={styles.logo_img} alt="VRCT-VOX" />
                <img src={vrct_now_downloading} className={styles.vrct_now_downloading_img} alt="Now downloading AI models for initialization..." />
            </div>
        </div>
    );
};


const DownloadModelsProgress = (props) => {
    if (props.progress === null) return null;
    const circular_progress = Math.floor(props.progress / 5) * 5;

    const progress_color = generateGradientColor({
        value: circular_progress,
        colorStart: [242, 242, 242], // #f2f2f2
        colorEnd: [72, 164, 149], // #48a495
    });

    return(
        <div className={styles.progress_bar_container}>
            <div className={styles.progress_bar_wrapper}>
                <div
                    className={styles.progress_bar}
                    style={{
                        width: `${props.progress}%`,
                        backgroundColor: progress_color,
                    }}
                />
            </div>
            <p className={styles.progress_label}>{`${props.type_label}: ${Math.round(props.progress)}%`}</p>
        </div>
    );
};


const generateGradientColor = ({ value, colorStart, colorEnd }) => {
    const normalizedValue = Math.max(0, Math.min(100, value)) / 100;
    const interpolatedColor = colorStart.map((start, i) => {
        const end = colorEnd[i];
        return Math.round(start + (end - start) * normalizedValue);
    });
    const hexColor = `#${interpolatedColor.map(val => val.toString(16).padStart(2, '0')).join('')}`;
    return hexColor;
};