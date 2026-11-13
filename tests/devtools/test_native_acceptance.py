"""tools/native_acceptance.py decides what to run from the build and the models at hand."""
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import native_acceptance as subject  # noqa: E402


def args(**changes):
    values = dict(appimage=Path("/candidates/app.AppImage"), app=None, copy=Path("/out/candidate.AppImage"),
                  driver=Path("/driver"), only=None)
    values.update(changes)
    return SimpleNamespace(**values)


def by_name(rows):
    return {name: (tests, env, reason) for name, tests, env, reason in rows}


ALL = {"vad": "/m/vad.gguf", "asr": "/m/asr.gguf", "qwen_tts": "/m/qwen.gguf", "irodori": "/m/irodori.gguf",
       "speech": "/bin/speech", "asr_input": "/m/input.wav", "voice_input": "/m/input.wav", "ocr": "/m/ocr",
       "rvc_runtime": "/r/rvc", "rvc_model": "/m/model.pth", "rvc_index": "/m/model.index", "seed_runtime": "/r/seed-vc",
       "--vrchat": True, "--downloads": True, "--vrchat-voice": True}


def test_nothing_downloads_or_starts_vrchat_unless_asked():
    """Without models or flags only the model-free groups run; the rest say what they lack."""
    rows = by_name(subject.plan(args(), {}))
    assert [name for name, row in rows.items() if row[2] is None] == ["appimage", "ui", "voice"]
    assert rows["asr"][2] == "missing: qwen3-asr-06b-q8, silero-vad-v62, qwen3-06b-q8, speech, asr_input"
    assert rows["tts-model"][2] == "missing: irodori-v41-q8, speech"
    assert rows["downloads"][2] == "missing: --downloads"
    assert rows["vrchat"][2] == "missing: --vrchat, ocr"
    # The runtimes and the PC's real audio route are opt-in too.
    assert rows["rvc"][2] == "missing: rvc, rvc-saisho, voice_input"
    assert rows["seed-vc"][2] == "missing: seed-vc, voice_input"
    assert rows["vrchat-voice"][2] == "missing: --vrchat-voice, irodori-v41-q8, speech"


def test_a_packaged_build_runs_the_image_itself_and_skips_the_fake_vr():
    rows = by_name(subject.plan(args(), ALL))
    assert rows["appimage"][1]["VRCT_TEST_APPIMAGE"] == "/candidates/app.AppImage"
    assert "VRCT_TEST_APP" not in rows["appimage"][1]
    for name in ("ui", "voice", "asr", "vrchat"):
        env = rows[name][1]
        assert (env["VRCT_TEST_APP"], env["VRCT_TEST_APPIMAGE"], env["APPIMAGE_EXTRACT_AND_RUN"]) == ("/out/candidate.AppImage", "1", "1")
    assert rows["vr-ui"][2].startswith("needs --app")
    assert all(reason is None for name, (_, _, reason) in rows.items() if name != "vr-ui")


def test_a_development_build_is_not_treated_as_an_image():
    rows = by_name(subject.plan(args(appimage=None, app=Path("/build/vrct-vox"), copy=None), ALL))
    assert rows["appimage"][2] == "needs --appimage" and rows["vr-ui"][2] is None
    env = rows["asr"][1]
    assert env["VRCT_TEST_APP"] == "/build/vrct-vox"
    assert "VRCT_TEST_APPIMAGE" not in env and "APPIMAGE_EXTRACT_AND_RUN" not in env


def test_each_group_gets_only_the_models_it_names():
    rows = by_name(subject.plan(args(), ALL))
    asr = rows["asr"][1]
    assert (asr["VRCT_SPEECH_ASR_MODEL"], asr["VRCT_SPEECH_VAD_MODEL"], asr["VRCT_QWEN_TTS_MODEL"], asr["VRCT_SPEECH_ASR_INPUT"],
            asr["VRCT_SPEECH_BINARY"]) == ("/m/asr.gguf", "/m/vad.gguf", "/m/qwen.gguf", "/m/input.wav", "/bin/speech")
    assert "VRCT_TEST_SPEECH_MODEL" not in asr
    tts = rows["tts-model"][1]
    assert tts["VRCT_TEST_SPEECH_MODEL"] == "/m/irodori.gguf" and "VRCT_SPEECH_ASR_MODEL" not in tts
    assert "VRCT_SPEECH_BINARY" not in rows["ui"][1]
    rvc = rows["rvc"][1]
    assert (rvc["VRCT_RVC_RUNTIME"], rvc["VRCT_RVC_MODEL"], rvc["VRCT_RVC_INDEX"], rvc["VRCT_RVC_INPUT"]) == (
        "/r/rvc", "/m/model.pth", "/m/model.index", "/m/input.wav")
    seed = rows["seed-vc"][1]
    assert (seed["VRCT_SEED_POC"], seed["VRCT_SEED_REFERENCE"], seed["VRCT_SEED_INPUT"]) == ("/r/seed-vc", "/m/input.wav", "/m/input.wav")


def test_spoken_translation_runs_its_rvc_variants_only_when_the_runtime_is_there():
    with_rvc = by_name(subject.plan(args(), ALL))["asr"][1]
    assert with_rvc["VRCT_TEST_NATIVE_RVC_UI"] == "1" and with_rvc["VRCT_RVC_RUNTIME"] == "/r/rvc"
    without = by_name(subject.plan(args(), {key: value for key, value in ALL.items() if key != "rvc_runtime"}))["asr"]
    assert without[2] is None and "VRCT_TEST_NATIVE_RVC_UI" not in without[1] and "VRCT_RVC_MODEL" not in without[1]


def test_only_limits_the_run_and_every_test_file_exists():
    rows = subject.plan(args(only=["asr", "vrchat"]), ALL)
    assert [name for name, *_ in rows] == ["asr", "vrchat"]
    for tests, *_ in subject.groups().values():
        for test in tests:
            assert (ROOT / "tests/platform" / test).is_file(), test
    # The models named here are in the product's catalog, the only place they may come from.
    sys.path.insert(0, str(ROOT / "src-python"))
    from models.model_downloads.catalog import CATALOG
    assert set(subject.MODELS.values()) <= {entry.id for entry in CATALOG}
    from models.voice_conversion.runtime_setup import RVC_COMMIT, SEED_COMMIT  # the runtimes are the product's own too
    assert set(subject.RUNTIMES.values()) == {"rvc", "seed-vc"} and RVC_COMMIT and SEED_COMMIT
