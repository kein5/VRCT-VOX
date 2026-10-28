"""Direct output ownership, independently of model and audio driver availability."""
import pytest

from models.audio_routing.source_bridge import Endpoint
from models.voice_conversion.direct_voice import DirectVoice


SOURCE = Endpoint(1, 2, 'explicit.mic', 'Audio/Source')


class Backend:
    def __init__(self):
        self.started = self.stops = 0
        self.busy = False
        self.state = dict(requested=False, active=False, pending=False,
                          error=None, conversion_verified=False, stopping=False)

    def start(self, *, source):
        assert source == SOURCE
        self.started += 1
        self.state.update(requested=True, active=True)

    def stop(self):
        self.stops += 1
        self.state.update(requested=False, active=False, stopping=self.busy)

    def close(self, timeout=3):
        self.stop()
        return not self.busy

    def health(self):
        return dict(self.state)


@pytest.fixture
def rig():
    raw, converted, options = [], [], []

    def original():
        raw.append(Backend())
        return raw[-1]

    def vc(value):
        options.append(value)
        converted.append(Backend())
        return converted[-1]

    owner = DirectVoice(passthrough_factory=original, converted_factory=vc)
    yield owner, raw, converted, options
    owner.close()


def start(owner, **kw):
    owner.start(source=SOURCE, expected_generation=owner.health()['generation'], **kw)


def test_initial_off_and_original_start_payload_compatibility(rig):
    owner, raw, vc, _ = rig
    assert owner.health()['mode'] == 'off'
    assert owner.health()['source'] is None
    assert not raw and not vc
    start(owner)
    assert len(raw) == 1 and not vc
    assert owner.health()['active'] and owner.health()['mode'] == 'passthrough'
    assert not owner.health()['conversion_verified']
    start(owner)  # Identical repeated request does not create another producer.
    assert len(raw) == 1 and raw[0].started == 1


def test_conversion_requires_stop_and_finished_cleanup(rig):
    owner, raw, vc, _ = rig
    start(owner)
    with pytest.raises(RuntimeError, match='stop_required'):
        start(owner, mode='converted')
    assert not vc
    raw[0].busy = True
    owner.stop()
    assert owner.health()['pending'] and not owner.health()['active']
    with pytest.raises(RuntimeError, match='stopping'):
        start(owner, mode='converted')
    assert not vc
    raw[0].busy = False
    raw[0].state['stopping'] = False
    start(owner, mode='converted')
    assert len(vc) == 1 and not raw[0].state['requested']
    assert owner.health()['mode'] == 'converted'


def test_stop_rejects_stale_start_and_forgets_conversion_proof(rig):
    owner, raw, vc, _ = rig
    start(owner, mode='converted')
    vc[0].state['conversion_verified'] = True
    assert owner.health()['conversion_verified']
    generation = owner.health()['generation']
    owner.stop()
    assert not owner.health()['conversion_verified']
    with pytest.raises(RuntimeError, match='source_bridge_stale_start'):
        owner.start(source=SOURCE, mode='converted', expected_generation=generation)
    assert not raw and len(vc) == 1


def test_failed_conversion_never_creates_original_or_resurrects(rig):
    owner, raw, vc, _ = rig
    start(owner, mode='converted')
    generation = owner.health()['generation']
    vc[0].state.update(requested=False, active=False, error='vc_worker_eof')
    health = owner.health()
    assert health['error'] == 'vc_worker_eof'
    assert health['mode'] == 'off' and health['generation'] > generation
    assert not raw
    owner.stop()
    assert not raw and len(vc) == 1


def test_backend_start_failure_is_closed_and_diagnostic_is_sanitized():
    backend = Backend()
    def fail(**kw):
        raise RuntimeError('/private/reference.wav failed')
    backend.start = fail
    owner = DirectVoice(converted_factory=lambda options: backend)
    with pytest.raises(RuntimeError, match='vc_start_failed'):
        start(owner, mode='converted')
    assert backend.stops and not owner.health()['requested']
    assert owner.health()['error'] == 'vc_start_failed'


@pytest.mark.parametrize('mode,source,options', [
    ('typo', SOURCE, None), ('off', SOURCE, None),
    ('passthrough', None, None), ('converted', SOURCE, []),
    ('passthrough', SOURCE, {'unexpected': True}),
])
def test_invalid_requests_never_create_a_producer(rig, mode, source, options):
    owner, raw, vc, _ = rig
    with pytest.raises(ValueError):
        owner.start(source=source, mode=mode, options=options, expected_generation=0)
    assert not raw and not vc and owner.health()['generation'] == 0


def test_options_and_health_do_not_expose_mutable_owner_state(rig):
    owner, _, _, options = rig
    value = {'runtime_root': '/tmp/consented', 'nested': {'value': 1}}
    start(owner, mode='converted', options=value)
    value['nested']['value'] = 2
    health = owner.health()
    health['source']['name'] = 'replacement'
    assert options[0]['nested']['value'] == 1
    assert owner.health()['source']['name'] == SOURCE.name


def test_missing_engine_and_close_do_not_start_capture():
    owner = DirectVoice()
    with pytest.raises(RuntimeError, match='vc_engine_unavailable'):
        start(owner, mode='converted')
    assert not owner.health()['requested']
    assert owner.close()
    with pytest.raises(RuntimeError, match='source_bridge_closed'):
        start(owner)


def test_old_backend_health_is_ignored_after_new_session(rig):
    owner, raw, vc, _ = rig
    start(owner, mode='converted')
    owner.stop()
    start(owner)
    vc[0].state.update(requested=False, error='vc_worker_failed', conversion_verified=True)
    assert owner.health()['active'] and owner.health()['error'] is None
    assert not owner.health()['conversion_verified'] and len(raw) == 1
