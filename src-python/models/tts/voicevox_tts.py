"""VOICEVOX ENGINE API and the engines that keep it: SHAREVOX and AivisSpeech (ADR-008).

Checked against VOICEVOX ENGINE 0.26.1's /openapi.json: GET /version, GET /speakers,
POST /audio_query?text=&speaker=<style id>, POST /synthesis?speaker=<style id> with the AudioQuery
as the body, which answers audio/wav (24 kHz, mono, 16-bit by default). The AudioQuery goes back
unchanged: AivisSpeech may fail on a query a client has edited.
"""
from urllib.parse import urlencode

from .external_engine import EngineClient
from .speechcpp_tts import CancelToken, SpeechError

# Engines of this API family and the port each listens on by default.
DEFAULT_URLS = {
    'voicevox': 'http://127.0.0.1:50021',
    'sharevox': 'http://127.0.0.1:50025',
    'aivis': 'http://127.0.0.1:10101',
}
# Styles that read text. Singing styles ("sing", "frame_decode", ...) need other APIs.
TALK_STYLES = {'talk', 'streaming_talk'}
QUERY_LIMIT = 4 * 1024 * 1024
WAV_LIMIT = 64 * 1024 * 1024


class VoicevoxTTS(EngineClient):
    def check_health(self, cancel_token=None):
        version = self.get_json('/version', cancel_token or CancelToken(), limit=4096)
        if not isinstance(version, str):
            raise SpeechError(self.not_ready)
        return version

    def list_voices(self, cancel_token=None):
        speakers = self.get_json('/speakers', cancel_token or CancelToken(), limit=QUERY_LIMIT)
        if not isinstance(speakers, list):
            raise SpeechError(self.not_ready)
        voices = []
        for speaker in speakers:
            if not isinstance(speaker, dict) or not isinstance(speaker.get('name'), str):
                continue
            for style in speaker.get('styles') or ():
                if (isinstance(style, dict) and type(style.get('id')) is int and isinstance(style.get('name'), str)
                        and style.get('type', 'talk') in TALK_STYLES):
                    voices.append({'id': str(style['id']), 'speaker': speaker['name'], 'style': style['name']})
        return voices

    def synthesize_piece(self, text, voice_id, token):
        query = self.request('POST', '/audio_query?' + urlencode({'text': text, 'speaker': voice_id}), token,
                             limit=QUERY_LIMIT, error_code='tts_engine_query_failed',
                             timeout=self.synthesis_timeout, expect='application/json')
        return self.request('POST', '/synthesis?' + urlencode({'speaker': voice_id}), token, body=query,
                            limit=WAV_LIMIT, error_code='tts_engine_synthesis_failed',
                            timeout=self.synthesis_timeout, expect='audio/wav')
