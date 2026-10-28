"""Saved direct-input choices; construction never acquires or loads a model."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DirectSettings:
    mode: str = 'passthrough'
    runtime: str = ''
    reference: str = ''

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ValueError('vc_settings_invalid')
        settings = cls(**value)
        if (settings.mode not in ('passthrough', 'converted')
                or any(not isinstance(v, str) or len(v) > 4096 or any(ord(c) < 32 for c in v)
                       for v in (settings.runtime, settings.reference))):
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
    if mode != 'converted' or not isinstance(options, dict) or set(options) != {'runtime', 'reference'}:
        raise ValueError('vc_options_invalid')
    settings = DirectSettings.from_dict(dict(options, mode=mode))
    if not settings.runtime.strip() or not settings.reference.strip():
        raise ValueError('vc_options_invalid')
    return dict(runtime=settings.runtime, reference=settings.reference)
