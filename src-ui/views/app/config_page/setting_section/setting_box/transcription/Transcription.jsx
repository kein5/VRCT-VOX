import { SpeechServers } from "../advanced_settings/SpeechServers";
import { useI18n } from "@useI18n";
import styles from "./Transcription.module.scss";
import { RealtimeASRSettings } from "./RealtimeASRSettings";
import { genNumObjArray } from "@utils";
import { useEffect } from "react";

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
    EntryWithSaveButtonContainer,
} from "../_templates/Templates";

import {
    SectionLabelComponent,
} from "../_components";

import { ComputeDevice } from "../_components/compute_device/ComputeDevice";
import { Description } from "../_components/description/Description";

export const Transcription = () => {
    return (
        <div className={styles.container}>
            <Mic_Container />
            <Speaker_Container />
            <TranscriptionEngine_Container />
            <CloudTranscription_Container />
            <RealtimeASRSettings />
            <SpeechServers profiles={["asr"]} />
        </div>
    );
};


const Mic_Container = () => {
    const { t } = useI18n();
    return (
        <div>
            <SectionLabelComponent label={t("config_page.transcription.section_label_mic")} />
            <MicRecordTimeout_Box />
            <MicPhraseTimeout_Box />
            <MicMaxWords_Box />
            <MicWordFilter_Box />
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
    return (
        <div>
            <SectionLabelComponent label={t("config_page.transcription.section_label_speaker")} />
            <SpeakerRecordTimeout_Box />
            <SpeakerPhraseTimeout_Box />
            <SpeakerMaxWords_Box />
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
    const { currentSelectedTranscriptionEngine } = useTranscription();

    return (
        <div>
            <SectionLabelComponent label={t("config_page.transcription.section_label_transcription_engines")} />
            <TranscriptionEngine_Box />
            {currentSelectedTranscriptionEngine.data === "Whisper" && (
                <>
                    <WhisperWeightType_Box />
                    <TranscriptionComputeDevice_Box />
                    <MicAvgLogprobContainer />
                    <MicNoSpeechProbContainer />
                    <SpeakerAvgLogprobContainer />
                    <SpeakerNoSpeechProbContainer />
                </>
            )}
        </div>
    );
};

const TranscriptionEngine_Box = () => {
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
            desc={t("config_page.transcription.select_transcription_engine.desc")}
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
    // use, and may move the selection back to Whisper; ask again each time.
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
            {CLOUD_TRANSCRIPTION_ENGINES.map(engine => (
                <div key={engine.id}>
                    {engine.has_url && <CloudURL_Box engine={engine} />}
                    <CloudAuthKey_Box engine={engine} />
                    <CloudModel_Box engine={engine} />
                </div>
            ))}
        </div>
    );
};

const CloudURL_Box = ({ engine }) => {
    const { t } = useI18n();
    const transcription = useTranscription();
    const current = transcription[`current${engine.base}URL`];
    const label = t(`config_page.transcription.${engine.key}_url.label`);

    const { variable, onChangeFunction, saveFunction } = useSaveButtonLogic({
        variable: current.data,
        state: current.state,
        setFunction: transcription[`set${engine.base}URL`],
        label,
    });

    return (
        <EntryWithSaveButtonContainer
            label={label}
            desc={t(`config_page.transcription.${engine.key}_url.desc`)}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={current.state}
            remove_border_bottom={true}
            width="24rem"
        />
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

    const downloadStartFunction = (id) => {
        pendingWhisperWeightTypeStatus(id);
        downloadWhisperWeightTypeStatus(id);
    };

    const whisper_weight_types = currentWhisperWeightTypeStatus.data.map(item => {
        return {
            ...item,
            label: item.id,
        };
    });

    return (
        <>
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
