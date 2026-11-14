"""COEIROINK v2 engine API (ADR-008).

Checked against COEIROINK 2.13.0's /openapi.json: GET /v1/engine_info, GET /v1/speakers_path_variant
(the speaker list without the base64 portraits that make /v1/speakers about 1 MB per speaker), and
POST /v1/synthesis with SynthesisParam, which answers audio/wav. Every scale field is required; the
values below are the engine UI's defaults. A voice is "<speakerUuid>:<styleId>".
"""
import re

from .external_engine import EngineClient
from .speechcpp_tts import CancelToken, SpeechError

DEFAULT_URL = 'http://127.0.0.1:50032'
SPEAKER_LIMIT = 4 * 1024 * 1024
WAV_LIMIT = 64 * 1024 * 1024
VOICE_ID = re.compile(r'([0-9A-Fa-f-]{1,64}):([0-9]{1,9})')
DEFAULT_SCALES = {'speedScale': 1.0, 'volumeScale': 1.0, 'pitchScale': 0.0, 'intonationScale': 1.0,
                  'prePhonemeLength': 0.1, 'postPhonemeLength': 0.1, 'outputSamplingRate': 24000}


class CoeiroinkTTS(EngineClient):
    def check_health(self, cancel_token=None):
        info = self.get_json('/v1/engine_info', cancel_token or CancelToken(), limit=4096)
        if not isinstance(info, dict) or not isinstance(info.get('version'), str):
            raise SpeechError(self.not_ready)
        return info['version']

    def list_voices(self, cancel_token=None):
        speakers = self.get_json('/v1/speakers_path_variant', cancel_token or CancelToken(), limit=SPEAKER_LIMIT)
        if not isinstance(speakers, list):
            raise SpeechError(self.not_ready)
        voices = []
        for speaker in speakers:
            if (not isinstance(speaker, dict) or not isinstance(speaker.get('speakerName'), str)
                    or not isinstance(speaker.get('speakerUuid'), str)):
                continue
            for style in speaker.get('styles') or ():
                if isinstance(style, dict) and type(style.get('styleId')) is int and isinstance(style.get('styleName'), str):
                    voice_id = f"{speaker['speakerUuid']}:{style['styleId']}"
                    if VOICE_ID.fullmatch(voice_id):
                        voices.append({'id': voice_id, 'speaker': speaker['speakerName'], 'style': style['styleName']})
        return voices

    def synthesize_piece(self, text, voice_id, token):
        match = VOICE_ID.fullmatch(voice_id)
        if not match:
            raise SpeechError('tts_engine_voice_missing')
        body = {**DEFAULT_SCALES, 'speakerUuid': match[1], 'styleId': int(match[2]), 'text': text}
        return self.request('POST', '/v1/synthesis', token, body=body, limit=WAV_LIMIT,
                            error_code='tts_engine_synthesis_failed', timeout=self.synthesis_timeout,
                            expect='audio/wav')
