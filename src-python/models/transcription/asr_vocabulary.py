"""The term vocabulary of realtime ASR: user terms merged with the VRChat list.

speech.cpp 0.10.0 takes it per Realtime session in session.audio.input.
transcription, in the form the model has an option for:

- Haas: "keywords", an array of strings, one keyword each, as
  "written form=reading,reading" on one line (docs/server.md, Realtime).
  keywords_alpha and keywords_guard keep their defaults (2, true): on
  synthetic VRChat sentences alpha 3 cut one utterance short, 2 did not.
- Qwen3-ASR: "prompt", text the model hears as background before the audio.

A model refuses an option it does not take, so each goes only to a model
that lists it. The server sets no size limit; these limits are VRCT's own,
since each keyword adds a small chance of a word that was not said and a
prompt adds decoding work to every utterance.
"""
import re

from .vrchat_terms import VRCHAT_TERMS

MAX_USER_TERMS = 100
MAX_TERMS = 150
MAX_WRITTEN = 48
MAX_READING = 32
MAX_READINGS = 8
MAX_PROMPT = 300
PROMPT_PREFIX = 'VRChat用語: '
DEFAULT = dict(builtin=True, terms=[])


def parse_term(value):
    """A canonical "written=reading,reading" keyword, or ValueError."""
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('realtime_vocabulary_term_invalid')
    written, _, readings = value.strip().partition('=')
    written = re.sub(r'\s+', ' ', written.strip())
    readings = [r.strip() for r in readings.split(',')] if readings.strip() else []
    if (not 0 < len(written) <= MAX_WRITTEN or ',' in written or len(readings) > MAX_READINGS
            or any(not 0 < len(r) <= MAX_READING or '=' in r for r in readings)):
        raise ValueError('realtime_vocabulary_term_invalid')
    return written + ('=' + ','.join(readings) if readings else '')


def written_form(term):
    return term.partition('=')[0]


def normalize_vocabulary(value):
    if value is None:
        value = DEFAULT
    if not isinstance(value, dict) or set(value) - {'builtin', 'terms'}:
        raise ValueError('realtime_vocabulary_invalid')
    builtin, terms = value.get('builtin', True), value.get('terms', [])
    if type(builtin) is not bool or not isinstance(terms, list) or len(terms) > MAX_USER_TERMS:
        raise ValueError('realtime_vocabulary_invalid')
    result, seen = [], set()
    for term in terms:
        term = parse_term(term)
        key = written_form(term).casefold()
        if key not in seen:
            seen.add(key)
            result.append(term)
    return dict(builtin=builtin, terms=result)


def merged_terms(vocabulary):
    """User terms first, so a user's readings win and survive the cap."""
    vocabulary = normalize_vocabulary(vocabulary)
    result, seen = [], set()
    for term in (*vocabulary['terms'], *(VRCHAT_TERMS if vocabulary['builtin'] else ())):
        key = written_form(term).casefold()
        if key not in seen and len(result) < MAX_TERMS:
            seen.add(key)
            result.append(term)
    return tuple(result)


def prompt_text(terms):
    """A short Qwen3-ASR prompt of whole written forms, at most MAX_PROMPT characters."""
    text = ''
    for term in terms:
        candidate = (text + '、' if text else PROMPT_PREFIX) + written_form(term)
        if len(candidate) > MAX_PROMPT:
            break
        text = candidate
    return text


def request_options(model_options, terms):
    """The transcription members for a model whose option names are model_options."""
    if not terms:
        return {}
    if 'keywords' in model_options:
        return {'keywords': list(terms)}
    if 'prompt' in model_options:
        return {'prompt': prompt_text(terms)}
    return {}
