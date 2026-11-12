import { CredentialPair } from "../_components/credential_pair/CredentialPair";
import { SpeechServers } from "../advanced_settings/SpeechServers";
import { useI18n } from "@useI18n";
import styles from "./Transcription.module.scss";
import { RealtimeASRSettings } from "./RealtimeASRSettings";
import { genNumObjArray } from "@utils";
import { useEffect, useState } from "react";

import {
    useTranscription,
    useSaveButtonLogic,
} from "@logics_configs";

import { CLOUD_TRANSCRIPTION_ENGINES } from "../../../../../../logics/configs/cloudTranscription";

import {
    WordFilterContainer,
    DownloadModelsContainer,
    RadioButtonContainer,
    DropdownMenuContainer,
    SliderContainer,
    SwitchBoxContainer,
    AuthKeyContainer,
} from "../_templates/Templates";

import {
    SectionLabelComponent,
} from "../_components";

import { ComputeDevice } from "../_components/compute_device/ComputeDevice";
import { Description } from "../_components/description/Description";
import { SetupSection } from "../_components/setup_section/SetupSection";
import { LegacyModelDownloadDialog } from "../_components/download_models/LegacyModelDownloadDialog";
import { AutoDownloadModelsContainer } from "../shared_items/SharedItems";

export const Transcription = () => {
    return (
        <div className={styles.container}>
            {/* Which engine listens comes first: it decides what else on this page applies.
                The timing numbers for the microphone and the speaker follow it, folded. */}
            <TranscriptionEngine_Container />
            <CloudTranscription_Container />
            <Mic_Container />
            <Speaker_Container />
            <RealtimeASRSettings />
            <SpeechServers profiles={["asr"]} />
        </div>
    );
};


// The numbers that tune how speech is cut into messages are set once, if ever.
// They sit in one fold whose line shows the values in use, so the page stays
// short and nothing has to be opened to see what is set.
const TimingFold = ({ silence, length, queue, children }) => {
    const { t } = useI18n();
    return (
        <SetupSection title={t("config_page.transcription.timing_title")}
            status={t("config_page.transcription.timing_status", { silence: silence ?? "-", length: length ?? "-", queue: queue ?? "-" })}>
            {children}
        </SetupSection>
    );
};

const Mic_Container = () => {
    const { t } = useI18n();
    const { currentMicRecordTimeout, currentMicPhraseTimeout, currentMicMaxWords } = useTranscription();
    return (
        <div>
            <SectionLabelComponent label={t("config_page.transcription.section_label_mic")} />
            <MicWordFilter_Box />
            <TimingFold silence={currentMicRecordTimeout.data} length={currentMicPhraseTimeout.data} queue={currentMicMaxWords.data}>
                <MicRecordTimeout_Box />
                <MicPhraseTimeout_Box />
                <MicMaxWords_Box />
            </TimingFold>
        </div>
    );
};

const MicRecordTimeout_Box = () => {
    const { t } = useI18n();
    const { currentMicRecordTimeout, setMicRecordTimeout } = useTranscription();

    const selectFunction = (selected_data) => {
        setMicRecordTimeout(selected_data.selected_id);
    };

    return (
        <DropdownMenuContainer
            dropdown_id="mic_record_timeout"
            label={t("config_page.transcription.mic_record_timeout.label")}
            desc={t("config_page.transcription.mic_record_timeout.desc")}
            selected_id={currentMicRecordTimeout.data}
            list={genNumObjArray(31)}
            selectFunction={selectFunction}
            state={currentMicRecordTimeout.state}
        />
    );
};
const MicPhraseTimeout_Box = () => {
    const { t } = useI18n();
    const { currentMicPhraseTimeout, setMicPhraseTimeout } = useTranscription();

    const selectFunction = (selected_data) => {
        setMicPhraseTimeout(selected_data.selected_id);
    };

    return (
        <DropdownMenuContainer
            dropdown_id="mic_phrase_timeout"
            label={t("config_page.transcription.mic_phrase_timeout.label")}
            desc={t("config_page.transcription.mic_phrase_timeout.desc")}
            selected_id={currentMicPhraseTimeout.data}
            list={genNumObjArray(31)}
            selectFunction={selectFunction}
            state={currentMicPhraseTimeout.state}
        />
    );
};
const MicMaxWords_Box = () => {
    const { t } = useI18n();
    const { currentMicMaxWords, setMicMaxWords } = useTranscription();

    const selectFunction = (selected_data) => {
        setMicMaxWords(selected_data.selected_id);
    };

    return (
        <DropdownMenuContainer
            dropdown_id="mic_max_phrase"
            label={t("config_page.transcription.mic_max_phrase.label")}
            desc={t("config_page.transcription.mic_max_phrase.desc")}
            selected_id={currentMicMaxWords.data}
            list={genNumObjArray(31)}
            selectFunction={selectFunction}
            state={currentMicMaxWords.state}
        />
    );
};

const MicWordFilter_Box = () => {
    const { t } = useI18n();

    return (
        <WordFilterContainer
            label={t("config_page.transcription.mic_word_filter.label")}
            desc={t("config_page.transcription.mic_word_filter.desc")}
        />
    );
};




const Speaker_Container = () => {
    const { t } = useI18n();
    const { currentSpeakerRecordTimeout, currentSpeakerPhraseTimeout, currentSpeakerMaxWords } = useTranscription();
    return (
        <div>
            <SectionLabelComponent label={t("config_page.transcription.section_label_speaker")} />
            <TimingFold silence={currentSpeakerRecordTimeout.data} length={currentSpeakerPhraseTimeout.data} queue={currentSpeakerMaxWords.data}>
                <SpeakerRecordTimeout_Box />
                <SpeakerPhraseTimeout_Box />
                <SpeakerMaxWords_Box />
            </TimingFold>
        </div>
    );
};

const SpeakerRecordTimeout_Box = () => {
    const { t } = useI18n();
    const { currentSpeakerRecordTimeout, setSpeakerRecordTimeout } = useTranscription();

    const selectFunction = (selected_data) => {
        setSpeakerRecordTimeout(selected_data.selected_id);
    };

    return (
        <DropdownMenuContainer
            dropdown_id="speaker_record_timeout"
            desc={t("config_page.transcription.speaker_record_timeout.desc")}
            label={t("config_page.transcription.speaker_record_timeout.label")}
            selected_id={currentSpeakerRecordTimeout.data}
            list={genNumObjArray(31)}
            selectFunction={selectFunction}
            state={currentSpeakerRecordTimeout.state}
        />
    );
};
const SpeakerPhraseTimeout_Box = () => {
    const { t } = useI18n();
    const { currentSpeakerPhraseTimeout, setSpeakerPhraseTimeout } = useTranscription();

    const selectFunction = (selected_data) => {
        setSpeakerPhraseTimeout(selected_data.selected_id);
    };
    return (
        <DropdownMenuContainer
            dropdown_id="speaker_phrase_timeout"
            label={t("config_page.transcription.speaker_phrase_timeout.label")}
            desc={t("config_page.transcription.speaker_phrase_timeout.desc")}
            selected_id={currentSpeakerPhraseTimeout.data}
            list={genNumObjArray(31)}
            selectFunction={selectFunction}
            state={currentSpeakerPhraseTimeout.state}
        />
    );
};
const SpeakerMaxWords_Box = () => {
    const { t } = useI18n();
    const { currentSpeakerMaxWords, setSpeakerMaxWords } = useTranscription();

    const selectFunction = (selected_data) => {
        setSpeakerMaxWords(selected_data.selected_id);
    };

    return (
        <DropdownMenuContainer
            dropdown_id="speaker_max_phrase"
            label={t("config_page.transcription.speaker_max_phrase.label")}
            desc={t("config_page.transcription.speaker_max_phrase.desc")}
            selected_id={currentSpeakerMaxWords.data}
            list={genNumObjArray(61)}
            selectFunction={selectFunction}
            state={currentSpeakerMaxWords.state}
        />
    );
};



const TranscriptionEngine_Container = () => {
    const { t } = useI18n();
    const { currentSelectedTranscriptionEngine, currentMicAvgLogprob, currentMicNoSpeechProb,
        currentSpeakerAvgLogprob, currentSpeakerNoSpeechProb } = useTranscription();
    const pair = (confidence, silence) => `${confidence.data ?? "-"} / ${silence.data ?? "-"}`;

    return (
        <div>
            <SectionLabelComponent label={t("config_page.transcription.section_label_transcription_engines")} />
            <TranscriptionEngine_Box />
            {/* Also on the translation page: one switch fetches both models. */}
            <AutoDownloadModelsContainer />
            {currentSelectedTranscriptionEngine.data === "Whisper" && (
                <>
                    <WhisperWeightType_Box />
                    <TranscriptionComputeDevice_Box />
                    {/* Whisper's own thresholds: the defaults suit most voices, so they are folded too. */}
                    <SetupSection title={t("config_page.transcription.thresholds_title")}
                        status={t("config_page.transcription.thresholds_status", {
                            mic: pair(currentMicAvgLogprob, currentMicNoSpeechProb),
                            speaker: pair(currentSpeakerAvgLogprob, currentSpeakerNoSpeechProb) })}>
                        <MicAvgLogprobContainer />
                        <MicNoSpeechProbContainer />
                        <SpeakerAvgLogprobContainer />
                        <SpeakerNoSpeechProbContainer />
                    </SetupSection>
                </>
            )}
        </div>
    );
};

export const TranscriptionEngine_Box = () => {
    const { t } = useI18n();
    const { currentSelectedTranscriptionEngine, setSelectedTranscriptionEngine, currentSelectableTranscriptionEngines } = useTranscription();
    const available = currentSelectableTranscriptionEngines.data || [];

    // A cloud engine can be chosen once the backend has accepted its key.
    const cloud_options = CLOUD_TRANSCRIPTION_ENGINES.map(engine => {
        const usable = available.includes(engine.id) || currentSelectedTranscriptionEngine.data === engine.id;
        return {
            id: engine.id,
            label: t(`config_page.transcription.select_transcription_engine.engines.${engine.key}`),
            disabled: !usable,
        };
    });

    return (
        <RadioButtonContainer
            label={t("config_page.transcription.select_transcription_engine.label")}
            desc={<span className={styles.engine_help}>
                <span>{t("config_page.transcription.select_transcription_engine.desc")}</span>
                <span role="status">{t("transcription_consent.selected", {
                    engine: currentSelectedTranscriptionEngine.data || t("transcription_consent.unselected"),
                })}</span>
                {currentSelectedTranscriptionEngine.data === "Google" && <span>{t("transcription_consent.google_notice")}</span>}
            </span>}
            selectFunction={setSelectedTranscriptionEngine}
            name="select_transcription_engine"
            options={[
                { id: "Google", label: "Google" },
                { id: "Whisper", label: "Whisper" },
                ...cloud_options,
            ]}
            checked_variable={currentSelectedTranscriptionEngine}
        />
    );
};

const CloudTranscription_Container = () => {
    const { t } = useI18n();
    const transcription = useTranscription();
    const { getSelectableTranscriptionEngines, getSelectedTranscriptionEngine } = transcription;
    // A saved, rejected or removed key changes which engines the backend can
    // use; the saved selection stays unchanged. Ask again each time.
    const watched = CLOUD_TRANSCRIPTION_ENGINES.map(engine => transcription[`current${engine.base}AuthKey`].data);
    watched.push(transcription.currentCustomWhisperURL.data);
    useEffect(() => {
        getSelectableTranscriptionEngines();
        getSelectedTranscriptionEngine();
    }, watched);

    return (
        <div data-setting-id="cloud_section">
            <SectionLabelComponent label={t("config_page.transcription.cloud_section.label")} />
            <Description text={t("config_page.transcription.cloud_section.desc")} />
            {/* One line per provider, as on the translation page: the line says whether it can
                be used, and the one that is selected above stays open. */}
            {CLOUD_TRANSCRIPTION_ENGINES.map(engine => {
                const in_use = transcription.currentSelectedTranscriptionEngine.data === engine.id;
                const usable = (transcription.currentSelectableTranscriptionEngines.data || []).includes(engine.id);
                return (
                    <SetupSection key={engine.id} title={t(`config_page.transcription.select_transcription_engine.engines.${engine.key}`)} attention={in_use}
                        status={t(`config_page.translation.provider_${in_use ? "in_use" : usable ? "ready" : "not_set"}`)}>
                        {engine.has_url
                            ? <CredentialPair settings={transcription} base={engine.base} provider={engine.key} section="transcription" />
                            : <CloudAuthKey_Box engine={engine} />}
                        <CloudModel_Box engine={engine} />
                    </SetupSection>
                );
            })}
        </div>
    );
};

const CloudAuthKey_Box = ({ engine }) => {
    const { t } = useI18n();
    const transcription = useTranscription();
    const current = transcription[`current${engine.base}AuthKey`];
    const label = t(`config_page.transcription.${engine.key}_auth_key.label`);

    const { variable, onChangeFunction, saveFunction } = useSaveButtonLogic({
        variable: current.data,
        state: current.state,
        setFunction: transcription[`set${engine.base}AuthKey`],
        deleteFunction: transcription[`delete${engine.base}AuthKey`],
        label,
    });

    return (
        <AuthKeyContainer
            label={label}
            desc={engine.has_url ? t(`config_page.transcription.${engine.key}_auth_key.desc`) : undefined}
            webpage_url={engine.webpage_url}
            variable={variable}
            state={current.state}
            onChangeFunction={onChangeFunction}
            saveFunction={saveFunction}
            remove_border_bottom={true}
        />
    );
};

const CloudModel_Box = ({ engine }) => {
    const { t } = useI18n();
    const transcription = useTranscription();
    const auth_key = transcription[`current${engine.base}AuthKey`];
    const selectable = transcription[`currentSelectable${engine.base}ModelList`];
    const selected = transcription[`currentSelected${engine.base}Model`];
    const setSelected = transcription[`setSelected${engine.base}Model`];

    const selected_label = (!auth_key.data && !selected.data)
        ? t("config_page.common.correct_auth_key_required")
        : selected.data;

    return (
        <DropdownMenuContainer
            dropdown_id={`select_${engine.key}_model`}
            label={t(`config_page.transcription.select_${engine.key}_model.label`)}
            selected_id={selected_label}
            list={selectable.data}
            selectFunction={selected_data => setSelected(selected_data.selected_id)}
            state={selected.state}
            is_disabled={!auth_key.data}
        />
    );
};

const WhisperWeightType_Box = () => {
    const { t } = useI18n();
    const {
        currentWhisperWeightTypeStatus,
        pendingWhisperWeightTypeStatus,
        downloadWhisperWeightTypeStatus,
    } = useTranscription();
    const { currentSelectedWhisperWeightType, setSelectedWhisperWeightType } = useTranscription();

    const selectFunction = (id) => {
        setSelectedWhisperWeightType(id);
    };

    const [downloadReview, setDownloadReview] = useState(null);
    const downloadStartFunction = (id) => setDownloadReview(id);
    const download = (request) => {
        pendingWhisperWeightTypeStatus(request.weight_type);
        downloadWhisperWeightTypeStatus(request);
    };

    const whisper_weight_types = currentWhisperWeightTypeStatus.data.map(item => {
        return {
            ...item,
            label: item.id,
        };
    });

    return (
        <>
            {downloadReview && <LegacyModelDownloadDialog kind="whisper" weightType={downloadReview}
                onCancel={() => setDownloadReview(null)} onDownload={download} />}
            <DownloadModelsContainer
                label={t("config_page.transcription.whisper_weight_type.label")}
                desc={t(
                    "config_page.transcription.whisper_weight_type.desc",
                    { translator: t("main_page.translator") }
                )}
                name="whisper_weight_type"
                options={whisper_weight_types}
                checked_variable={currentSelectedWhisperWeightType}
                selectFunction={selectFunction}
                downloadStartFunction={downloadStartFunction}
            />
        </>
    );
};

const TranscriptionComputeDevice_Box = () => {
    const { t } = useI18n();
    const {
        currentSelectableTranscriptionComputeDeviceList,
        currentSelectedTranscriptionComputeDevice,
        setSelectedTranscriptionComputeDevice,
        currentSelectedTranscriptionComputeType,
        setSelectedTranscriptionComputeType,
    } = useTranscription();

    return (
        <ComputeDevice
            label={t("config_page.transcription.transcription_compute_device.label")}
            dropdownIdPrefix="transcription"
            currentDeviceList={currentSelectableTranscriptionComputeDeviceList}
            currentSelectedDevice={currentSelectedTranscriptionComputeDevice}
            setSelectedDevice={setSelectedTranscriptionComputeDevice}
            currentSelectedComputeType={currentSelectedTranscriptionComputeType}
            setSelectedComputeType={setSelectedTranscriptionComputeType}
        />
    );
};






const MicAvgLogprobContainer = () => {
    const { t } = useI18n();
    const { currentMicAvgLogprob, setMicAvgLogprob } = useTranscription();
    return (
        <SliderContainer
            label={t("config_page.transcription.mic_avg_logprob.label")}
            desc={t("config_page.transcription.mic_avg_logprob.desc")}
            state={currentMicAvgLogprob.state}
            variable={currentMicAvgLogprob.data}
            setterFunction={setMicAvgLogprob}
            min={-2}
            max={0}
            step={0.1}
            marks_step={0.1}
            show_label_values={[-2, -1.8, -1.6, -1.4, -1.2, -1, -0.8, -0.6, -0.4, -0.2, 0]}
        />
    );
};

const MicNoSpeechProbContainer = () => {
    const { t } = useI18n();
    const { currentMicNoSpeechProb, setMicNoSpeechProb } = useTranscription();

    return (
        <SliderContainer
            label={t("config_page.transcription.mic_no_speech_prob.label")}
            desc={t("config_page.transcription.mic_no_speech_prob.desc")}
            state={currentMicNoSpeechProb.state}
            variable={currentMicNoSpeechProb.data}
            setterFunction={setMicNoSpeechProb}
            min={0}
            max={1}
            step={0.1}
            marks_step={0.1}
            show_label_values={[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]}
        />
    );
};

const SpeakerAvgLogprobContainer = () => {
    const { t } = useI18n();
    const { currentSpeakerAvgLogprob, setSpeakerAvgLogprob } = useTranscription();

    return (
        <SliderContainer
            label={t("config_page.transcription.speaker_avg_logprob.label")}
            desc={t("config_page.transcription.speaker_avg_logprob.desc")}
            state={currentSpeakerAvgLogprob.state}
            variable={currentSpeakerAvgLogprob.data}
            setterFunction={setSpeakerAvgLogprob}
            min={-2}
            max={0}
            step={0.1}
            marks_step={0.1}
            show_label_values={[-2, -1.8, -1.6, -1.4, -1.2, -1, -0.8, -0.6, -0.4, -0.2, 0]}
        />
    );
};

const SpeakerNoSpeechProbContainer = () => {
    const { t } = useI18n();
    const { currentSpeakerNoSpeechProb, setSpeakerNoSpeechProb } = useTranscription();

    return (
        <SliderContainer
            label={t("config_page.transcription.speaker_no_speech_prob.label")}
            desc={t("config_page.transcription.speaker_no_speech_prob.desc")}
            state={currentSpeakerNoSpeechProb.state}
            variable={currentSpeakerNoSpeechProb.data}
            setterFunction={setSpeakerNoSpeechProb}
            min={0}
            max={1}
            step={0.1}
            marks_step={0.1}
            show_label_values={[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]}
        />
    );
};
