"""Recorders that wrap speech_recognition microphone interfaces.

These classes provide small adapters that push raw audio bytes into queues.
They intentionally keep a thin API so the rest of the system can mock them
in tests.

デバイスライフサイクル整理と VAD ストリーミング撤退 (ADR-0004) の結果、
現在の設計は以下の通り:

- `BaseEnergyAndAudioRecorder` が mic/speaker 共通の唯一の Recorder として、
  音声データ (audio_queue) とエネルギー (energy_queue) の両方を同時に扱う。
  同一物理デバイスに対する PyAudio Microphone インスタンスは常に 1 つ。
- 発話区間検出・フレーズ境界・pause/resume/stop は `speech_recognition` の
  `listen_energy_and_audio_in_background` に完全に委任する (energy_threshold,
  phrase_time_limit)。独自 VAD/ストリーミング分割は行わない (ADR-0004 参照)。
  `callback_energy` フックにより、フレーズ確定を待たず生チャンクごとに
  エナジー値を取得できる (音量メーターのリアルタイム更新用)。
- PyAudio 操作は全て `pyaudio_op_lock` の下で行い、WASAPI ロック競合を防ぐ。
"""

import threading
from typing import Any, Callable, Optional
from speech_recognition import AudioSource, Recognizer, Microphone
from datetime import datetime
from errors import AudioPipelineFailure, ERROR_METADATA, ErrorCode
from utils import errorLogging, printLog, putDroppingOldestOnFull
from .utterance_diagnostics import utterance_diagnostics
from device_manager import device_manager, pyaudio_op_lock
from models.transcription.audio_vad import FRAME_DURATION_MS, VadRecognizerAdapter, VadSegmenter

# 直前に同じ物理デバイスを force-stop した直後は、WASAPI 側の解放が
# 完了しておらず Microphone.__enter__ 内の PyAudio.open() がブロックし
# たまま返らないことがある (open() 自体にタイムアウトが無い)。
# mainloop のハンドラワーカーは少数 (DEFAULT_WORKER_COUNT) しかなく、
# ここで無期限にブロックすると mic/speaker 以外の操作も含めてアプリ
# 全体が無応答になる。そのため open() は別スレッドで実行し、規定時間
# 内に完了しなければタイムアウトとして扱う。
_MIC_OPEN_TIMEOUT_SEC = 8.0


class _ReadErrorReportingStream:
    """MicrophoneStream の read 例外を Recorder へ返す薄いプロキシ。"""

    def __init__(self, stream: Any, handler: Callable[[Exception], None]) -> None:
        self._stream = stream
        self._handler = handler

    def read(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._stream.read(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - report and preserve original behavior
            self._handler(error)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _ErrorReportingSegmenter:
    """VAD adapter の process/flush 例外を Recorder へ返すプロキシ。"""

    def __init__(self, segmenter: Any, handler: Callable[[Exception], None]) -> None:
        self._segmenter = segmenter
        self._handler = handler

    def process(self, pcm_bytes: bytes) -> Any:
        try:
            return self._segmenter.process(pcm_bytes)
        except Exception as error:  # noqa: BLE001 - report and preserve original behavior
            self._handler(error)
            raise

    def flush(self) -> Any:
        try:
            return self._segmenter.flush()
        except Exception as error:  # noqa: BLE001 - report and preserve original behavior
            self._handler(error)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._segmenter, name)


def _close_audio_source(source):
    if getattr(source, "stream", None) is not None:
        source.__exit__(None, None, None)
    else:
        audio = getattr(source, "audio", None)
        if audio is not None:
            audio.terminate()


def _validate_audio_source(source: Any) -> Any:
    # Keep the opened stream for the listener. A second implicit open could
    # fail after start had already been reported as successful.
    try:
        source.__enter__()
        if source.stream is None:
            raise OSError("Audio device could not be opened")
        return source
    except Exception:
        _close_audio_source(source)
        raise


class _LockedAudioSource(AudioSource):
    """Own the validated stream until the listener closes it.

    Enter/exit remain serialized with enumeration. Cancellation is checked after
    acquiring that lock, including a listener that has not entered its context
    yet when OFF completes. A normal start reuses the already opened stream.
    """

    def __init__(self, source: Any) -> None:
        # AudioSource を継承するのは listen_energy_and_audio_in_background
        # の `assert isinstance(source, AudioSource)` を通すためだけ。
        # AudioSource.__init__ は "抽象クラスです" として
        # NotImplementedError を送出するガードなので、意図的に呼ばない。
        self._source = source
        self._cancelled = threading.Event()
        self._closed = False
        self._read_error_handler: Optional[Callable[[Exception], None]] = None

    def set_read_error_handler(self, handler: Callable[[Exception], None]) -> None:
        self._read_error_handler = handler

    def __enter__(self) -> Any:
        with pyaudio_op_lock:
            if self._cancelled.is_set():
                self._close_locked()
                raise OSError("Audio open cancelled")
            if getattr(self._source, "stream", None) is None:
                self._source.__enter__()
                self._closed = False
            if self._cancelled.is_set():
                self._close_locked()
                raise OSError("Audio open cancelled")
            stream = getattr(self._source, "stream", None)
            if (
                stream is not None
                and self._read_error_handler is not None
                and not isinstance(stream, _ReadErrorReportingStream)
            ):
                self._source.stream = _ReadErrorReportingStream(stream, self._read_error_handler)
        return self._source

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        with pyaudio_op_lock:
            return self._close_locked(exc_type, exc_value, traceback)

    def _close_locked(self, exc_type=None, exc_value=None, traceback=None):
        if not self._closed:
            if getattr(self._source, "stream", None) is not None:
                result = self._source.__exit__(exc_type, exc_value, traceback)
            else:
                result = _close_audio_source(self._source)
            self._closed = True
            return result

    def cancel(self):
        self._cancelled.set()

    def close(self):
        self.cancel()
        with pyaudio_op_lock:
            self._close_locked()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._source, name)


class AudioOpenBusy(OSError):
    """A native open still owns this source; no alternate may be started."""


_openers_lock = threading.Lock()
_openers = {}


class _MicrophoneOpener:
    def __init__(self, fallback_kwargs, device_kwargs):
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.source = None
        self.error = None
        self.cleanup_failed = False
        self.fallback_kwargs = fallback_kwargs
        self.device_kwargs = device_kwargs
        self.thread = threading.Thread(target=self.run, daemon=True, name="mic-open")

    def run(self):
        source = None
        try:
            source = _open_with_fallback(
                self.fallback_kwargs, cancelled=self.cancelled, **self.device_kwargs)
            with self.lock:
                if not self.cancelled.is_set():
                    self.source = source
                    source = None
                    self.done.set()
        except Exception as error:
            with self.lock:
                self.error = error
                self.done.set()
        finally:
            if source is not None:
                try:
                    with pyaudio_op_lock:
                        _close_audio_source(source)
                except Exception:
                    self.cleanup_failed = True
                    errorLogging()
            self.done.set()


def audioOpenOutstanding(source_kind):
    with _openers_lock:
        opener = _openers.get(source_kind)
        return opener is not None and (opener.thread.is_alive() or opener.cleanup_failed)


def _open_with_fallback(fallback_kwargs, *, cancelled=None, expected_device=None, **device_kwargs):
    cancelled = cancelled or threading.Event()
    # Fallbacks must name a concrete index. The session selects and publishes
    # alternates; an unlabelled library default is never opened here.
    candidates = [device_kwargs]
    if "device_index" in fallback_kwargs:
        candidates.append(fallback_kwargs)
    with pyaudio_op_lock:
        for candidate in candidates:
            if cancelled.is_set():
                raise AudioOpenBusy("Audio open cancelled")
            try:
                source = Microphone(**candidate)
                if cancelled.is_set():
                    _close_audio_source(source)
                    raise AudioOpenBusy("Audio open cancelled")
                source = _validate_audio_source(source)
                if expected_device is not None:
                    try:
                        actual = source.audio.get_device_info_by_index(candidate["device_index"])
                        native_keys = ("endpoint_id", "deviceUID", "uid")
                        missing_identity = any(expected_device.get(key) and not actual.get(key)
                                               for key in native_keys)
                        if missing_identity:
                            actual = device_manager.getOpenedDevice(source.audio, actual)
                        expected_id = next((expected_device[key] for key in native_keys if expected_device.get(key)), None)
                        actual_id = next((actual[key] for key in native_keys if actual.get(key)), None)
                        if expected_id and actual_id and expected_id != actual_id:
                            raise OSError("Audio endpoint changed while opening")
                        # Slot reuse must not be published as the former endpoint.
                        for key in ("name", "hostApi"):
                            if key in expected_device and key in actual and expected_device[key] != actual[key]:
                                raise OSError("Audio endpoint changed while opening")
                        source.opened_device = actual if missing_identity else {**expected_device, **actual}
                    except Exception:
                        _close_audio_source(source)
                        raise
                return source
            except AudioOpenBusy:
                raise
            except Exception:
                if candidate is candidates[-1]:
                    raise


def _create_microphone(fallback_kwargs, *, source_kind="mic", **device_kwargs):
    with _openers_lock:
        previous = _openers.get(source_kind)
        if previous is not None and (previous.thread.is_alive() or previous.cleanup_failed):
            raise AudioOpenBusy("Previous audio open is still outstanding")
        opener = _MicrophoneOpener(fallback_kwargs, device_kwargs)
        _openers[source_kind] = opener
        opener.thread.start()
    if opener.done.wait(timeout=_MIC_OPEN_TIMEOUT_SEC):
        opener.thread.join(timeout=0.1)
    with opener.lock:
        if not opener.done.is_set():
            opener.cancelled.set()
            raise AudioOpenBusy("Timed out opening audio device")
        if opener.error is not None:
            raise opener.error
        source = opener.source
        opener.source = None
    return _LockedAudioSource(source)


def _wrapStopperWithBlockingReadUnblock(
    source: Any,
    raw_stop: Callable[..., None],
    before_stop: Optional[Callable[[], None]] = None,
    after_stop: Optional[Callable[[], None]] = None,
) -> Callable[..., None]:
    """`listen_energy_and_audio_in_background`/`listen_with_segmenter_in_background`
    が返す生の stopper を、ブロッキング中の `stream.read()` を強制的に
    解除してから呼ぶようにラップする。エネルギー閾値方式/VAD方式の
    両 Recorder に共通する問題への対処なので、ここに集約して二重実装に
    よるドリフトを避ける。

    speech_recognition 側の stopper は listener スレッドの join() に
    タイムアウトを持たない。listener は self.source.stream.read() で
    ブロックしており、WASAPI ループバックの無音時などデータが来なく
    なると read() は返らず、stop() が永久にブロックしてしまう。
    Pa_StopStream (pyaudio_stream.stop_stream) は稼働中のストリームを
    別スレッドから止める用途の API で、進行中の read を強制的に返させる。
    Pa_CloseStream と異なり別スレッドから呼んでもデッドロックしない。
    self.source.stream は speech_recognition の MicrophoneStream ラッパで、
    実 PyAudio stream は .pyaudio_stream 属性経由でアクセスする。
    """

    def stopper(wait_for_stop: bool = True) -> None:
        if before_stop is not None:
            before_stop()
        if isinstance(source, _LockedAudioSource):
            source.cancel()
        try:
            with pyaudio_op_lock:
                sr_stream = getattr(source, "stream", None)
                pa_stream = (
                    getattr(sr_stream, "pyaudio_stream", None)
                    if sr_stream is not None
                    else None
                )
                if pa_stream is not None and not pa_stream.is_stopped():
                    pa_stream.stop_stream()
        except Exception:
            # 既に停止済み等、想定内の失敗もあり得るが原因調査のため記録する
            errorLogging()
        try:
            raw_stop(wait_for_stop=wait_for_stop)
        finally:
            if after_stop is not None:
                after_stop()

    return stopper


class BaseEnergyAndAudioRecorder:
    """Records audio and/or a raw energy stream from a single physical device.

    Energy-only callers (the config-panel volume meter) and transcription
    callers (mic/speaker send/receive) both go through this same recorder
    so a given physical device is only ever opened once. Every PyAudio
    operation is serialized via `pyaudio_op_lock`.

    フレーズ境界・エネルギー閾値による発話検出は `speech_recognition` の
    `listen_energy_and_audio_in_background` に完全委任する (energy_threshold /
    dynamic_energy_threshold / phrase_time_limit)。独自 VAD は使わない。
    この API は `listen_in_background` と同じ発話区間検出ロジックを使うが、
    追加で `callback_energy` フックを持ち、フレーズ確定を待たず生チャンク
    読み取りのたびにエナジー値を通知できる (config パネルの音量メーターを
    リアルタイム更新するために必要)。
    """

    def __init__(
        self,
        source: Any,
        energy_threshold: int,
        dynamic_energy_threshold: bool,
        phrase_time_limit: int,
        label: str = "mic",
    ) -> None:
        self.recorder = Recognizer()
        self.recorder.energy_threshold = energy_threshold
        self.recorder.dynamic_energy_threshold = dynamic_energy_threshold
        self.phrase_time_limit = phrase_time_limit
        self.stop = None
        self.pause = None
        self.resume = None

        if source is None:
            raise ValueError("audio source can't be None")

        self.source = source
        self.label = label
        self._stop_requested = threading.Event()
        self._device_error_lock = threading.Lock()
        self.device_error_info: Optional[AudioPipelineFailure] = None
        self.SAMPLE_RATE = source.SAMPLE_RATE
        self.SAMPLE_WIDTH = source.SAMPLE_WIDTH
        self.channels = getattr(source, "channels", 1)
        # Set when the background listener thread dies from an unexpected
        # stream error (e.g. the device was unplugged) rather than a normal
        # stop() call, so callers can surface a "device lost" notice instead
        # of silently going quiet.
        self.device_error_event = threading.Event()
        set_read_error_handler = getattr(source, "set_read_error_handler", None)
        if callable(set_read_error_handler):
            set_read_error_handler(self._on_stream_read_error)

    def _recording_error_code(self) -> ErrorCode:
        return ErrorCode.AUDIO_READ_ERROR

    def _set_device_error(self, error: Exception, error_code: Optional[ErrorCode] = None) -> None:
        if self._stop_requested.is_set():
            return
        with self._device_error_lock:
            if self.device_error_event.is_set():
                return
            code = error_code or self._recording_error_code()
            self.device_error_info = AudioPipelineFailure(
                error_code=code,
                stage="recording",
                source=self.label,
                message=ERROR_METADATA[code]["message"],
                exception_type=type(error).__name__,
            )
            errorLogging()
            self.device_error_event.set()

    def _on_stream_read_error(self, error: Exception) -> None:
        self._set_device_error(error)

    def adjustForNoise(self) -> None:
        with self.source:
            self.recorder.adjust_for_ambient_noise(self.source)

    def recordIntoQueue(self, audio_queue: Any, energy_queue: Any = None) -> None:
        """listen_energy_and_audio_in_background で発話区間ごとに audio を
        audio_queue に積む。energy_queue が指定されていれば、フレーズ確定を
        待たず生チャンク読み取りのたびに RMS を積む (callback_energy)。

        audio_queue には (raw_bytes, recorded_at) タプルを push する。
        フレーズの区切りは phrase_time_limit と energy_threshold ベースの
        発話終端検出に委ねる (listen_in_background と同じロジック)。
        """

        def audio_callback(_, audio) -> None:
            try:
                raw = audio.get_raw_data()
                item = (raw, datetime.now())
                # 文字起こしが実時間に追いつけていない状況。ここでブロック
                # すると listener スレッド (このコールバック自体) が止まり
                # 録音が滞るため、非ブロッキングで積み、満杯なら最も古い
                # チャンクを1つ捨てて追いつく方を優先する (フェーズ3項目20)。
                # audio_queue に maxsize が無い場合 (_DiscardQueue 等) は
                # 常にFalseが返る (Fullが発生しないため)。
                dropped = putDroppingOldestOnFull(audio_queue, item)
                utterance_diagnostics.queue_result(self.label, dropped)
            except Exception as error:  # noqa: BLE001 - report and preserve callback failure
                self._set_device_error(error)

        def energy_callback(energy) -> None:
            try:
                # 音量メーター用途で直近の値のみ意味を持つため、
                # audio_queue と同じ理由で非ブロッキング化し、消費側
                # (sendEnergy) が追いつけない場合は古い値を捨てる
                # (フェーズ3項目20、energy_queue は maxsize=1 で構築される)。
                putDroppingOldestOnFull(energy_queue, energy)
            except Exception:
                errorLogging()

        try:
            # custom_speech_recognition 3.10.4.3 以降の record_timeout は実時間で測り、
            # 超えると録音中のフレーズを丸ごと捨てる。読み取った音声の長さで区切り、
            # そこまでの音声を返す phrase_time_limit があるので、無制限にして使わない。
            # 同じ値を渡すと 2 つが競争になる。44.1kHz で既定の 3 秒なら、読み取りが
            # 5ms 遅れるだけで 3 秒分の発話が消える。0 は 1 バッファも読めない (issue #113)。
            stop, pause, resume = self.recorder.listen_energy_and_audio_in_background(
                source=self.source,
                callback=audio_callback,
                phrase_time_limit=self.phrase_time_limit,
                callback_energy=energy_callback if energy_queue is not None else None,
                phrase_timeout=1,
                record_timeout=float("inf"),
            )
        except Exception as error:  # noqa: BLE001 - report and preserve setup failure
            self._set_device_error(error)
            raise

        self.stop = _wrapStopperWithBlockingReadUnblock(
            self.source, stop, before_stop=self._stop_requested.set,
            after_stop=lambda: utterance_diagnostics.flush(self.label),
        )
        self.pause = pause
        self.resume = resume


class BaseVadAndAudioRecorder:
    """`BaseEnergyAndAudioRecorder` の VAD 版。フレーズ境界検出を
    `speech_recognition` の energy_threshold/pause_threshold ではなく、
    `VadRecognizerAdapter` (Silero VAD ベースの `VadSegmenter`) に委譲する。

    ストリームの open/close・停止/一時停止の仕組み (`_create_microphone`
    による同一デバイス二重オープン防止、`_wrapStopperWithBlockingReadUnblock`
    によるブロッキング read の強制解除) は `BaseEnergyAndAudioRecorder` と
    完全に同じものをそのまま流用する。差分は「フレーズ区切りの判定方法」
    だけに閉じている。

    VAD は発話開始前のプリロール (pre_speech_pad_frames) と、無音か
    どうかの実際の確率で終端を判定する anchor 方式のヒステリシスを持つ。
    これはエネルギー閾値方式の `phrase_time_limit` (record_timeout 秒で
    単語の途中でも問答無用で打ち切る) が引き起こす「文章の途中で切れる」
    「静かな出だしを取りこぼす」症状への対策として、2026-09-06に
    2度目の実機検証成功実装 (WIP commit 0e4a8d84) を土台に再導入した。

    オプトイン機能 (config.MIC_ENABLE_VAD/SPEAKER_ENABLE_VAD、既定 False) の実装で、既定の
    エネルギー閾値方式の挙動には一切影響しない。
    """

    def __init__(self, source: Any, record_timeout: int, label: str = "vad") -> None:
        self.recorder = Recognizer()
        self.record_timeout = float("inf") if record_timeout <= 0 else record_timeout
        self.stop = None
        self.pause = None
        self.resume = None

        if source is None:
            raise ValueError("audio source can't be None")

        self.source = source
        self.label = label
        self._stop_requested = threading.Event()
        self._device_error_lock = threading.Lock()
        self.device_error_info: Optional[AudioPipelineFailure] = None
        self.device_error_event = threading.Event()
        set_read_error_handler = getattr(source, "set_read_error_handler", None)
        if callable(set_read_error_handler):
            set_read_error_handler(self._on_stream_read_error)
        # max_speech_frames を record_timeout (既定3秒) に連動させていた
        # 時期があったが、実機検証で「長い連続発話ほど内容が丸ごと
        # 抜け落ちる」regressionを引き起こした (2026-09-06)。無音を挟まない
        # 継続発話で record_timeout 秒ごとに強制打ち切りが頻発し、単語の
        # 途中で始まり/終わる不自然な断片を単独でエンジンに送ることになる
        # 結果、境界の不自然さでエンジン側の信頼度フィルタ (Whisper の
        # avg_logprob/no_speech_prob、Google の recognize_google が返す
        # UnknownValueError) に断片ごと棄却されるケースが増えていた。
        # 強制打ち切り (reason="max_duration") された断片は
        # AudioTranscriber 側で単独送信せず蓄積するよう変更した (下記
        # audio_callback の reason 伝播、transcription_transcriber.py 参照)
        # ため、この値は「1回のエンジン呼び出しの粒度」ではなく純粋に
        #「無音が来ない場合の安全弁」の役割になった。PuriPuly-heart の
        # `VadGating.PEER_MAX_SEGMENT_MS` (7秒、docs/ref/PuriPuly-heart 参照)
        # を参考値としてそのまま採用する。
        #
        # 2026-09-07: Google (無料/非公式エンドポイント) 向けにこの値を
        # エンジン別に短縮する対策を一時的に試したが、実機検証で
        # 「呼び出し頻度が上がり過ぎて処理が悪化した」regressionが確認され
        # 撤回した。最終的には AudioTranscriber 側でクリップ前後に無音
        # パディングを付与するだけで無応答/内容欠落が解消したため
        # (transcription_transcriber.py の VAD_PRE_PAD_MS/VAD_POST_PAD_MS
        # 参照)、この値はエンジンを問わず常に固定 (7秒) のままでよい。
        _MAX_SPEECH_DURATION_MS = 7000
        max_speech_frames = max(1, round(_MAX_SPEECH_DURATION_MS / FRAME_DURATION_MS))
        # 通常の speech_start/speech_end は source 別に集約する。
        # hangover 待ちの外れ値は従来の詳細をその場で残す。
        self.vad_adapter = VadRecognizerAdapter(
            native_sample_rate=source.SAMPLE_RATE,
            native_sample_width=source.SAMPLE_WIDTH,
            native_channels=getattr(source, "channels", 1),
            segmenter=VadSegmenter(
                max_speech_frames=max_speech_frames,
                diagnostic_observer=utterance_diagnostics.record,
                diagnostic_label=label,
            ),
        )
        self._error_reporting_segmenter = _ErrorReportingSegmenter(
            self.vad_adapter, self._on_vad_error
        )
        # AudioTranscriber は self.SAMPLE_RATE/SAMPLE_WIDTH/channels を、
        # audio_queue に積まれる生バイト列 (last_sample) の実際の形式として
        # そのまま AudioData の再構成に使う (processMicData/processSpeakerData)。
        # VAD 経由の音声は常に vad_adapter が正規化した 16kHz/16bit/mono に
        # なっているため、ここはネイティブなデバイスのフォーマット
        # (source.SAMPLE_RATE 等) ではなく vad_adapter 側の値を公開する。
        # 混同するとサンプルレートが違う音声として再生/認識され、
        # 認識精度が壊滅的に低下する (実機で確認済みの不具合)。
        self.SAMPLE_RATE = self.vad_adapter.sample_rate
        self.SAMPLE_WIDTH = self.vad_adapter.sample_width
        self.channels = 1

    def _on_stream_read_error(self, error: Exception) -> None:
        if self._stop_requested.is_set():
            return
        with self._device_error_lock:
            if self.device_error_event.is_set():
                return
            code = ErrorCode.AUDIO_READ_ERROR
            self.device_error_info = AudioPipelineFailure(
                error_code=code,
                stage="recording",
                source=self.label,
                message=ERROR_METADATA[code]["message"],
                exception_type=type(error).__name__,
            )
            errorLogging()
            self.device_error_event.set()

    def _on_vad_error(self, error: Exception) -> None:
        if self._stop_requested.is_set():
            return
        with self._device_error_lock:
            if self.device_error_event.is_set():
                return
            self.device_error_info = AudioPipelineFailure(
                error_code=ErrorCode.VAD_INFERENCE_ERROR,
                stage="vad",
                source=self.label,
                message=ERROR_METADATA[ErrorCode.VAD_INFERENCE_ERROR]["message"],
                exception_type=type(error).__name__,
            )
            errorLogging()
            self.device_error_event.set()

    def adjustForNoise(self) -> None:
        # VAD はエネルギー閾値のキャリブレーションを必要としないため no-op。
        # BaseEnergyAndAudioRecorder と同じインターフェースを保つために存在する。
        pass

    def recordIntoQueue(self, audio_queue: Any, energy_queue: Any = None) -> None:
        """listen_with_segmenter_in_background で VAD が確定した発話区間ごとに
        audio を audio_queue に積む。audio_queue には
        (raw_bytes, recorded_at, reason) の3要素タプルを push する
        (BaseEnergyAndAudioRecorder の2要素タプルとは形が異なる点に注意)。

        reason は "silence"/"flush"/"max_duration"/None のいずれか
        (`audio_vad.SpeechSegment.reason`、custom_speech_recognition フォークの
        `AudioData.segment_reason` として伝播されたもの)。
        AudioTranscriber.transcribeAudioQueue は reason=="max_duration"
        (無音を挟まない強制打ち切り) の場合は単独で確定・送信せず蓄積し、
        それ以外 (自然な区切り) の場合だけ即座に確定・送信する
        (2026-09-06、実機で「強制打ち切り断片が単独送信され、エンジン側の
        信頼度フィルタで丸ごと棄却される」regressionが判明したための対策)。
        """

        def audio_callback(_, audio) -> None:
            try:
                raw = audio.get_raw_data()
                reason = getattr(audio, "segment_reason", None)
                item = (raw, datetime.now(), reason)
                # BaseEnergyAndAudioRecorder.audio_callback と同じ理由
                # (フェーズ3項目20)。VAD 経由でも文字起こしが実時間に
                # 追いつけない状況は起こり得るため同じ有界化を適用する。
                dropped = putDroppingOldestOnFull(audio_queue, item)
                utterance_diagnostics.queue_result(self.label, dropped)
            except Exception as error:  # noqa: BLE001 - report callback failure
                self._on_stream_read_error(error)

        def energy_callback(energy) -> None:
            try:
                putDroppingOldestOnFull(energy_queue, energy)
            except Exception:
                errorLogging()

        try:
            stop, pause, resume = self.recorder.listen_with_segmenter_in_background(
                source=self.source,
                callback=audio_callback,
                segmenter=self._error_reporting_segmenter,
                callback_energy=energy_callback if energy_queue is not None else None,
                record_timeout=self.record_timeout,
            )
        except Exception as error:  # noqa: BLE001 - report setup failure
            self._on_stream_read_error(error)
            raise

        self.stop = _wrapStopperWithBlockingReadUnblock(
            self.source, stop, before_stop=self._stop_requested.set,
            after_stop=lambda: utterance_diagnostics.flush(self.label),
        )
        self.pause = pause
        self.resume = resume


class SelectedMicEnergyAndAudioRecorder(BaseEnergyAndAudioRecorder):
    def __init__(
        self,
        device: dict,
        energy_threshold: int,
        dynamic_energy_threshold: bool,
        phrase_time_limit: int,
    ) -> None:
        # PortAudio の WASAPI はステレオ入力を channels=1 で開くと変換せず
        # L,R,L,R... のまま半分だけ返し、文字起こしが壊れる (メーターは動く)。
        # スピーカー側と同じくデバイス本来のチャンネル数で開き、モノラル化は
        # 文字起こし側 (processMicData / VAD の Pcm16MonoNormalizer) で行う。
        # custom_speech_recognition の Microphone は speaker=True のときだけ
        # channels を使って開く (False だと常に 1ch) ため、マイクでも True にする。
        source = _create_microphone(
            {},
            source_kind="mic",
            expected_device=device,
            speaker=True,
            device_index=int(device.get("index", -1)),
            sample_rate=int(device.get("defaultSampleRate", 16000)),
            channels=int(device.get("maxInputChannels", 1)),
        )
        try:
            super().__init__(
                source=source,
                energy_threshold=energy_threshold,
                dynamic_energy_threshold=dynamic_energy_threshold,
                phrase_time_limit=phrase_time_limit,
                label="mic",
            )
        except Exception:
            source.close()
            raise


class SelectedSpeakerEnergyAndAudioRecorder(BaseEnergyAndAudioRecorder):
    def __init__(
        self,
        device: dict,
        energy_threshold: int,
        dynamic_energy_threshold: bool,
        phrase_time_limit: int,
    ) -> None:
        source = _create_microphone(
            {},
            source_kind="speaker",
            expected_device=device,
            speaker=True,
            device_index=int(device.get("index", -1)),
            sample_rate=int(device.get("defaultSampleRate", 16000)),
            channels=int(device.get("maxInputChannels", 1)),
        )
        try:
            super().__init__(
                source=source,
                energy_threshold=energy_threshold,
                dynamic_energy_threshold=dynamic_energy_threshold,
                phrase_time_limit=phrase_time_limit,
                label="speaker",
            )
        except Exception:
            source.close()
            raise


class SelectedMicVadRecorder(BaseVadAndAudioRecorder):
    def __init__(self, device: dict, record_timeout: int = 5) -> None:
        # speaker/channels は SelectedMicEnergyAndAudioRecorder と同じ理由で指定する
        source = _create_microphone(
            {},
            source_kind="mic",
            expected_device=device,
            speaker=True,
            device_index=int(device.get("index", -1)),
            sample_rate=int(device.get("defaultSampleRate", 16000)),
            channels=int(device.get("maxInputChannels", 1)),
        )
        try:
            super().__init__(source=source, record_timeout=record_timeout, label="mic")
        except Exception:
            source.close()
            raise


class SelectedSpeakerVadRecorder(BaseVadAndAudioRecorder):
    def __init__(self, device: dict, record_timeout: int = 5) -> None:
        source = _create_microphone(
            {},
            source_kind="speaker",
            expected_device=device,
            speaker=True,
            device_index=int(device.get("index", -1)),
            sample_rate=int(device.get("defaultSampleRate", 16000)),
            channels=int(device.get("maxInputChannels", 1)),
        )
        try:
            super().__init__(source=source, record_timeout=record_timeout, label="speaker")
        except Exception:
            source.close()
            raise
