"""The client for each speech engine a user can install and run (ADR-008)."""
from .coeiroink_tts import CoeiroinkTTS
from .voicevox_tts import VoicevoxTTS

CLIENTS = {'voicevox': VoicevoxTTS, 'sharevox': VoicevoxTTS, 'aivis': VoicevoxTTS, 'coeiroink': CoeiroinkTTS}


def engine_client(engine, url, **options):
    try:
        client = CLIENTS[engine]
    except KeyError:
        raise ValueError('Unknown speech engine') from None
    return client(url, **options)
