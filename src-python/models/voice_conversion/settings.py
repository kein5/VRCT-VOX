"""Saved direct-input choices; construction never acquires or loads a model."""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class DirectSettings:
    mode: str = 'passthrough'
    runtime: str = ''
    reference: str = ''
    engine: str = 'seed-vc'
    rvc_runtime: str = ''
    rvc_model: str = ''
    rvc_index: str = ''
    rvc_pitch: int = 0
    rvc_index_rate: float = 0.0

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ValueError('vc_settings_invalid')
        settings = cls(**value)
        if (settings.mode not in ('passthrough', 'converted')
                or settings.engine not in ('seed-vc', 'rvc')
                or any(not isinstance(v, str) or len(v) > 4096 or any(ord(c) < 32 for c in v)
                       for v in (settings.runtime, settings.reference, settings.rvc_runtime,
                                 settings.rvc_model, settings.rvc_index))
                or type(settings.rvc_pitch) is not int or not -24 <= settings.rvc_pitch <= 24
                or type(settings.rvc_index_rate) not in (int, float)
                or not math.isfinite(settings.rvc_index_rate) or not 0 <= settings.rvc_index_rate <= 1):
            raise ValueError('vc_settings_invalid')
        return settings

    def to_dict(self):
        return asdict(self)


def normalize_settings(value, _instance=None):
    try:
        return DirectSettings.from_dict(value).to_dict()
    except (ValueError, TypeError):
        return None


def start_options(mode, options):
    if mode == 'passthrough' and (options is None or options == {}):
        return {}
    if mode != 'converted' or not isinstance(options, dict):
        raise ValueError('vc_options_invalid')
    if options.get('engine') == 'rvc':
        if set(options) != {'engine', 'runtime', 'model', 'index', 'pitch', 'index_rate'}:
            raise ValueError('vc_options_invalid')
        settings = DirectSettings.from_dict(dict(mode=mode, engine='rvc', **{
            'rvc_' + k: v for k, v in options.items() if k != 'engine'}))
        if (not settings.rvc_runtime.strip() or not settings.rvc_model.lower().endswith('.pth')
                or (settings.rvc_index and not settings.rvc_index.lower().endswith('.index'))
                or (settings.rvc_index_rate and not settings.rvc_index)):
            raise ValueError('vc_options_invalid')
        return dict(options)
    if set(options) != {'runtime', 'reference'}:
        raise ValueError('vc_options_invalid')
    settings = DirectSettings.from_dict(dict(options, mode=mode))
    if not settings.runtime.strip() or not settings.reference.strip():
        raise ValueError('vc_options_invalid')
    return dict(runtime=settings.runtime, reference=settings.reference)
