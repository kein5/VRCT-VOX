from dataclasses import dataclass
from contextlib import nullcontext
import sys
from uuid import uuid4
from audio_device_identity import capture_key, device_id
from typing import Callable, Dict, List, Optional, Any
from time import monotonic, sleep
from threading import Thread, Lock, Event
from pyaudio_lock import pyaudio_op_lock

# Optional, Windows-specific dependencies. Guard imports so module can be imported on non-Windows systems.
try:
    import comtypes
except Exception:  # pragma: no cover - optional runtime
    comtypes = None  # type: ignore

try:
    from pyaudiowpatch import PyAudio, paWASAPI
except Exception:  # pragma: no cover - optional runtime
    PyAudio = None  # type: ignore
    paWASAPI = None  # type: ignore

try:
    from pycaw.callbacks import MMNotificationClient
    from pycaw.utils import AudioUtilities
except Exception:  # pragma: no cover - optional runtime
    MMNotificationClient = object  # type: ignore
    AudioUtilities = None  # type: ignore

from utils import errorLogging, printLog
from active_endpoint_tracker import ActiveEndpointTracker

# pauseMicEndpointTracker/pauseSpeakerEndpointTracker のバリア待ちの上限。
# tracker の COM 呼び出し (Activate/GetPeakValue 等) には現状タイムアウトが
# 無く、理論上ハングし得る (active_endpoint_tracker.py の ActiveEndpointTracker
# クラスdocstring参照)。ハングした場合、このバリアを無期限待ちにしていると
# 呼び出し元 (mainloop のハンドラワーカースレッド、本数が限られている) が
# 永久にブロックされ、他の全リクエスト処理までアプリごと無応答になる。
# タイムアウトしても根本のロック保持スレッドが解放されるわけではない
# (COM 呼び出し自体は止められない) ため完全な解決ではないが、少なくとも
# ハンドラワーカーを解放してアプリの他機能を無応答にしないための緩和策。
_PAUSE_BARRIER_TIMEOUT_SEC = 5.0


@dataclass(frozen=True)
class _DeviceSnapshot:
    """mic/speakerのデバイス一覧4フィールドをまとめて原子的にスワップする
    ための不変スナップショット(バックエンドレビュー フェーズ4項目32)。

    以前は DeviceManager.update() 内でこの4つを個別の self.属性へ順に
    代入していた。列挙処理自体は pyaudio_op_lock 配下で保護されていたが、
    その後のこの4つの代入は無保護だったため、別スレッド(mainloopワーカー
    が getMicDevices()/getDefaultMicDevice() 等を連続で呼ぶ経路)から見ると
    「新しい mic_devices + 古い default_mic_device」のような、新旧が
    混在した組み合わせを観測しうった。1つのオブジェクトへの単一代入に
    一本化することで、読み手は常にどちらか一方の完全なスナップショットの
    みを見るようになる。
    """
    mic_devices: Dict[str, List[Dict[str, Any]]]
    default_mic_device: Dict[str, Any]
    speaker_devices: List[Dict[str, Any]]
    default_speaker_device: Dict[str, Any]


class Client(MMNotificationClient):
    """Callback client used by pycaw to detect device changes.

    COM のコールバックスレッドから呼ばれる。monitoring スレッドは
    `notify_event` を wait しており、いずれかのイベントで set されると
    デバイス一覧を再構築する。stop イベント (外部から `stop_event.set()`)
    でも wait は解ける (`Event.wait` は set 済みならすぐ True を返す)。
    """

    def __init__(self, notify_event: Event, invalidate=None) -> None:
        # If MMNotificationClient is the placeholder object (non-windows), avoid calling super
        try:
            super().__init__()
        except Exception:
            pass
        self._notify_event = notify_event
        self._invalidate = invalidate

    def on_default_device_changed(self, *args: Any, **kwargs: Any) -> None:
        self._notify_event.set()

    def on_device_added(self, *args: Any, **kwargs: Any) -> None:
        if self._invalidate is not None:
            self._invalidate()
        self._notify_event.set()

    def on_device_removed(self, *args: Any, **kwargs: Any) -> None:
        if self._invalidate is not None:
            self._invalidate()
        self._notify_event.set()

    def on_device_state_changed(self, *args: Any, **kwargs: Any) -> None:
        if self._invalidate is not None:
            self._invalidate()
        self._notify_event.set()

    # on_property_value_changed は登録しない: default endpoint 変更は
    # on_default_device_changed で拾えており、property イベントは
    # ボリューム変更などでも発火するため、拾うとポーリングが過剰になる。

class DeviceManager:
    _instance = None

    # Keep stop checks and polling without COM at the existing two-second pace.
    _MONITOR_WAIT_TIMEOUT_SEC: float = 2.0
    # COM notifications refresh immediately. One idle reconciliation per minute
    # bounds missed-notification recovery while avoiding 30 full enumerations
    # per minute contending with capture opening for the shared PyAudio lock.
    _COM_RECONCILE_INTERVAL_SEC: float = 60.0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DeviceManager, cls).__new__(cls)
            # 監視スレッドは import では開始しない (startMonitoring を
            # 明示的に呼ぶ必要がある)。ただし init() はここで呼ぶ:
            # シングルトンを観測する側が初期化前の内部構造を見てしまい、
            # import 順によって NoDevice になる問題があったため。
            # この init() は PyAudio が使えればデバイス列挙まで行う。
            cls._instance._initialized = False
            try:
                # Call init() to populate internal containers. This will NOT start
                # the monitoring thread (startMonitoring must be called explicitly).
                cls._instance.init()
            except Exception:
                # Avoid import-time crashes; log and continue.
                try:
                    errorLogging()
                except Exception:
                    pass
        return cls._instance

    def init(self) -> None:
        """Initialize internal state. This is intentionally separate from object
        creation so importing the module won't start threads or access OS
        audio APIs. Call `device_manager.init()` and then explicitly enable
        monitoring with `startMonitoring()` or
        `setDeviceListMonitoringActive()` when ready.
        """
        if getattr(self, "_initialized", False):
            return

        self._device_snapshot = self._identifiedSnapshot(
            mic_devices={"NoHost": [{"index": -1, "name": "NoDevice"}]},
            default_mic_device={"host": {"index": -1, "name": "NoHost"}, "device": {"index": -1, "name": "NoDevice"}},
            speaker_devices=[{"index": -1, "name": "NoDevice"}],
            default_speaker_device={"device": {"index": -1, "name": "NoDevice"}},
            # NoDevice rows need no endpoint IDs; asking Windows costs 0.5 s or more.
            endpoint_ids={},
        )

        # Initialize previous state trackers
        self.prev_mic_host: List[str] = [host for host in self.mic_devices]
        self.prev_mic_devices: Dict[str, List[Dict[str, Any]]] = self.mic_devices
        self.prev_default_mic_device: Dict[str, Any] = self.default_mic_device
        self.prev_speaker_devices: List[Dict[str, Any]] = self.speaker_devices
        self.prev_default_speaker_device: Dict[str, Any] = self.default_speaker_device

        # Update flags
        self.update_flag_default_mic_device: bool = False
        self.update_flag_default_speaker_device: bool = False
        self.update_flag_host_list: bool = False
        self.update_flag_mic_device_list: bool = False
        self.update_flag_speaker_device_list: bool = False

        # Callbacks
        self.callback_default_mic_device: Optional[Callable[..., None]] = None
        self.callback_default_speaker_device: Optional[Callable[..., None]] = None
        self.callback_host_list: Optional[Callable[..., None]] = None
        self.callback_mic_device_list: Optional[Callable[..., None]] = None
        self.callback_speaker_device_list: Optional[Callable[..., None]] = None
        self.callback_process_before_update_mic_devices: Optional[Callable[..., None]] = None
        self.callback_process_after_update_mic_devices: Optional[Callable[..., None]] = None
        self.callback_process_before_update_speaker_devices: Optional[Callable[..., None]] = None
        self.callback_process_after_update_speaker_devices: Optional[Callable[..., None]] = None
        # ActiveEndpointTracker (render) がエンドポイント切替を検知したとき、
        # Session の Recorder 差し替えをトリガするための callback (Auto Speaker
        # 経路専用)。既存の default_speaker_device callback は config 更新 +
        # UI 通知のみで、Recorder 側の再開はしない設計のため別チャネルにする。
        # マイク側は peak 追従を行わないため対応する callback は無い。
        self.callback_endpoint_reconfigured_speaker: Optional[Callable[..., None]] = None

        # Monitoring control
        # `_stop_event` を set すると monitoring スレッドは wait を即抜けて終了する。
        # 従来の `monitoring_flag` (bool) は `sleep` 越しに参照するとタイムラグが
        # 生じ、stopMonitoring 側で最大 5s の join 待ちが発生していた。Event に
        # 置き換えたことで stop は即応する。
        self._stop_event: Event = Event()
        self._stop_event.set()  # 初期状態は「停止済み」
        # notify_event は startMonitoring の中で作り直されるが、
        # stopMonitoring が startMonitoring より先に呼ばれても落ちないよう
        # ここでダミーを 1 個用意しておく。
        self._notify_event: Event = Event()
        self.th_monitoring: Optional[Thread] = None
        self._monitor_stop_logged = False

        # setMicAutoActive/setSpeakerAutoActive/monitoring スレッドと
        # tracker の起動・停止を直列化するロック。pyaudio_op_lock とは別物
        # (WASAPI/PortAudio 操作用) で、こちらは「フラグの読み書き」と
        # 「monitoring スレッド・tracker の起動/停止判断」を保護する。
        # このロックを保持したまま pyaudio_op_lock を新規に取得すること
        # はない (tracker.stop()/monitoring スレッドの join は、それらが
        # 内部で pyaudio_op_lock を保持中でも待つだけで、こちら側から
        # 追加で pyaudio_op_lock を取りに行かないため、両ロック間に
        # 循環待ちは生じない)。
        self._lifecycle_lock: Lock = Lock()

        # デバイス一覧の監視は Auto Select 状態とは独立して管理する。
        # Auto Select が両方 OFF でも、抜き差し後の一覧更新は継続する必要が
        # あるため、一覧監視のライフサイクルを別フラグにする。
        self._device_list_monitoring_active: bool = False

        # Auto Select 状態を mic/speaker で独立管理する。
        # 監視スレッド自体は 1 本 (update() が両方のリストを一括で refresh する
        # ため分けても大きな利点なし) だが、Before/After callback は各サイド
        # の active フラグに応じて選択的に発火する。従来は controller 側で
        # 「相手側が OFF なら monitoring 全体を止める」という相互参照ガードが
        # 必要だったが、DeviceManager にフラグを持たせることで撤去できる。
        self._mic_auto_active: bool = False
        self._speaker_auto_active: bool = False
        self._tracked_speaker_endpoint = None

        # 「実使用中エンドポイント」を追跡する tracker。Auto Speaker Select が
        # アクティブなときのみ起動する (マイク側は起動しない。理由は
        # setMicAutoActive の docstring 参照)。tracker の on_change コールバックは
        # 監視スレッド (別スレッド) から呼ばれ、内部で updateSelectedSpeakerDevice
        # 相当の callback を発火する。tracker が None (無音) を返す場合は既存の
        # Multimedia default 検出 (update() → noticeUpdateDevices →
        # setSpeakerDefaultDevice) が生きているので何もしない = 前回選択を維持。
        # _mic_endpoint_tracker は常に None のままだが、pause/resume/stop 経路の
        # 対称性のためフィールドは残す。
        self._mic_endpoint_tracker: Optional[ActiveEndpointTracker] = None
        self._speaker_endpoint_tracker: Optional[ActiveEndpointTracker] = None
        # stop() が COM 呼び出しの滞留でタイムアウトした場合、旧 tracker の
        # apartment 終了を待ってから再起動するための回収スレッド。
        self._speaker_endpoint_tracker_reaper: Optional[Thread] = None

        self._identity_namespace = uuid4().hex
        self._topology_generation = 0
        self._initialized = True

        # Best-effort single update: if PyAudio is available, attempt to populate
        # real device lists. Keep this short and ignore errors to avoid import-time
        # failures.
        try:
            if PyAudio is not None:
                try:
                    # update() is robust and will fall back to defaults if audio libs
                    # are missing or fail; do not let exceptions bubble up.
                    self.update()
                except Exception:
                    errorLogging()
        except Exception:
            # defensive: if errorLogging isn't available or other issues occur,
            # swallow to avoid breaking initialization
            pass

    # mic_devices/default_mic_device/speaker_devices/default_speaker_device は
    # _DeviceSnapshot 経由の読み取り専用プロパティ(項目32)。既存の呼び出し
    # 側 (getMicDevices() 等、_applyDeviceDiffs() 等) は素の属性アクセスと
    # 見分けが付かないため変更不要。
    @property
    def mic_devices(self) -> Dict[str, List[Dict[str, Any]]]:
        return self._device_snapshot.mic_devices

    @property
    def default_mic_device(self) -> Dict[str, Any]:
        return self._device_snapshot.default_mic_device

    @property
    def speaker_devices(self) -> List[Dict[str, Any]]:
        return self._device_snapshot.speaker_devices

    @property
    def default_speaker_device(self) -> Dict[str, Any]:
        return self._device_snapshot.default_speaker_device

    def _linuxMicDevices(self):
        """PipeWire inputs as one host. These are the RVC inputs, not legacy recorder devices."""
        no_device = {"host": {"index": -1, "name": "NoHost"}, "device": {"index": -1, "name": "NoDevice"}}
        try:
            from models.audio_routing.source_bridge import PIPEWIRE_MIC_HOST, microphone_devices
            devices, default = microphone_devices()
        except RuntimeError:
            # pw-dump is missing or the graph is unreadable: same as no inputs.
            return {}, no_device
        except Exception:
            errorLogging()
            return {}, no_device
        if not devices:
            return {}, no_device
        host = {"index": 0, "name": PIPEWIRE_MIC_HOST}
        return {PIPEWIRE_MIC_HOST: devices}, {"host": host, "device": default}

    def update(self):
        # A topology event during enumeration belongs to the next snapshot.
        # Tagging the old snapshot with that event would hide a reused slot.
        generation = self._topology_generation
        buffer_mic_devices: Dict[str, List[Dict[str, Any]]] = {}
        buffer_default_mic_device: Dict[str, Any] = {"host": {"index": -1, "name": "NoHost"}, "device": {"index": -1, "name": "NoDevice"}}
        buffer_speaker_devices: List[Dict[str, Any]] = []
        buffer_default_speaker_device: Dict[str, Any] = {"device": {"index": -1, "name": "NoDevice"}}

        if PyAudio is None:
            # PyAudio not available (PyAudioWPatch is Windows-only). On Linux
            # the Mic list comes from PipeWire instead; elsewhere keep defaults.
            if sys.platform.startswith("linux"):
                buffer_mic_devices, buffer_default_mic_device = self._linuxMicDevices()
            self._device_snapshot = self._identifiedSnapshot(
                generation=generation,
                mic_devices=buffer_mic_devices or {"NoHost": [{"index": -1, "name": "NoDevice"}]},
                default_mic_device=buffer_default_mic_device,
                speaker_devices=buffer_speaker_devices or [{"index": -1, "name": "NoDevice"}],
                default_speaker_device=buffer_default_speaker_device,
            )
            return

        try:
            # ロックで PortAudio/WASAPI の並行操作を防ぐ。
            # recorder 側の open と衝突するとデッドロックし得る。
            with pyaudio_op_lock, PyAudio() as p:
                # gather input devices grouped by host
                for host_index in range(p.get_host_api_count()):
                    host = p.get_host_api_info_by_index(host_index)
                    device_count = host.get('deviceCount', 0)
                    for device_index in range(device_count):
                        device = p.get_device_info_by_host_api_device_index(host_index, device_index)
                        if device.get("maxInputChannels", 0) > 0 and not device.get("isLoopbackDevice", True):
                            buffer_mic_devices.setdefault(host["name"], []).append(device)
                if not buffer_mic_devices:
                    buffer_mic_devices = {"NoHost": [{"index": -1, "name": "NoDevice"}]}

                api_info = p.get_default_host_api_info()
                default_mic_device = api_info.get("defaultInputDevice", -1)

                for host_index in range(p.get_host_api_count()):
                    host = p.get_host_api_info_by_index(host_index)
                    device_count = host.get('deviceCount', 0)
                    for device_index in range(device_count):
                        device = p.get_device_info_by_host_api_device_index(host_index, device_index)
                        if device.get("index") == default_mic_device:
                            buffer_default_mic_device = {"host": host, "device": device}
                            break
                    else:
                        continue
                    break

                # Loopbacks are already enumerated by PortAudio. Matching each
                # render device by a name substring duplicates or conflates them.
                if paWASAPI is not None:
                    try:
                        buffer_speaker_devices = sorted(
                            [dict(d) for d in p.get_loopback_device_info_generator()],
                            key=lambda d: d.get("index", -1))
                        wasapi_info = p.get_host_api_info_by_type(paWASAPI)
                        output_index = wasapi_info.get("defaultOutputDevice", -1)
                        output = p.get_device_info_by_index(output_index)
                        native_id = output.get("endpoint_id")
                        matches = [d for d in buffer_speaker_devices
                                   if (d.get("endpoint_id") == native_id if native_id else
                                       d.get("name", "").strip() == output.get("name", "").strip() + " [Loopback]")]
                        if len(matches) == 1:
                            buffer_default_speaker_device = {"device": matches[0]}
                    except Exception:
                        pass
                buffer_speaker_devices = buffer_speaker_devices or [{"index": -1, "name": "NoDevice"}]

        except Exception:
            errorLogging()

        self._device_snapshot = self._identifiedSnapshot(
            generation=generation,
            mic_devices=buffer_mic_devices,
            default_mic_device=buffer_default_mic_device,
            speaker_devices=buffer_speaker_devices,
            default_speaker_device=buffer_default_speaker_device,
        )

    def _invalidateDeviceIncarnations(self):
        # COM callbacks never take the PyAudio lock. A topology event invalidates
        # slot-only identities, including same-name, same-format replacements.
        self._topology_generation += 1

    @staticmethod
    def _windowsEndpointIds(*, locked=False):
        if sys.platform != "win32" or AudioUtilities is None or comtypes is None:
            return {}
        comtypes.CoInitialize()
        try:
            result = {}
            with nullcontext() if locked else pyaudio_op_lock:
                endpoints, endpoint = [], None
                try:
                    endpoints = AudioUtilities.GetAllDevices()
                    for endpoint in endpoints:
                        result.setdefault(endpoint.FriendlyName, []).append(endpoint.id)
                finally:
                    # COM references must die in this apartment, before uninit.
                    endpoint = None
                    endpoints = []
            return result
        except Exception:
            errorLogging()
            return {}
        finally:
            comtypes.CoUninitialize()

    def getOpenedDevice(self, audio, actual):
        """Resolve this open's slot using its PortAudio owner; caller holds the audio lock."""
        generation = self._topology_generation
        loopback = actual.get("isLoopbackDevice", False)
        host = {"name": str(actual.get("hostApi", "unknown"))}
        devices, endpoints = [actual], {}
        try:
            host = audio.get_host_api_info_by_index(actual["hostApi"])
            devices = [audio.get_device_info_by_host_api_device_index(actual["hostApi"], index)
                       for index in range(host["deviceCount"])]
            devices = [d for d in devices if d.get("maxInputChannels", 0) > 0
                       and d.get("isLoopbackDevice", False) == loopback]
            endpoints = self._windowsEndpointIds(locked=True)
        except Exception:
            # Capture still works without native IDs, but the requested ID is
            # not evidence of what this open owns. Publish a slot identity.
            errorLogging()
        if not any(d.get("index") == actual["index"] for d in devices):
            devices.append(actual)
            endpoints = {}
        devices = [actual if d.get("index") == actual["index"] else d for d in devices]
        missing = {"device": {"name": "NoDevice", "index": -1}}
        snapshot = self._identifiedSnapshot(
            mic_devices={} if loopback else {host["name"]: devices},
            default_mic_device={**missing, "host": host},
            speaker_devices=devices if loopback else [],
            default_speaker_device=missing, generation=generation, endpoint_ids=endpoints)
        rows = snapshot.speaker_devices if loopback else snapshot.mic_devices[host["name"]]
        opened = next(d for d in rows if d.get("index") == actual["index"])
        return {**opened, "host_name": host["name"]}

    def _identifiedSnapshot(self, *, mic_devices, default_mic_device,
                            speaker_devices, default_speaker_device, generation=None, endpoint_ids=None):
        namespace = getattr(self, "_identity_namespace", "initial")
        if generation is None:
            generation = getattr(self, "_topology_generation", 0)
        endpoints = endpoint_ids
        if endpoints is None:
            endpoints = self._windowsEndpointIds() if mic_devices or speaker_devices else {}
        counts = {}
        for host, devices in mic_devices.items():
            for d in devices:
                counts[("mic", host, d.get("name"))] = counts.get(("mic", host, d.get("name")), 0) + 1
        for d in speaker_devices:
            key = ("speaker", d.get("hostApi", "WASAPI"), d.get("name"))
            counts[key] = counts.get(key, 0) + 1

        def identify(device, host, source):
            device = dict(device)
            if device.get("name") == "NoDevice":
                return device
            native = next((device.get(key) for key in
                           ("endpoint_id", "deviceUID", "uid") if device.get(key)), None)
            label = device.get("name", "").removesuffix(" [Loopback]")
            mapped = endpoints.get(label, [])
            if not native and len(mapped) == 1 and counts.get((source, host, device.get("name"))) == 1:
                native = mapped[0]
                device["endpoint_id"] = native
            if native:
                identity = f"{source}:{host}:{native}"
            elif device.get("node_name"):
                identity = f"pipewire:{device['node_name']}"
            else:
                # PortAudio builds without an endpoint ID expose only slots.
                # Never persistently equate a reused slot with the old endpoint.
                identity = f"pa:{namespace}:{generation}:{source}:{host}:{device.get('index')}"
            device["id"] = identity
            device["incarnation"] = (generation, device.get("object_serial"))
            return device

        mics = {host: [identify(d, host, "mic") for d in devices]
                for host, devices in mic_devices.items()}
        speakers = [identify(d, d.get("hostApi", "WASAPI"), "speaker") for d in speaker_devices]
        mic_default = dict(default_mic_device)
        host = mic_default.get("host", {}).get("name", "NoHost")
        mic_default["device"] = identify(mic_default["device"], host, "mic")
        speaker_default = dict(default_speaker_device)
        d = speaker_default["device"]
        speaker_default["device"] = identify(d, d.get("hostApi", "WASAPI"), "speaker")
        if getattr(self, "_speaker_auto_active", False):
            tracked = self._trackedSpeakerDevice(speakers)
            if tracked is not None:
                speaker_default = {"device": tracked}
        return _DeviceSnapshot(mics, mic_default, speakers, speaker_default)

    def _applyDeviceDiffs(self) -> None:
        """update() 後の一覧と prev_* を比較して update_flag_* を立て、
        prev_* を最新に置き換える (副作用のみ、戻り値なし)。

        monitoring ループからのみ呼ばれる前提。他所から呼ぶと prev_* が
        意図せず上書きされ、次回の差分検知が不正確になる。以前は
        `checkUpdate` という副作用の無さそうな名前だったため rename した。
        """
        if capture_key(self.prev_default_mic_device["device"]) != capture_key(self.default_mic_device["device"]):
            self.update_flag_default_mic_device = True
            self.prev_default_mic_device = self.default_mic_device
        if capture_key(self.prev_default_speaker_device["device"]) != capture_key(self.default_speaker_device["device"]):
            self.update_flag_default_speaker_device = True
            self.prev_default_speaker_device = self.default_speaker_device
        if self.prev_mic_host != [host for host in self.mic_devices]:
            self.update_flag_host_list = True
            self.prev_mic_host = [host for host in self.mic_devices]
        if {key: [capture_key(device) for device in devices] for key, devices in self.prev_mic_devices.items()} != {key: [capture_key(device) for device in devices] for key, devices in self.mic_devices.items()}:
            self.update_flag_mic_device_list = True
            self.prev_mic_devices = self.mic_devices
        if [capture_key(device) for device in self.prev_speaker_devices] != [capture_key(device) for device in self.speaker_devices]:
            self.update_flag_speaker_device_list = True
            self.prev_speaker_devices = self.speaker_devices

    def monitoring(self):
        """デバイス変更を監視するスレッド本体。

        フロー:
          1. COM の endpoint 通知を待つ (通知またはポーリング fallback として最大 2s)
          2. 通知が来たら Before callback → update() → noticeUpdate → After callback
          3. stop_event が set されていれば即座に終了

        以前は「COM 通知後、20s ポーリングで変化を待つ」ループがあったが、
        (a) COM 通知が届いた時点でほぼ確実にデバイス一覧は変化済み、
        (b) 変化しないケースでは 20s 待ち続けてもリソース浪費なだけ、
        (c) その間 stop_event を見ないので OFF 応答が遅くなる、という
        3 点の理由で削除した。update() 一発と noticeUpdate で必要十分。

        COM 登録について: 以前はこのループの反復ごと (=通知を受けるたび) に
        CoInitialize → RegisterEndpointNotificationCallback →
        UnregisterEndpointNotificationCallback → CoUninitialize を
        繰り返していた。IMMNotificationClient は元々「スレッド生存中は
        登録しっぱなしにし、変更があれば COM 側が勝手にコールバックを
        呼んでくる」設計 (fire-and-forget) で使うのが Microsoft の想定する
        使い方であり、同じファイル内の ActiveEndpointTracker._run() も
        その作法 (CoInitialize/CoUninitialize をスレッド開始・終了時に
        1 回ずつ) に従っている。ここも合わせ、COM 登録・CoInitialize は
        スレッド開始時に 1 回だけ行い、スレッド終了時に 1 回だけ後始末する。
        """
        com_initialized = False
        com_registered = False
        cb = None
        enumerator = None
        if comtypes is not None and AudioUtilities is not None:
            try:
                comtypes.CoInitialize()
                com_initialized = True
                cb = Client(self._notify_event, self._invalidateDeviceIncarnations)
                enumerator = AudioUtilities.GetDeviceEnumerator()
                enumerator.RegisterEndpointNotificationCallback(cb)
                com_registered = True
            except Exception:
                # COM 監視の初期化に失敗したらポーリング fallback に落ちる。
                errorLogging()
                if com_initialized and not com_registered:
                    try:
                        comtypes.CoUninitialize()
                    except Exception:
                        pass
                    com_initialized = False

        next_reconcile = monotonic() + self._COM_RECONCILE_INTERVAL_SEC
        try:
            while not self._stop_event.is_set():
                try:
                    # Notifications and normal stop wake this wait immediately;
                    # a stop flag alone is still checked at most two seconds later.
                    notified = self._notify_event.wait(timeout=self._MONITOR_WAIT_TIMEOUT_SEC)
                    if self._stop_event.is_set():
                        break
                    if com_registered and not notified and monotonic() < next_reconcile:
                        continue
                    # Consume before enumeration. A notification arriving during
                    # update remains set for the next iteration. Without COM,
                    # every timeout still polls (including the Linux path).
                    self._notify_event.clear()
                    next_reconcile = monotonic() + self._COM_RECONCILE_INTERVAL_SEC

                    # 通知を受けた直後 (または COM 未登録時の定期ポーリング)
                    # のデバイス一覧再構築フェーズ。Before/After callback は
                    # Auto がアクティブな側のみ発火。相手側の Auto は無効な
                    # 状態でも、update() は両方のデバイスリストを refresh
                    # する (副作用の少ない読み取りなので always-run)。
                    if self._mic_auto_active:
                        self.runProcessBeforeUpdateMicDevices()
                    if self._speaker_auto_active:
                        self.runProcessBeforeUpdateSpeakerDevices()
                    self.update()
                    if self._stop_event.is_set():
                        break
                    self._applyDeviceDiffs()
                    self.noticeUpdateDevices()
                    if self._mic_auto_active:
                        self.runProcessAfterUpdateMicDevices()
                    if self._speaker_auto_active:
                        self.runProcessAfterUpdateSpeakerDevices()
                except Exception:
                    errorLogging()
                    # 個別の例外で暴走ループにならないよう、短い wait を挟む
                    self._stop_event.wait(timeout=0.5)
        except Exception:
            errorLogging()
        finally:
            if com_registered:
                try:
                    enumerator.UnregisterEndpointNotificationCallback(cb)
                except Exception:
                    # best-effort unregister
                    pass
            if com_initialized:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def startMonitoring(self):
        """公開 API。単体で呼ばれても安全なよう _lifecycle_lock を取る。"""
        with self._lifecycle_lock:
            self._startMonitoringLocked()

    def _startMonitoringLocked(self) -> None:
        """_lifecycle_lock を既に保持している前提の内部実装。"""
        # 既に稼働中なら何もしない (冪等)
        # A stopped worker may still be in COM cleanup. Never clear its event
        # or replace its reference until it has actually exited.
        if self.th_monitoring is not None and self.th_monitoring.is_alive():
            return
        self._monitor_stop_logged = False
        self._stop_event.clear()
        # notify_event は init 時に作った同一インスタンスを再利用し
        # 状態だけ clear する。以前は毎回 Event() で作り直していたが、
        # startMonitoring と stopMonitoring が並行実行された場合に
        # stopMonitoring が古い Event を set し、新しく起動したスレッドは
        # 新 Event を wait したまま起きられない、という race が発生していた
        # (_lifecycle_lock 導入後もこのイベント自体の再生成をしない設計は
        # そのまま維持する)。
        self._notify_event.clear()
        self.th_monitoring = Thread(target=self.monitoring, daemon=True)
        self.th_monitoring.start()

    def setMicAutoActive(self, active: bool) -> None:
        """Auto Mic Select の有効/無効を DeviceManager 側で受け取る。

        監視スレッドの起動/停止判断はここで完結させ、controller 側が
        相手側 (speaker) の状態を見て判断する必要を無くす。

        マイク側は speaker と違い ActiveEndpointTracker (peak 追従) を
        起動しない。Windows の IAudioMeterInformation は capture
        エンドポイントについて「そのデバイスを能動的に掴んでいる
        クライアントがいる時」しかピークを返さない
        (active_endpoint_tracker.py の「既知の制限」参照)。VRCT は選択中の
        マイク 1 本しか開かないため、非選択マイクは基本ピーク 0 のまま =
        追従先が無い。逆に VB-Audio Virtual Cable のような「常時他アプリの
        音が流れている」仮想 capture だけがピークを持ち、Auto ON にした
        瞬間 OS 既定を無視してそこへ張り替わる誤動作になっていた
        (Windows 規定とずれる / UI が一瞬既定を表示してすぐ戻る)。
        マイクの Auto Select は monitoring スレッドによる OS 既定デバイス
        追従のみとする。

        _lifecycle_lock で flag 更新〜monitoring 起動/停止判断までを 1 つの
        原子操作にする。setMicAutoActive/setSpeakerAutoActive は別々の
        エンドポイント (mainloop のロック) から並行に呼ばれ得るため、
        ここでロックしないと (a) 両方が同時に monitoring スレッドを起動して
        2 本走る、(b) 片方が active フラグを書く前にもう片方が
        「両方 inactive」と誤判定して monitoring を止める、といった競合が
        起きる。
        """
        with self._lifecycle_lock:
            self._mic_auto_active = active
            # マイク側 tracker は常に起動しない。過去の経路や将来の変更で
            # 生き残りがあっても確実に片付けるため stop 側だけ無条件で呼ぶ
            # (tracker is None なら no-op)。
            self._stopMicEndpointTrackerLocked()
            self._syncMonitoringLifecycleLocked()

    def setSpeakerAutoActive(self, active: bool) -> None:
        """Auto Speaker Select の有効/無効を DeviceManager 側で受け取る。
        詳細は setMicAutoActive のコメント参照。"""
        with self._lifecycle_lock:
            self._speaker_auto_active = active
            if not active:
                self._tracked_speaker_endpoint = None
            if active:
                self._startSpeakerEndpointTrackerLocked()
            else:
                self._stopSpeakerEndpointTrackerLocked()
            self._syncMonitoringLifecycleLocked()

    def setDeviceListMonitoringActive(self, active: bool) -> None:
        """デバイス一覧監視の有効/無効を設定する。

        デバイスの再接続を検出するための一覧更新は、Auto Select の設定とは
        独立して動作させる。Auto Select が両方 OFF の場合でもこのフラグが
        active なら monitoring スレッドを維持し、一覧 callback を発火する。
        Auto Select の選択変更や endpoint tracker の起動は、従来どおり
        setMicAutoActive/setSpeakerAutoActive 側のフラグで制御する。
        """
        with self._lifecycle_lock:
            self._device_list_monitoring_active = active
            self._syncMonitoringLifecycleLocked()

    def _stopMicEndpointTrackerLocked(self) -> None:
        """_lifecycle_lock を既に保持している前提の内部実装。

        マイク側は ActiveEndpointTracker を起動しない (setMicAutoActive の
        docstring 参照) ため通常 `_mic_endpoint_tracker` は常に None。
        将来マイク peak 追従を復活させる場合や、旧状態が残っていた場合の
        後片付けとして stop 経路だけ残す。"""
        tracker = self._mic_endpoint_tracker
        self._mic_endpoint_tracker = None
        if tracker is not None:
            tracker.stop()

    def _startSpeakerEndpointTrackerLocked(self) -> None:
        """_lifecycle_lock を既に保持している前提の内部実装。"""
        if self._speaker_endpoint_tracker is not None:
            tracker = self._speaker_endpoint_tracker
            is_running = getattr(tracker, "is_running", None)
            # 古いテスト用スタブなどが is_running() を持たない場合は、
            # 既存 tracker があること自体を起動済みとして扱う。
            if not callable(is_running) or is_running():
                is_stop_requested = getattr(tracker, "is_stop_requested", None)
                if callable(is_stop_requested) and is_stop_requested():
                    printLog(
                        "DeviceManager: speaker endpoint tracker restart deferred "
                        "until the previous tracker thread has stopped."
                    )
                return
            # timeout 後に保持していた tracker の COM cleanup が完了済み。
            self._speaker_endpoint_tracker = None
        tracker = ActiveEndpointTracker("render", com_lock=pyaudio_op_lock)
        if callable(getattr(tracker, "set_on_change_id_callback", None)):
            tracker.set_on_change_id_callback(self._onActiveSpeakerEndpointChanged)
        else:
            tracker.set_on_change_callback(self._onActiveSpeakerEndpointChanged)
        tracker.start()
        self._speaker_endpoint_tracker = tracker

    def _stopSpeakerEndpointTrackerLocked(self) -> None:
        """_lifecycle_lock を既に保持している前提の内部実装。"""
        tracker = self._speaker_endpoint_tracker
        if tracker is not None:
            stopped = tracker.stop()
            if stopped is False:
                # 旧 tracker を参照し続けることで、stop timeout 後の再ONで
                # 新しい COM tracker が並行起動することを防ぐ。旧スレッドの
                # 終了後、Auto Select がまだ ON なら一度だけ再起動する。
                self._scheduleSpeakerEndpointTrackerReaperLocked(tracker)
            else:
                self._speaker_endpoint_tracker = None

    def _scheduleSpeakerEndpointTrackerReaperLocked(
        self, tracker: ActiveEndpointTracker
    ) -> None:
        """_lifecycle_lock を保持したまま、tracker の終了待ちを予約する。"""
        reaper = self._speaker_endpoint_tracker_reaper
        if reaper is not None and reaper.is_alive():
            return

        def reap() -> None:
            wait_until_stopped = getattr(tracker, "wait_until_stopped", None)
            if not callable(wait_until_stopped):
                # 実装済み tracker では必ず存在する。互換スタブで存在しない
                # 場合は、再起動を許可せず旧参照を保持したまま安全側に倒す。
                return
            wait_until_stopped()
            with self._lifecycle_lock:
                if self._speaker_endpoint_tracker is not tracker:
                    return
                self._speaker_endpoint_tracker = None
                self._speaker_endpoint_tracker_reaper = None
                if self._speaker_auto_active:
                    self._startSpeakerEndpointTrackerLocked()

        self._speaker_endpoint_tracker_reaper = Thread(
            target=reap,
            daemon=True,
            name="speaker_endpoint_tracker_reaper",
        )
        self._speaker_endpoint_tracker_reaper.start()

    def pauseMicEndpointTracker(self) -> None:
        """外部から tracker を一時停止し、進行中の COM 呼び出しが
        あれば完了を待つ (Session の reconfigure 前に使用)。

        pause() は次の poll の開始をブロックするだけで、既に走っている
        _com_lock 内の Activate/GetPeakValue は完了を待たない。ここで
        pyaudio_op_lock を一瞬 acquire/release することでバリアとして
        機能させ、以降 Session の Recorder open/close 中に tracker の
        COM が同時実行されないことを保証する。
        """
        tracker = self._mic_endpoint_tracker
        if tracker is None:
            return
        tracker.pause()
        # バリア: tracker が _com_lock (=pyaudio_op_lock) 保持中なら待つ
        # (上限あり、詳細は _PAUSE_BARRIER_TIMEOUT_SEC のコメント参照)
        acquired = pyaudio_op_lock.acquire(timeout=_PAUSE_BARRIER_TIMEOUT_SEC)
        if acquired:
            pyaudio_op_lock.release()
        else:
            printLog(
                f"pauseMicEndpointTracker: barrier timed out after "
                f"{_PAUSE_BARRIER_TIMEOUT_SEC}s waiting for pyaudio_op_lock; "
                "a COM call may be stuck. Proceeding without the barrier."
            )

    def resumeMicEndpointTracker(self) -> None:
        tracker = self._mic_endpoint_tracker
        if tracker is not None:
            tracker.resume()

    def pauseSpeakerEndpointTracker(self) -> None:
        """スピーカー側 tracker の一時停止。詳細は pauseMicEndpointTracker 参照。"""
        tracker = self._speaker_endpoint_tracker
        if tracker is None:
            return
        tracker.pause()
        acquired = pyaudio_op_lock.acquire(timeout=_PAUSE_BARRIER_TIMEOUT_SEC)
        if acquired:
            pyaudio_op_lock.release()
        else:
            printLog(
                f"pauseSpeakerEndpointTracker: barrier timed out after "
                f"{_PAUSE_BARRIER_TIMEOUT_SEC}s waiting for pyaudio_op_lock; "
                "a COM call may be stuck. Proceeding without the barrier."
            )

    def resumeSpeakerEndpointTracker(self) -> None:
        tracker = self._speaker_endpoint_tracker
        if tracker is not None:
            tracker.resume()

    def _trackedSpeakerDevice(self, devices):
        endpoint = getattr(self, "_tracked_speaker_endpoint", None)
        if endpoint is None:
            return None
        if isinstance(endpoint, dict):
            matches = [d for d in devices if d.get("endpoint_id") == endpoint.get("id")]
            if not matches:
                matches = [d for d in devices if not d.get("endpoint_id")
                           and d.get("name") == endpoint.get("name", "") + " [Loopback]"]
        else:
            matches = [d for d in devices if d.get("name", "").strip() == endpoint.strip() + " [Loopback]"]
        return matches[0] if len(matches) == 1 else None

    def _onActiveSpeakerEndpointChanged(self, endpoint) -> None:
        if endpoint is None or not self._speaker_auto_active:
            return
        self._tracked_speaker_endpoint = endpoint
        selected = self._trackedSpeakerDevice(self.speaker_devices)
        if selected is None:
            return
        # One snapshot target, one reconciliation callback. No selection is
        # published until the controller has switched the active recorder.
        old = self._device_snapshot
        self._device_snapshot = _DeviceSnapshot(old.mic_devices, old.default_mic_device,
                                               old.speaker_devices, {"device": selected})
        if callable(self.callback_default_speaker_device):
            self.callback_default_speaker_device(selected["name"])

    def _findSpeakerDeviceByName(self, endpoint_name: str) -> Optional[str]:
        matches = [d for d in self.speaker_devices
                   if d.get("name", "").strip() == endpoint_name.strip() + " [Loopback]"]
        return matches[0]["name"] if len(matches) == 1 else None

    def _syncMonitoringLifecycleLocked(self) -> None:
        """一覧監視または Auto Select の active フラグに応じて monitoring を起動/停止。

        一覧監視または少なくとも 1 サイドの Auto Select が active なら起動し、
        すべて inactive なら停止する。個々の設定変更
        (setDeviceListMonitoringActive/setMicAutoActive/setSpeakerAutoActive) の
        後に呼ぶ。
        _lifecycle_lock を既に保持している前提の内部実装。
        """
        any_active = (
            self._device_list_monitoring_active
            or self._mic_auto_active
            or self._speaker_auto_active
        )
        if any_active:
            self._startMonitoringLocked()
        else:
            self._stopMonitoringLocked()

    def stopMonitoring(self):
        """公開 API。単体で呼ばれても安全なよう _lifecycle_lock を取る。"""
        with self._lifecycle_lock:
            self._stopMonitoringLocked()

    def _stopMonitoringLocked(self) -> None:
        """非ブロッキング stop。event を set して短時間だけ join を試みる。
        _lifecycle_lock を既に保持している前提の内部実装。

        以前は join(timeout=5) だったが、内部ループが flag を最大 20s 見て
        いなかったため endpoint 呼び出しが 5s 丸ごとブロックされていた。
        現在は Event ベースなのでスレッドは即抜ける想定 (数十 ms 以内)。
        万一 COM 呼び出しなどで抜けが遅れても endpoint を待たせないよう、
        join タイムアウトは 0.5s に短縮した (daemon スレッドなのでプロセス
        終了時に確実に片付く)。
        """
        self._stop_event.set()
        # notify_event は init/startMonitoring で確実に生成済み (再代入は
        # startMonitoring では行わない設計に統一)。COM 通知待ちで止まって
        # いるスレッドを即座に起こす。
        self._notify_event.set()
        if getattr(self, "th_monitoring", None) is not None:
            try:
                self.th_monitoring.join(timeout=0.5)
                if self.th_monitoring.is_alive() and not getattr(self, "_monitor_stop_logged", False):
                    self._monitor_stop_logged = True
                    printLog("DeviceManager: monitoring stop timed out; restart deferred until the worker exits")
            except Exception:
                # join がスレッド非依存の理由で失敗しても致命的ではない
                pass

    def setCallbackDefaultMicDevice(self, callback):
        self.callback_default_mic_device = callback

    def clearCallbackDefaultMicDevice(self):
        self.callback_default_mic_device = None

    def setCallbackDefaultSpeakerDevice(self, callback):
        self.callback_default_speaker_device = callback

    def clearCallbackDefaultSpeakerDevice(self):
        self.callback_default_speaker_device = None

    def setCallbackHostList(self, callback):
        self.callback_host_list = callback

    def clearCallbackHostList(self):
        self.callback_host_list = None

    def setCallbackMicDeviceList(self, callback):
        self.callback_mic_device_list = callback

    def clearCallbackMicDeviceList(self):
        self.callback_mic_device_list = None

    def setCallbackSpeakerDeviceList(self, callback):
        self.callback_speaker_device_list = callback

    def clearCallbackSpeakerDeviceList(self):
        self.callback_speaker_device_list = None

    def setCallbackProcessBeforeUpdateMicDevices(self, callback):
        self.callback_process_before_update_mic_devices = callback

    def clearCallbackProcessBeforeUpdateMicDevices(self):
        self.callback_process_before_update_mic_devices = None

    def runProcessBeforeUpdateMicDevices(self):
        if isinstance(self.callback_process_before_update_mic_devices, Callable):
            try:
                self.callback_process_before_update_mic_devices()
            except Exception:
                errorLogging()

    def setCallbackProcessAfterUpdateMicDevices(self, callback):
        self.callback_process_after_update_mic_devices = callback

    def clearCallbackProcessAfterUpdateMicDevices(self):
        self.callback_process_after_update_mic_devices = None

    def runProcessAfterUpdateMicDevices(self):
        if isinstance(self.callback_process_after_update_mic_devices, Callable):
            try:
                self.callback_process_after_update_mic_devices()
            except Exception:
                errorLogging()

    def setCallbackProcessBeforeUpdateSpeakerDevices(self, callback):
        self.callback_process_before_update_speaker_devices = callback

    def clearCallbackProcessBeforeUpdateSpeakerDevices(self):
        self.callback_process_before_update_speaker_devices = None

    def runProcessBeforeUpdateSpeakerDevices(self):
        if isinstance(self.callback_process_before_update_speaker_devices, Callable):
            try:
                self.callback_process_before_update_speaker_devices()
            except Exception:
                errorLogging()

    def setCallbackProcessAfterUpdateSpeakerDevices(self, callback):
        self.callback_process_after_update_speaker_devices = callback

    def clearCallbackProcessAfterUpdateSpeakerDevices(self):
        self.callback_process_after_update_speaker_devices = None

    def runProcessAfterUpdateSpeakerDevices(self):
        if isinstance(self.callback_process_after_update_speaker_devices, Callable):
            try:
                self.callback_process_after_update_speaker_devices()
            except Exception:
                errorLogging()

    def setCallbackEndpointReconfiguredSpeaker(self, callback):
        self.callback_endpoint_reconfigured_speaker = callback

    def clearCallbackEndpointReconfiguredSpeaker(self):
        self.callback_endpoint_reconfigured_speaker = None

    def noticeUpdateDevices(self):
        if self.update_flag_default_mic_device is True:
            self.setMicDefaultDevice()
        if self.update_flag_default_speaker_device is True:
            self.setSpeakerDefaultDevice()
        if self.update_flag_host_list is True:
            self.setMicHostList()
        if self.update_flag_mic_device_list is True:
            self.setMicDeviceList()
        if self.update_flag_speaker_device_list is True:
            self.setSpeakerDeviceList()

        self.update_flag_default_mic_device = False
        self.update_flag_default_speaker_device = False
        self.update_flag_host_list = False
        self.update_flag_mic_device_list = False
        self.update_flag_speaker_device_list = False

    def setMicDefaultDevice(self):
        if isinstance(self.callback_default_mic_device, Callable):
            try:
                self.callback_default_mic_device(self.default_mic_device["host"]["name"], self.default_mic_device["device"]["name"])
            except Exception:
                errorLogging()

    def setSpeakerDefaultDevice(self):
        if isinstance(self.callback_default_speaker_device, Callable):
            try:
                self.callback_default_speaker_device(self.default_speaker_device["device"]["name"])
            except Exception:
                errorLogging()

    def setMicHostList(self):
        if isinstance(self.callback_host_list, Callable):
            try:
                self.callback_host_list()
            except Exception:
                errorLogging()

    def setMicDeviceList(self):
        if isinstance(self.callback_mic_device_list, Callable):
            try:
                self.callback_mic_device_list()
            except Exception:
                errorLogging()

    def setSpeakerDeviceList(self):
        if isinstance(self.callback_speaker_device_list, Callable):
            try:
                self.callback_speaker_device_list()
            except Exception:
                errorLogging()

    def getMicDevices(self):
        # Ensure initialized and return devices (safe default if still not populated)
        if not getattr(self, '_initialized', False):
            try:
                self.init()
            except Exception:
                try:
                    errorLogging()
                except Exception:
                    pass
        return getattr(self, 'mic_devices', {"NoHost": [{"index": -1, "name": "NoDevice"}]})

    def getDefaultMicDevice(self):
        # Ensure initialized and return default mic device (safe default if still not populated)
        if not getattr(self, '_initialized', False):
            try:
                self.init()
            except Exception:
                try:
                    errorLogging()
                except Exception:
                    pass
        return getattr(self, 'default_mic_device', {"host": {"index": -1, "name": "NoHost"}, "device": {"index": -1, "name": "NoDevice"}})

    def getSpeakerDevices(self):
        # Ensure initialized and return speaker devices (safe default if still not populated)
        if not getattr(self, '_initialized', False):
            try:
                self.init()
            except Exception:
                try:
                    errorLogging()
                except Exception:
                    pass
        return getattr(self, 'speaker_devices', [{"index": -1, "name": "NoDevice"}])

    def getDefaultSpeakerDevice(self):
        # Ensure initialized and return default speaker device (safe default if still not populated)
        if not getattr(self, '_initialized', False):
            try:
                self.init()
            except Exception:
                try:
                    errorLogging()
                except Exception:
                    pass
        return getattr(self, 'default_speaker_device', {"device": {"index": -1, "name": "NoDevice"}})

    def forceUpdateAndSetMicDevices(self):
        self.update()
        self.setMicHostList()
        self.setMicDeviceList()
        self.setMicDefaultDevice()

    def forceUpdateAndSetSpeakerDevices(self):
        self.update()
        self.setSpeakerDeviceList()
        self.setSpeakerDefaultDevice()

# Provide a module-level singleton.
#
# 注意: import には副作用がある。`DeviceManager.__new__` が `init()` を
# 呼び、`init()` は PyAudio が使えれば `update()` でデバイスを実際に
# 列挙する。つまり `import device_manager` しただけで PyAudio の
# デバイス列挙が走る (これは意図的。import 順によって初期化前の内部構造が
# 観測され NoDevice になる問題があったため。__new__ のコメント参照)。
#
# import 時に走らないのは監視スレッドだけで、これは
# `device_manager.startMonitoring()` を明示的に呼んだときに開始する。
device_manager = DeviceManager()

if __name__ == "__main__":
    print("DeviceManager demo. Call device_manager.init() and device_manager.startMonitoring() to run live monitoring.")
    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        print("exiting")
