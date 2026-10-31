"""The VRChat term vocabulary: limits, merge/disable, and that it reaches the request."""
import importlib

import pytest

from models.audio_routing.source_bridge import Endpoint
from models.transcription.speechcpp_asr import RecognitionModel
from test_realtime_delivery import eventually
from test_realtime_session import Dependencies

# Option names as speech.cpp 0.10.0's /v1/models lists them.
HAAS_OPTIONS = ('language', 'timestamps', 'decode_on_cpu', 'keywords', 'keywords_alpha', 'keywords_guard')
QWEN_OPTIONS = ('language', 'prompt', 'draft')


def vocab():
    return importlib.import_module('models.transcription.asr_vocabulary')


def test_builtin_terms_are_canonical_small_and_avoid_everyday_readings():
    v = vocab()
    from models.transcription.vrchat_terms import VRCHAT_TERMS
    assert all(v.parse_term(term) == term for term in VRCHAT_TERMS)
    assert len(VRCHAT_TERMS) <= 60 and len(set(map(v.written_form, VRCHAT_TERMS))) == len(VRCHAT_TERMS)
    readings = {r for term in VRCHAT_TERMS for r in term.partition('=')[2].split(',') if r}
    # Haas rewrites a reading into the written form: うどん and ブース stay as said.
    assert not readings & {'うどん', 'ウドン', 'ブース'}
    assert {'Udon', 'BOOTH', 'VRChat=ブイアールチャット,ブイチャ', 'お砂糖=おさとう'} <= set(VRCHAT_TERMS)


@pytest.mark.parametrize('term', [
    '', '   ', 'a\nb', 'tab\there', '=よみ', 'a,b=よみ', 'x' * 49,
    'VRChat=' + ','.join(['よみ'] * 9), 'VRChat=よみ,,よみ', 'VRChat=' + 'よ' * 33, 'VRChat=a=b', 3,
])
def test_invalid_terms_are_refused(term):
    with pytest.raises(ValueError, match='realtime_vocabulary_term_invalid'):
        vocab().parse_term(term)


def test_terms_are_canonicalized():
    assert vocab().parse_term('  New   User = ニューユーザー , にゅーゆーざー ') == 'New User=ニューユーザー,にゅーゆーざー'
    assert vocab().parse_term('集会') == '集会'


def test_user_terms_come_first_override_builtin_and_builtin_can_be_disabled():
    v = vocab()
    from models.transcription.vrchat_terms import VRCHAT_TERMS
    merged = v.merged_terms({'builtin': True, 'terms': ['vrchat=ぶいちゃっと', '自作ワールド']})
    assert merged[:2] == ('vrchat=ぶいちゃっと', '自作ワールド')
    assert 'VRChat=ブイアールチャット,ブイチャ' not in merged  # Same written form, user's wins.
    assert len(merged) == 2 + len(VRCHAT_TERMS) - 1
    assert v.merged_terms({'builtin': False, 'terms': ['自作ワールド']}) == ('自作ワールド',)
    assert v.merged_terms({'builtin': False, 'terms': []}) == ()
    assert v.merged_terms(None) == VRCHAT_TERMS


def test_user_dictionary_limits_and_duplicates():
    v = vocab()
    assert v.normalize_vocabulary({'terms': ['Udon', 'udon', 'UDON=うどん']}) == {'builtin': True, 'terms': ['Udon']}
    with pytest.raises(ValueError):
        v.normalize_vocabulary({'terms': [f'語{i}' for i in range(v.MAX_USER_TERMS + 1)]})
    with pytest.raises(ValueError):
        v.normalize_vocabulary({'builtin': 'yes'})
    with pytest.raises(ValueError):
        v.normalize_vocabulary({'terms': 'VRChat'})
    many = v.merged_terms({'terms': [f'語{i}' for i in range(v.MAX_USER_TERMS)]})
    assert len(many) == v.MAX_TERMS and many[0] == '語0'  # The cap drops built-in terms first.


def test_prompt_holds_whole_written_forms_within_its_limit():
    v = vocab()
    prompt = v.prompt_text(v.merged_terms(None))
    assert prompt.startswith('VRChat用語: VRChat、VRC、インスタンス') and len(prompt) <= v.MAX_PROMPT
    assert '=' not in prompt and 'ブイアールチャット' not in prompt
    assert all(part in {v.written_form(t) for t in v.merged_terms(None)}
               for part in prompt.removeprefix(v.PROMPT_PREFIX).split('、'))
    assert len(v.prompt_text(('あ' * 48,) * 20)) <= v.MAX_PROMPT


def test_each_model_gets_only_the_option_it_takes():
    v = vocab()
    terms = ('VRChat=ブイアールチャット', '集会')
    assert v.request_options(HAAS_OPTIONS, terms) == {'keywords': ['VRChat=ブイアールチャット', '集会']}
    assert v.request_options(QWEN_OPTIONS, terms) == {'prompt': 'VRChat用語: VRChat、集会'}
    assert v.request_options(('language',), terms) == {}
    assert v.request_options(HAAS_OPTIONS, ()) == {}


def test_settings_carry_a_validated_vocabulary_into_session_options():
    s = importlib.import_module('models.transcription.realtime_settings')
    endpoint = dict(cookie='1', serial='2', name='selected', media_class='Audio/Source')
    value = s.normalize_settings({'model': 'asr', 'mic': {'endpoint': endpoint},
                                  'vocabulary': {'builtin': False, 'terms': ['自作ワールド=じさくわーるど']}})
    options, _ = s.session_options(value, 'mic')
    assert options.vocabulary == ('自作ワールド=じさくわーるど',)
    with pytest.raises(ValueError):
        s.normalize_settings({'vocabulary': {'terms': ['a\nb']}})
    with pytest.raises(ValueError):
        s.SessionOptions('http://127.0.0.1:8080', 'asr', 'ja', ('bad\nterm',))


def realtime(options):
    m = importlib.import_module('models.transcription.speechcpp_realtime')
    return m.SpeechCppRealtime('http://127.0.0.1:8080', 'Haas-ja-v1.0', 'ja', 'mic', options=options)


def test_realtime_session_update_carries_the_vocabulary_and_checks_the_echo():
    client = realtime({'keywords': ['VRChat=ブイアールチャット', '集会']})
    sent = client._settings()['audio']['input']['transcription']
    assert sent == {'model': 'Haas-ja-v1.0', 'language': 'ja', 'keywords': ['VRChat=ブイアールチャット', '集会']}
    echo = {'type': 'session.updated', 'session': {'type': 'transcription', 'audio': {'input': {
        'format': {'type': 'audio/pcm', 'rate': 24000}, 'noise_reduction': None, 'diarization': None,
        'turn_detection': {'type': 'server_vad'}, 'transcription': dict(sent)}}}}
    client._check_config(echo)
    echo['session']['audio']['input']['transcription']['keywords'] = []
    with pytest.raises(Exception, match='configuration_rejected'):
        client._check_config(echo)
    assert 'keywords' not in realtime({})._settings()['audio']['input']['transcription']
    with pytest.raises(ValueError):
        realtime({'keywords_alpha': 5})
    with pytest.raises(ValueError):
        realtime({'keywords': 'VRChat'})


@pytest.mark.parametrize('model,expected', [
    (RecognitionModel('asr', ('ja',), True, False, HAAS_OPTIONS), {'keywords': ['集会']}),
    (RecognitionModel('asr', ('ja', 'en'), True, True, QWEN_OPTIONS), {'prompt': 'VRChat用語: 集会'}),
    (RecognitionModel('asr', ('ja',), True), {}),
])
def test_session_passes_the_option_its_model_takes_to_the_client(monkeypatch, model, expected):
    m = importlib.import_module('models.transcription.realtime_session')
    settings = importlib.import_module('models.transcription.realtime_settings')
    deps = Dependencies()
    deps.models = (model,)
    seen = []

    def client(url, name, language, source, options=None):
        seen.append(options)
        return deps.client(url, name, language, source)

    monkeypatch.setattr(m, 'SpeechCppASR', deps.rest)
    session = m.RealtimeSession('mic', settings.SessionOptions('http://127.0.0.1:8080', 'asr', 'ja', ('集会',)),
                                Endpoint(1, 2, 'selected', 'Audio/Source'),
                                capture_factory=deps.capture, client_factory=client)
    try:
        session.start()
        eventually(lambda: seen)
        assert seen == [expected]
    finally:
        session.close()


def test_recognizers_list_their_option_names(monkeypatch):
    m = importlib.import_module('models.transcription.speechcpp_asr')
    client = m.SpeechCppASR('http://127.0.0.1:8080')
    payload = {'data': [{'id': 'Haas-ja-v1.0', 'speech': {'task': 'recognition', 'languages': ['ja'],
                         'options': [{'name': n} for n in HAAS_OPTIONS]}}]}
    monkeypatch.setattr(client, '_request', lambda *a, **k: (payload, None))
    assert client.recognizers()[0].options == HAAS_OPTIONS
