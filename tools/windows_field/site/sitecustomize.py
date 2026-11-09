"""Test-only startup hook for src-python/mainloop.py.

- Installs the fake SteamVR from tools/fake_vr_site.
- Replaces the audio device with WAV playback: the real microphone is never opened.
  Everything after the device (phrase detection, Whisper, translation, OSC) is real.
Drop <VOX_FAKE_AUDIO_DIR>/play-mic.wav or play-speaker.wav (16 kHz mono 16-bit) to "speak".
"""
import os
import sys


def _install_audio():
    import threading
    import time
    import wave
    from pathlib import Path
    from types import SimpleNamespace

    directory = Path(os.environ["VOX_FAKE_AUDIO_DIR"])
    opened = directory / "opened.log"

    class Stream:
        def __init__(self, source):
            self.source = source
            self.pyaudio_stream = SimpleNamespace(
                get_read_available=lambda: source.CHUNK, is_stopped=lambda: source.closed,
                stop_stream=lambda: setattr(source, "closed", True))

        def read(self, frames):
            source = self.source
            if source.closed:
                raise OSError("stream closed")
            # Paced like a device: audio piles up on its own clock, so a late reader catches up.
            source.position += frames
            delay = source.started + source.position / source.SAMPLE_RATE - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            size = frames * source.SAMPLE_WIDTH
            if not source.pcm:
                wav = directory / f"play-{source.kind}.wav"
                if wav.exists():
                    try:
                        with wave.open(str(wav), "rb") as reader:
                            assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (16000, 1, 2)
                            source.pcm = reader.readframes(reader.getnframes())
                        wav.replace(directory / f"played-{source.kind}-{time.time_ns()}.wav")
                    except PermissionError:  # the test is still moving the file in; next read
                        source.pcm = b""
                    else:
                        with opened.open("a", encoding="utf-8") as log:
                            log.write(f"play {source.kind} source={id(source)} bytes={len(source.pcm)} t={time.monotonic():.2f}\n")
            chunk, source.pcm = source.pcm[:size], source.pcm[size:]
            return chunk + b"\0" * (size - len(chunk))

        def close(self):
            self.source.closed = True

    from speech_recognition import AudioSource, Recognizer, WaitTimeoutError

    real_listen = Recognizer.listen_energy_and_audio

    def listen_logged(self, source, *args, **kwargs):
        # The two WaitTimeoutError messages tell "no speech yet" from "phrase thrown away".
        began = time.monotonic()
        try:
            return real_listen(self, source, *args, **kwargs)
        except WaitTimeoutError as error:
            if "Can't read" in str(error):
                with opened.open("a", encoding="utf-8") as log:
                    log.write(f"PHRASE DISCARDED by record_timeout after {time.monotonic() - began:.3f}s "
                              f"left={len(source.pcm)} t={time.monotonic():.2f}\n")
            raise

    Recognizer.listen_energy_and_audio = listen_logged

    class WavSource(AudioSource):  # the recognizer asserts this type
        SAMPLE_RATE, SAMPLE_WIDTH, CHUNK, channels = 16000, 2, 1024, 1

        def __init__(self, kind):  # AudioSource.__init__ only raises
            self.kind, self.pcm, self.closed, self.stream = kind, b"", False, None
            self.started, self.position = time.perf_counter(), 0
            self.audio = SimpleNamespace(terminate=lambda: None)
            self.opened_device = None

        def __enter__(self):
            self.closed = False
            self.stream = Stream(self)
            return self

        def __exit__(self, *args):
            with opened.open("a", encoding="utf-8") as log:
                log.write(f"close {self.kind} source={id(self)} left={len(self.pcm)} t={time.monotonic():.2f}\n")
            self.closed = True
            self.stream = None

    def open_wav(fallback_kwargs, *, cancelled=None, expected_device=None, **device_kwargs):
        # The recorder passes speaker=True for microphones too; only the device tells them apart.
        device = expected_device or {}
        kind = "speaker" if device.get("isLoopbackDevice") or "Loopback" in str(device.get("name")) else "mic"
        source = WavSource(kind).__enter__()
        with opened.open("a", encoding="utf-8") as log:
            log.write(f"{kind} -> wav, device={device_kwargs.get('device_index')} source={id(source)} t={time.monotonic():.2f}\n")
        source.opened_device = expected_device
        return source

    class NoRealMicrophone:
        def __init__(self, *args, **kwargs):
            with opened.open("a", encoding="utf-8") as log:
                log.write("REAL MICROPHONE REQUESTED\n")
            raise OSError("real microphone blocked by the test")

    def patch():
        while True:
            module = sys.modules.get("models.transcription.transcription_recorder")
            if module is not None and hasattr(module, "_open_with_fallback"):
                module._open_with_fallback = open_wav
                module.Microphone = NoRealMicrophone
                with opened.open("a", encoding="utf-8") as log:
                    log.write("audio device replaced\n")
                return
            time.sleep(0.005)

    threading.Thread(target=patch, name="fake-audio-patch", daemon=True).start()


def _install_ocr():
    """The screen capture becomes a PNG; detection, OCR and delivery stay real."""
    import threading
    import time
    from pathlib import Path

    frame = Path(os.environ["VOX_FAKE_OCR_FRAME"])

    class FrameCapture:
        backend, source = "hwnd", "window"

        def __init__(self, window_title="VRChat"):
            pass

        def get(self):
            import cv2
            return cv2.imread(str(frame)) if frame.exists() else None

        def close(self):
            pass

    def patch():
        while True:
            module = sys.modules.get("models.ocr.ocr_pipeline")
            if module is not None and hasattr(module, "OcrPipeline"):
                module.OcrCapture = FrameCapture
                module.probeCapture = lambda title: module.CAPTURE_OK
                break
            time.sleep(0.01)
        # Drawn bubbles score below the 0.7 tuned on real frames. Test only.
        confidence = os.environ.get("VOX_FAKE_DETECTOR_CONFIDENCE")
        while confidence:
            detector = sys.modules.get("models.ocr.ocr_chatbox_detector")
            if detector is not None and hasattr(detector, "ChatboxDetector"):
                detector.ChatboxDetector.__init__.__defaults__ = (float(confidence),)
                return
            time.sleep(0.01)

    threading.Thread(target=patch, name="fake-ocr-patch", daemon=True).start()


def _install_router():
    import threading
    import time

    def patch():
        while True:
            module = sys.modules.get('models.voice_conversion.isolated')
            if module is not None and hasattr(module, 'launch_owned'):
                real = module.launch_owned

                def launch(args, **kwargs):
                    env = kwargs['env']
                    env['PYTHONPATH'] = os.environ['VOX_ROUTER_SITE'] + os.pathsep + env['PYTHONPATH']
                    return real(args, **kwargs)

                module.launch_owned = launch
                break
            time.sleep(.002)
        # Forwarding runs in the sidecar itself, so read its 'microphone' the same way.
        while True:
            capture = sys.modules.get('models.transcription.capture_windows')
            if capture is not None and hasattr(capture, 'capture_device'):
                devices = sys.modules['models.audio_routing.devices_windows']
                target = os.environ['VOX_MIC_AS_LOOPBACK']
                real_device = capture.capture_device

                def capture_device(pa, audio, endpoint, source):
                    if source == 'mic':
                        for info in devices._endpoint_rows(pa, audio, 'speaker'):
                            if devices._identity(pa, info) == target:
                                return pa.get_wasapi_loopback_analogue_by_dict(info)
                        raise LookupError('endpoint_missing')  # never fall through to a real microphone
                    return real_device(pa, audio, endpoint, source)

                capture.capture_device = capture_device
                return
            time.sleep(.002)

    threading.Thread(target=patch, name='fake-router-patch', daemon=True).start()


def _install_speech_device():
    """Test only: start speech.cpp on a named device, which the app's settings cannot express yet."""
    import threading
    import time

    device = os.environ["VOX_SPEECH_DEVICE"]

    def patch():
        while True:
            module = sys.modules.get("models.speech_server.runtime")
            if module is not None and hasattr(module, "launch_owned"):
                real = module.launch_owned

                def launch(args, **kwargs):
                    args = list(args)
                    if "--device" in args:
                        args[args.index("--device") + 1] = device
                    cache = os.environ.get("VOX_SHADER_CACHE")
                    if cache:  # this speech.exe only: an empty driver cache, as on a first run
                        from pathlib import Path
                        Path(cache).mkdir(parents=True, exist_ok=True)
                        kwargs["env"] = dict(kwargs["env"], __GL_SHADER_DISK_CACHE="1",
                                             __GL_SHADER_DISK_CACHE_PATH=cache, LOCALAPPDATA=cache)
                    return real(args, **kwargs)

                module.launch_owned = launch
                return
            time.sleep(0.002)

    threading.Thread(target=patch, name="speech-device-patch", daemon=True).start()


def _install_mic_guard():
    """Real devices, but only loopbacks: any capture of a microphone raises and is logged."""
    import threading
    import time
    from pathlib import Path

    log = Path(os.environ["VOX_BLOCK_MIC"])

    def refuse(what):
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"MICROPHONE REFUSED {what} t={time.monotonic():.2f}\n")
        raise OSError("microphone blocked by the soak test")

    def patch_classic():
        while True:
            module = sys.modules.get("models.transcription.transcription_recorder")
            if module is not None and hasattr(module, "_open_with_fallback"):
                real = module._open_with_fallback

                def guarded(fallback_kwargs, *args, expected_device=None, **kwargs):
                    device = expected_device or {}
                    if not (device.get("isLoopbackDevice") or "Loopback" in str(device.get("name"))):
                        refuse(f"classic {device.get('name')!r}")
                    return real(fallback_kwargs, *args, expected_device=expected_device, **kwargs)

                module._open_with_fallback = guarded
                return
            time.sleep(0.005)

    def patch_realtime():
        while True:
            module = sys.modules.get("models.transcription.capture_windows")
            if module is not None and hasattr(module, "capture_device"):
                real = module.capture_device

                def guarded(pa, audio, endpoint, source):
                    if source == "mic":
                        refuse(f"realtime {endpoint!r}")
                    return real(pa, audio, endpoint, source)

                module.capture_device = guarded
                return
            time.sleep(0.005)

    threading.Thread(target=patch_classic, name="mic-guard-classic", daemon=True).start()
    # With VOX_MIC_AS_LOOPBACK, the router patch already turns every 'mic' into a loopback.
    if not os.environ.get("VOX_MIC_AS_LOOPBACK"):
        threading.Thread(target=patch_realtime, name="mic-guard-realtime", daemon=True).start()


def _install_capture_probe():
    """Test only: write down why a realtime capture stopped. The app reduces every reason to one code."""
    import threading
    import time
    import traceback
    from pathlib import Path

    log = Path(os.environ["VOX_CAPTURE_PROBE"])

    def write(line):
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"t={time.monotonic():.3f} {line}\n")

    def patch():
        while True:
            module = sys.modules.get("models.transcription.realtime_audio")
            if module is not None and hasattr(module, "RealtimeIngress"):
                real_close = module.RealtimeIngress._close_locked

                def close_locked(self, reason):
                    write(f"ingress close reason={reason} queued_frames={len(self._queue)} "
                          f"queued_samples={self._samples_queued} first_reason={self._reason}")
                    return real_close(self, reason)

                module.RealtimeIngress._close_locked = close_locked
                break
            time.sleep(0.002)
        while True:
            module = sys.modules.get("models.transcription.capture_windows")
            if module is not None and hasattr(module, "WindowsCapture"):
                real_init = module.WindowsCapture.__init__
                real_pump = module.WindowsCapture._pump

                def init(self, endpoint, source, on_audio, on_error):
                    def logged(code):
                        write(f"capture on_error code={code} source={source}")
                        return on_error(code)
                    real_init(self, endpoint, source, on_audio, logged)

                def pump(self, *args, **kwargs):
                    try:
                        return real_pump(self, *args, **kwargs)
                    except Exception as error:
                        write(f"pump raised {error!r}\n{traceback.format_exc()}")
                        raise

                module.WindowsCapture.__init__ = init
                module.WindowsCapture._pump = pump
                write("capture probe installed")
                return
            time.sleep(0.002)

    def patch_client():
        while True:
            module = sys.modules.get("models.transcription.speechcpp_realtime")
            if module is not None and hasattr(module, "SpeechCppRealtime"):
                pending = os.environ.get("VOX_PENDING_TIMEOUT")
                if pending:
                    module.PENDING_TIMEOUT = float(pending)
                real_shutdown = module.SpeechCppRealtime._shutdown

                async def shutdown(self, reason, failed):
                    write(f"client shutdown reason={reason} failed={failed} state={self.state} "
                          f"pending_timeout={module.PENDING_TIMEOUT}")
                    return await real_shutdown(self, reason, failed)

                module.SpeechCppRealtime._shutdown = shutdown
                real_accept = module.TranscriptEvents.accept

                def accept(self, event):
                    updates = real_accept(self, event)
                    for update in updates:
                        if update.is_final:
                            write(f"final item={update.item_id[:8]}")
                    if event.get("type") == "input_audio_buffer.speech_started":
                        write("speech_started")
                    return updates

                module.TranscriptEvents.accept = accept
                return
            time.sleep(0.002)

    threading.Thread(target=patch, name="capture-probe", daemon=True).start()
    threading.Thread(target=patch_client, name="client-probe", daemon=True).start()


def _activate():
    script = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if script != "mainloop.py":
        return
    if os.environ.get("VOX_FAKE_VR_OUT"):
        import importlib.util
        from pathlib import Path

        site = Path(os.environ["VOX_REPO"]) / "tools" / "fake_vr_site"
        sys.path.insert(0, str(site))
        # Not runpy: it replaces sys.argv[0], which the hook checks for mainloop.py.
        spec = importlib.util.spec_from_file_location("vox_fake_vr_site", site / "sitecustomize.py")
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    if os.environ.get("VOX_FAKE_AUDIO_DIR"):
        _install_audio()
    if os.environ.get("VOX_FAKE_OCR_FRAME"):
        _install_ocr()
    if os.environ.get("VOX_ROUTER_SITE"):
        _install_router()
    if os.environ.get("VOX_BLOCK_MIC"):
        _install_mic_guard()
    if os.environ.get("VOX_SPEECH_DEVICE"):
        _install_speech_device()
    if os.environ.get("VOX_CAPTURE_PROBE"):
        _install_capture_probe()


try:
    _activate()
except Exception:  # noqa: BLE001
    import traceback

    traceback.print_exc()
