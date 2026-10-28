"""Persist intent only, without requiring or starting an optional engine."""
import pytest
from models.voice_conversion.settings import DirectSettings, normalize_settings


def test_old_config_defaults_to_passthrough_and_retains_paths_as_data():
    assert DirectSettings.from_dict({}).to_dict() == dict(mode='passthrough', runtime='', reference='', engine='seed-vc', rvc_runtime='',
        rvc_model='', rvc_index='', rvc_pitch=0, rvc_index_rate=0.0)
    data = dict(mode='converted', runtime='~/allowed/runtime', reference='~/allowed/reference.wav')
    settings = DirectSettings.from_dict(data)
    assert normalize_settings(data) == settings.to_dict()
    data['runtime'] = '/changed'
    assert settings.runtime == '~/allowed/runtime'


@pytest.mark.parametrize('bad', [None, {'mode': 'rvc'}, {'mode': False}, {'runtime': 4},
    {'runtime': '/bad\0path'}, {'reference': 'x'*4097}, {'download': True}])
def test_invalid_choice_is_rejected(bad):
    with pytest.raises(ValueError):
        DirectSettings.from_dict(bad)
    assert normalize_settings(bad) is None
