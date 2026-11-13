"""Run the native GUI acceptance tests against a built app, with the models and VRChat they need.

    python tools/native_acceptance.py --appimage path/to/VRCT-VOX.AppImage
    python tools/native_acceptance.py --appimage ... --fetch-models --vrchat
    python tools/native_acceptance.py --app src-tauri/target/debug/vrct-vox --only vr-ui

These tests are not part of `dev.py check`: they open the real app on this desktop. Audio runs in
private PipeWire graphs, so the PC's microphone and speakers are not touched. Each group runs in
its own pytest process under tools/display_power_guard.py (a sleeping display stops drawing).

Models come from the product's catalog (src-python/models/model_downloads/catalog.py): pinned
revision, size and SHA-256, fetched with the product's own downloader into a cache of their own
(~/.cache/vrct-vox-acceptance). Nothing is downloaded unless --fetch-models is given; without it
a group whose models are missing is reported as skipped, with what it lacks. The speech the ASR
tests listen to is synthesized with the product's own TTS, so no recording of a person is needed.

--vrchat starts the chatbox lab's two local VRChat clients (a hidden local instance), runs the
round trip, and stops the clients it started. --downloads runs the real 336 MB model download.
--fetch-runtimes sets up the RVC and Seed-VC runtimes with the product's installer. --vrchat-voice
runs the two tests that use the PC's real audio route; tools/vrchat_voice_host.py prepares the PC
for them and restores it afterwards.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".cache/vrct-vox-acceptance"
# What a group needs -> the catalog entry that provides it.
MODELS = {"vad": "silero-vad-v62", "asr": "qwen3-asr-06b-q8", "qwen_tts": "qwen3-06b-q8", "irodori": "irodori-v41-q8",
          "rvc_model": "rvc-saisho", "rvc_index": "rvc-saisho"}
FILES = {"rvc_model": "model.pth", "rvc_index": "model.index"}  # everything else is the entry's one GGUF
# The voice conversion runtimes the product can set up (models/voice_conversion/runtime_setup.py).
RUNTIMES = {"rvc_runtime": "rvc", "seed_runtime": "seed-vc"}
# Qwen3-ASR names each utterance's language; game audio captions need that ("auto").
SENTENCES = ["今日はいい天気ですね", "駅の前で会いましょう"]
PLATFORM = "tests/platform/"


# What a group can use when it is there, without needing it: with these the spoken translation
# test also runs its two RVC variants.
OPTIONAL = {"asr": ({"VRCT_TEST_NATIVE_RVC_UI": "1"}, ["rvc_runtime", "rvc_model", "rvc_index"])}
# Environment variable -> the asset whose path it carries.
PATHS = {"VRCT_SPEECH_BINARY": "speech", "VRCT_TEST_SPEECH_BINARY": "speech", "VRCT_SPEECH_ASR_MODEL": "asr",
         "VRCT_SPEECH_VAD_MODEL": "vad", "VRCT_QWEN_TTS_MODEL": "qwen_tts", "VRCT_TEST_SPEECH_MODEL": "irodori",
         "VRCT_SPEECH_ASR_INPUT": "asr_input", "VRCT_RVC_RUNTIME": "rvc_runtime", "VRCT_RVC_MODEL": "rvc_model",
         "VRCT_RVC_INDEX": "rvc_index", "VRCT_RVC_INPUT": "voice_input", "VRCT_SEED_POC": "seed_runtime",
         "VRCT_SEED_REFERENCE": "voice_input", "VRCT_SEED_INPUT": "voice_input"}


def groups():
    """name -> (tests, extra environment, needs, kind). kind: "any", "packaged" or "development"."""
    on = "1"
    return {
        "appimage": (["test_appimage.py"], {"VRCT_TEST_APPIMAGE_FUSE": on, "VRCT_TEST_NATIVE_ROUTE": on}, [], "packaged"),
        "ui": (["test_native_ui.py", "test_native_tts_settings.py"], {"VRCT_TEST_NATIVE_ROUTE": on}, [], "any"),
        "voice": (["test_native_tts_independence.py", "test_native_direct_voice.py", "test_native_voice.py",
                   "test_native_managed_microphone.py", "test_native_rvc_model_free.py", "test_native_backend.py"],
                  {"VRCT_TEST_NATIVE_TTS_INDEPENDENCE": on, "VRCT_TEST_NATIVE_DIRECT": on, "VRCT_TEST_NATIVE_VOICE": on,
                   "VRCT_TEST_AUTO_MIC": on, "VRCT_TEST_RVC_ROUTE": on, "VRCT_TEST_NATIVE": on}, [], "any"),
        "tts-model": (["test_native_low_latency_controls.py", "test_native_voice_measurement.py"],
                      {"VRCT_TEST_NATIVE_LOW_LATENCY_CONTROLS": on, "VRCT_TEST_NATIVE_MEASUREMENT": on,
                       "VRCT_TEST_MEASUREMENT_TRIALS": "5"}, ["irodori", "speech"], "any"),
        "asr": (["test_native_realtime.py", "test_native_speech_servers.py", "test_native_spoken_translation.py"],
                {"VRCT_TEST_OWNED_SPEECH": on}, ["asr", "vad", "qwen_tts", "speech", "asr_input"], "any"),
        "downloads": (["test_native_model_downloads.py"], {"VRCT_TEST_NATIVE_MODEL_DOWNLOADS": on}, ["--downloads"], "any"),
        "rvc": (["test_native_rvc_ui.py"], {"VRCT_TEST_NATIVE_RVC_UI": on},
                ["rvc_runtime", "rvc_model", "rvc_index", "voice_input"], "any"),
        "seed-vc": (["test_native_direct_vc.py"], {"VRCT_TEST_NATIVE_DIRECT_VC": on}, ["seed_runtime", "voice_input"], "any"),
        "vrchat": (["test_native_vrchat_roundtrip.py"], {"VRCT_TEST_NATIVE_VRCHAT_ROUNDTRIP": on}, ["--vrchat", "ocr"], "any"),
        # On the PC's real audio route; see tools/vrchat_voice_host.py for what it changes and restores.
        "vrchat-voice": (["test_native_chatbox.py", "test_native_vrchat.py"],
                         {"VRCT_TEST_NATIVE_CHATBOX": on, "VRCT_TEST_NATIVE_VRCHAT": on},
                         ["--vrchat-voice", "irodori", "speech"], "any"),
        "vr-ui": (["test_native_vr_ui.py"], {}, [], "development"),
    }


# A copy the user already downloaded through the app serves as well (read only).
INSTALLED = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "vrct-vox/downloaded_models"
ALSO = {"irodori": ["irodori-v41-f16"]}


def model_path(cache, need):
    for root, model in [(cache / "models", MODELS[need]), *((INSTALLED, other) for other in [MODELS[need], *ALSO.get(need, [])])]:
        found = sorted((root / model).glob("*/" + FILES.get(need, "*.gguf")))
        if found:
            return found[0]
    return None


def runtime_path(cache, need):
    folder = cache / "vc_runtimes" / RUNTIMES[need]
    return folder if (folder / "receipt.json").is_file() else None


def assets(args):
    """need -> path or flag for everything that exists now."""
    have = {need: model_path(args.cache, need) for need in MODELS}
    have.update({need: runtime_path(args.cache, need) for need in RUNTIMES})
    speech = Path(args.speech_binary)
    have["speech"] = speech if speech.is_file() else None
    recording = args.cache / "asr-input-ja.wav"
    have["asr_input"] = have["voice_input"] = recording if recording.is_file() else None
    ocr = Path(os.environ.get("VRCT_TEST_OCR_MODELS", Path.home() / ".cache/vrct-vox-chatbox-lab/models"))
    have["ocr"] = ocr if ocr.is_dir() else None
    have["--downloads"], have["--vrchat"] = args.downloads or None, args.vrchat or None
    have["--vrchat-voice"] = args.vrchat_voice or None
    return {need: value for need, value in have.items() if value}


def plan(args, have):
    """[(name, tests, environment, skip reason or None)] for the chosen build. Pure: it starts nothing."""
    packaged = bool(args.appimage)
    rows = []
    for name, (tests, extra, needs, kind) in groups().items():
        if args.only and name not in args.only:
            continue
        missing = [need for need in needs if need not in have]
        reason = None
        if kind == "packaged" and not packaged:
            reason = "needs --appimage"
        elif kind == "development" and packaged:
            reason = "needs --app (a development build; the fake SteamVR is a Python module)"
        elif missing:
            reason = "missing: " + ", ".join(dict.fromkeys(MODELS.get(need) or RUNTIMES.get(need, need) for need in missing))
        env = {"VRCT_TEST_NATIVE_GUI": "1", "VRCT_TEST_DRIVER": str(args.driver), **extra}
        if name == "appimage":
            env["VRCT_TEST_APPIMAGE"] = str(args.appimage)
        else:
            env["VRCT_TEST_APP"] = str(args.copy if packaged else args.app)
            if packaged:
                env.update(VRCT_TEST_APPIMAGE="1", APPIMAGE_EXTRACT_AND_RUN="1")
        extra_env, extra_needs = OPTIONAL.get(name, ({}, []))
        if all(need in have for need in extra_needs):
            env.update(extra_env)
            needs = [*needs, *extra_needs]
        env.update({variable: str(have[need]) for variable, need in PATHS.items() if need in needs and need in have})
        rows.append((name, [PLATFORM + test for test in tests], env, reason))
    return rows


def fetch_models(args):
    """Download the catalog models that are missing, with the product's own verified downloader."""
    sys.path.insert(0, str(ROOT / "src-python"))
    from models.model_downloads.manager import Downloads

    manager = Downloads(args.cache / "models")
    try:
        for need, model in MODELS.items():
            if model_path(args.cache, need):
                continue
            entry = manager.entries[model]
            total = sum(artifact.size for artifact in entry.artifacts)
            print(f"fetching {model}: {entry.repo}@{entry.revision[:10]}, {entry.license}, {total / 1e6:.0f} MB", flush=True)
            manager.start({"id": model, "consent": True, "catalog_version": manager.catalog_version})
            while True:
                job = manager.state()["jobs"].get(model, {})
                if job.get("phase") in ("ready", "failed", "cancelled"):
                    break
                time.sleep(1)
            if job.get("phase") != "ready":
                raise SystemExit(f"could not fetch {model}: {job.get('error_code') or job.get('phase')}")
    finally:
        manager.close(timeout=10)


def fetch_runtimes(args):
    """Set up the RVC and Seed-VC runtimes with the product's own consent-gated installer (about 11 GB)."""
    sys.path.insert(0, str(ROOT / "src-python"))
    from models.voice_conversion.runtime_setup import ACTIVE, RuntimeSetup

    setup = RuntimeSetup(args.cache / "vc_runtimes")
    try:
        for row in setup.catalog()["runtimes"]:
            if row["id"] in setup.state()["installed"]:
                continue
            print(f"setting up {row['id']}: {row['license']}, download {row['download_bytes'] / 1e9:.1f} GB, "
                  f"disk {row['disk_bytes'] / 1e9:.1f} GB", flush=True)
            setup.start({"id": row["id"], "consent": True, "version": row["version"]})
            while setup.state()["jobs"].get(row["id"], {}).get("phase") in ACTIVE:
                time.sleep(2)
            if row["id"] not in setup.state()["installed"]:
                raise SystemExit(f"could not set up {row['id']}: {setup.state()['jobs'].get(row['id'])}")
    finally:
        setup.close(timeout=20)


def synthesize_recording(args, have):
    """Two short sentences with a pause, 48 kHz mono 16-bit, spoken by the product's own Japanese TTS."""
    sys.path[:0] = [str(ROOT), str(ROOT / "src-python")]
    from types import SimpleNamespace

    from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS, SpeechError
    from tools.live_tts_acceptance import SpeechServer

    out = args.cache / "asr-input-ja.wav"
    server = SpeechServer(SimpleNamespace(model=have["irodori"], output=args.cache, speech_binary=str(have["speech"]),
                                          device="Vulkan0", seed=42))
    server.start()
    try:
        pcm = b""
        for index, text in enumerate(SENTENCES):
            for attempt in range(3):  # the first request can outlast the client's timeout while the model warms up
                try:
                    frames = list(SpeechCppTTS(server.url).synthesize_stream(text, "none", "ja", CancelToken()))
                    break
                except SpeechError:
                    if attempt == 2:
                        raise
            assert frames and all(frame.sample_rate == 48000 and frame.channels == 1 for frame in frames)
            pcm += b"".join(frame.pcm for frame in frames) + (b"\0\0" * 60000 if index + 1 < len(SENTENCES) else b"")
    finally:
        server.stop()
    with wave.open(str(out), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(48000)
        recording.writeframes(pcm)
    print(f"synthesized {out} ({len(pcm) / 96000:.1f} s)", flush=True)


def counts(report):
    """(passed, failed, skipped) from a JUnit report, or None if pytest did not get that far."""
    try:
        suite = ET.parse(report).getroot()
    except (OSError, ET.ParseError):
        return None
    suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
    tests, failed, skipped = (int(suite.get(key, 0)) for key in ("tests", "failures", "skipped"))
    failed += int(suite.get("errors", 0))
    return tests - failed - skipped, failed, skipped


def run_group(args, name, tests, env):
    out = args.output / name
    out.mkdir(parents=True, exist_ok=True)
    report = out / "junit.xml"
    command = ["python3", str(ROOT / "tools/display_power_guard.py"), "--", str(args.python), "-m", "pytest",
               "-c", "tests/voice/pytest.ini", *tests, "-q", "-rs", "--tb=short", f"--basetemp={out / 'tmp'}",
               f"--junitxml={report}"]
    with (out / "pytest.log").open("w") as log:
        code = subprocess.run(command, cwd=ROOT, env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT,
                              timeout=args.timeout).returncode
    return code, counts(report)


class VRChatVoice:
    """The PC's real audio route with VRChat on it, prepared before the group and restored after it."""

    def __enter__(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import vrchat_voice_host as host

        self.host = host
        try:
            self.env = host.prepare()
            host.open_mic_test()
        except BaseException:
            host.restore()
            raise
        return self

    def __exit__(self, *exc):
        self.host.restore()


class VRChat:
    """The chatbox lab's two local clients, started here unless they already run."""

    def __init__(self, args):
        self.args, self.started = args, False

    def __enter__(self):
        sys.path.insert(0, str(ROOT / "tests/platform"))
        import native_vrchat_lab as lab

        if not lab.ready():
            subprocess.run([sys.executable, str(ROOT / "tools/chatbox_lab/launch_clients.py"), "--clients", "2"],
                           cwd=ROOT, check=True, timeout=300)
            self.started = True
            deadline = time.monotonic() + 240
            while not lab.ready():
                if time.monotonic() > deadline:
                    raise SystemExit("the VRChat lab clients did not show their windows in time")
                time.sleep(3)
            time.sleep(20)  # both must have finished joining the world before a bubble can be seen
        return self

    def __exit__(self, *exc):
        if self.started:
            subprocess.run([sys.executable, str(ROOT / "tools/chatbox_lab/launch_clients.py"), "--stop"], cwd=ROOT, timeout=120)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    build = parser.add_mutually_exclusive_group(required=True)
    build.add_argument("--appimage", type=Path, help="a candidate or published AppImage")
    build.add_argument("--app", type=Path, help="a development build (src-tauri/target/debug/vrct-vox)")
    parser.add_argument("--only", action="append", choices=sorted(groups()), help="run only this group (repeatable)")
    parser.add_argument("--fetch-models", action="store_true",
                        help="download missing catalog models (about 3.6 GB in all) into the cache")
    parser.add_argument("--vrchat", action="store_true", help="start two local VRChat clients and run the round trip")
    parser.add_argument("--downloads", action="store_true", help="run the real 336 MB model download test")
    parser.add_argument("--fetch-runtimes", action="store_true",
                        help="set up the RVC and Seed-VC runtimes (about 11 GB of downloads, 17 GB on disk) into the cache")
    parser.add_argument("--vrchat-voice", action="store_true",
                        help="run the two tests on the PC's real audio route (see tools/vrchat_voice_host.py)")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=ROOT / "build/native-acceptance")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv_linux/bin/python")
    parser.add_argument("--driver", type=Path, default=Path(os.environ.get("VRCT_TEST_DRIVER", ROOT / "tmp/tauri-driver/bin/tauri-driver")))
    parser.add_argument("--speech-binary", default=str(ROOT / "build/linux/resources/build/speechcpp/speech"))
    parser.add_argument("--timeout", type=int, default=1800, help="seconds for one group")
    args = parser.parse_args(argv)
    build = (args.appimage or args.app).resolve()
    if not build.is_file():
        parser.error(f"not found: {build}")
    args.appimage, args.app = (build, None) if args.appimage else (None, build)
    args.cache.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(args.output, ignore_errors=True)
    args.output.mkdir(parents=True)
    args.copy = None
    if args.appimage:
        # The other groups run the image directly; keep the candidate itself read-only and untouched.
        args.copy = args.output / "candidate.AppImage"
        shutil.copyfile(args.appimage, args.copy)
        args.copy.chmod(0o755)
    if args.fetch_models:
        fetch_models(args)
    if args.fetch_runtimes:
        fetch_runtimes(args)
    have = assets(args)
    if "asr_input" not in have and {"irodori", "speech"} <= set(have):
        synthesize_recording(args, have)
        have = assets(args)

    results, failed = [], False
    rows = plan(args, have)
    lab = VRChat(args) if any(name == "vrchat" and not reason for name, _, _, reason in rows) else None
    for name, tests, env, reason in rows:
        if reason:
            results.append({"group": name, "result": "skipped", "reason": reason})
            print(f"{name:10} skipped  {reason}", flush=True)
            continue
        started = time.monotonic()
        try:
            if name == "vrchat":
                with lab:
                    code, tally = run_group(args, name, tests, env)
            elif name == "vrchat-voice":
                with VRChatVoice() as voice:
                    code, tally = run_group(args, name, tests, {**env, **voice.env})
            else:
                code, tally = run_group(args, name, tests, env)
        except subprocess.TimeoutExpired:
            code, tally = 1, None
        row = {"group": name, "result": "passed" if code == 0 else "failed", "seconds": round(time.monotonic() - started),
               "log": str(args.output / name / "pytest.log")}
        if tally:
            row.update(passed=tally[0], failed=tally[1], skipped=tally[2])
        failed |= code != 0
        results.append(row)
        detail = f"{tally[0]} passed, {tally[1]} failed, {tally[2]} skipped" if tally else "no report (see the log)"
        print(f"{name:10} {row['result']:8} {detail}  {row['seconds']} s", flush=True)
    summary = {"build": str(build), "packaged": bool(args.appimage), "groups": results}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"report: {args.output / 'summary.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
