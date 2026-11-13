"""Linux Device page Mic lists PipeWire inputs and supplies the default RVC input.

PyAudioWPatch is Windows-only, so before this the Linux Mic list was only
NoHost/NoDevice and RVC could not be pointed at a microphone from there.
"""
import pytest

from test_controller_integration import controller_module  # noqa: F401
from test_direct_voice_controller import app  # noqa: F401
from test_source_bridge import module, node
from test_source_selection import ID


def pipewire_graph(default='vrct.managed.source', configured='alsa_input.usb-mic'):
    """Shape of a real pw-dump: the managed virtual mic can be PipeWire's default."""
    return [
        {'type': 'PipeWire:Interface:Core', 'info': {'cookie': 42}},
        node(40, 'vrct.managed.source', 'Audio/Source', 40, **{
            'node.description': 'VRCT Managed Virtual Microphone', 'vrct.managed.route': 'v1'}),
        node(93, 'bluez_input.E4:DC', 'Audio/Source', 219, **{'node.description': 'Headset'}),
        node(114, 'alsa_input.usb-mic', 'Audio/Source', 41139, **{'node.description': 'USB Mic'}),
        node(96, 'bluez_capture_internal.E4:DC', 'Stream/Input/Audio/Internal', 220),
        {'type': 'PipeWire:Interface:Metadata', 'props': {'metadata.name': 'default'}, 'metadata': [
            {'subject': 0, 'key': 'default.configured.audio.source', 'type': 'Spa:String:JSON',
             'value': {'name': configured}},
            {'subject': 0, 'key': 'default.audio.source', 'type': 'Spa:String:JSON', 'value': {'name': default}}]},
    ]


@pytest.fixture
def linux_graph(monkeypatch):
    m, data = module(), pipewire_graph()
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(m, '_read_graph', lambda: data)
    return m, data


def test_microphone_devices_are_rvc_inputs_without_the_virtual_mic(linux_graph):
    m, _ = linux_graph
    devices, default = m.microphone_devices()
    assert devices == [{'index': 0, 'name': 'Headset', 'node_name': 'bluez_input.E4:DC'},
                       {'index': 1, 'name': 'USB Mic', 'node_name': 'alsa_input.usb-mic'}]
    assert [item['id']['name'] for item in m.enumerate_sources()] == [d['node_name'] for d in devices]
    # PipeWire's current default is our own virtual mic; use the configured one.
    assert default == devices[1]


@pytest.mark.parametrize('default, configured, expected', [
    ('bluez_input.E4:DC', 'alsa_input.usb-mic', 'Headset'),
    ('vrct.managed.source', 'missing', 'Headset'),
])
def test_default_prefers_current_then_configured_then_first(monkeypatch, default, configured, expected):
    m, data = module(), pipewire_graph(default, configured)
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(m, '_read_graph', lambda: data)
    assert m.microphone_devices()[1]['name'] == expected


def test_shared_descriptions_get_unique_names(linux_graph):
    m, data = linux_graph
    data[3]['info']['props']['node.description'] = 'Headset'
    names = [d['name'] for d in m.microphone_devices()[0]]
    assert names == ['Headset (bluez_input.E4:DC)', 'Headset (alsa_input.usb-mic)']
    assert m.microphone_names(m.enumerate_sources()) == names


def test_microphone_devices_are_linux_only(monkeypatch):
    m = module()
    monkeypatch.setattr(m.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='linux_only'):
        m.microphone_devices()


@pytest.fixture
def manager(monkeypatch):
    import device_manager as dm_module
    dm = dm_module.device_manager
    monkeypatch.setattr(dm_module, 'PyAudio', None)
    monkeypatch.setattr(dm, '_device_snapshot', dm._device_snapshot)
    return dm_module, dm


def test_linux_device_manager_lists_pipewire_microphones(manager, linux_graph, monkeypatch):
    dm_module, dm = manager
    monkeypatch.setattr(dm_module.sys, 'platform', 'linux')
    dm.update()
    assert list(dm.getMicDevices()) == ['PipeWire']
    assert [d['name'] for d in dm.getMicDevices()['PipeWire']] == ['Headset', 'USB Mic']
    assert dm.getDefaultMicDevice()['host']['name'] == 'PipeWire'
    assert dm.getDefaultMicDevice()['device']['name'] == 'USB Mic'


def test_linux_without_graph_and_non_linux_keep_no_device(manager, monkeypatch):
    dm_module, dm = manager
    m = module()
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(dm_module.sys, 'platform', 'linux')

    def unavailable():
        raise RuntimeError('source_bridge_graph_unavailable')
    monkeypatch.setattr(m, '_read_graph', unavailable)
    dm.update()
    assert dm.getMicDevices() == {'NoHost': [{'index': -1, 'name': 'NoDevice'}]}
    assert dm.getDefaultMicDevice()['device']['name'] == 'NoDevice'
    # Without PyAudio off Linux (and with it on Windows) nothing reads PipeWire.
    monkeypatch.setattr(m, '_read_graph', lambda: pytest.fail('PipeWire read off Linux'))
    monkeypatch.setattr(dm_module.sys, 'platform', 'darwin')
    dm.update()
    assert dm.getMicDevices() == {'NoHost': [{'index': -1, 'name': 'NoDevice'}]}


def test_device_page_mic_is_the_preferred_rvc_input(app, monkeypatch):  # noqa: F811
    c, _, _, controller = app
    monkeypatch.setattr(controller.config, 'SELECTED_MIC_HOST', 'PipeWire', raising=False)
    monkeypatch.setattr(controller.config, 'SELECTED_MIC_DEVICE', 'external.source', raising=False)
    assert c.getDirectVoiceSources()['result'] == {
        'sources': [{'id': ID, 'label': 'external.source'}], 'error': None, 'preferred': ID}
    controller.config.SELECTED_MIC_DEVICE = 'unplugged mic'
    assert c.getDirectVoiceSources()['result']['preferred'] is None
    # A Windows host name never maps onto a PipeWire input.
    controller.config.SELECTED_MIC_HOST = 'Windows WASAPI'
    controller.config.SELECTED_MIC_DEVICE = 'external.source'
    assert c.getDirectVoiceSources()['result']['preferred'] is None
