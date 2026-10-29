"""Persist local model choices without persisting permission to start a process."""
from pathlib import Path
import stat

PROFILES = ('japanese', 'multilingual', 'asr')
DEFAULT = dict(model='', vad_model='', voice_file='', device='auto')


def normalize_settings(value):
    if not isinstance(value, dict) or set(value)-{'version','profiles'}:
        raise ValueError('speech_server_settings_invalid')
    if type(value.get('version',1)) is not int or value.get('version',1)!=1:
        raise ValueError('speech_server_settings_invalid')
    given=value.get('profiles',{})
    if not isinstance(given,dict) or set(given)-set(PROFILES):
        raise ValueError('speech_server_settings_invalid')
    result=dict(version=1,profiles={})
    for profile in PROFILES:
        row=given.get(profile,{})
        if not isinstance(row,dict) or set(row)-set(DEFAULT):
            raise ValueError('speech_server_settings_invalid')
        row={**DEFAULT,**row}
        if any(not isinstance(v,str) or len(v)>4096 or any(ord(c)<32 for c in v) for v in row.values()):
            raise ValueError('speech_server_settings_invalid')
        if (row['device'] not in ('auto','cpu','gpu') or
                (row['voice_file'] if profile=='asr' else row['vad_model'])):
            raise ValueError('speech_server_settings_invalid')
        result['profiles'][profile]=row
    return result


def _gguf(value):
    try:
        if not value:
            raise ValueError()
        path=Path(value).expanduser().resolve(strict=True)
        if path.suffix.lower()!='.gguf' or not stat.S_ISREG(path.stat().st_mode):
            raise ValueError()
        with path.open('rb') as source:
            if source.read(4)!=b'GGUF':
                raise ValueError()
        return str(path)
    except (OSError, ValueError, RuntimeError):
        raise ValueError('speech_server_model_invalid') from None


def start_options(settings, profile):
    if profile not in PROFILES:
        raise ValueError('speech_server_profile_invalid')
    row=normalize_settings(settings)['profiles'][profile]
    row['model']=_gguf(row['model'])
    if profile=='asr':
        row['vad_model']=_gguf(row['vad_model'])
    elif row['voice_file']:
        row['voice_file']=_gguf(row['voice_file'])
    return row
