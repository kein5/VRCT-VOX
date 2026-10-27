"""GUI-independent P1: speech.cpp -> explicit Windows/PipeWire output.

Run with uv run --no-project python tools/voice_cli.py --help.
No model downloads, microphone recording, or Windows imports on Linux.
"""
import argparse
import http.client
import json
import platform
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src-python"))

from models.audio_routing.audio_router import enumerate_outputs  # noqa: E402
from models.tts.settings import VoiceSettings, local_url  # noqa: E402
from models.tts.tts_scheduler import VoiceEventBus  # noqa: E402
from models.voice_events import SpeechMessageEvent  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help="List explicit playback targets")
    doctor = sub.add_parser("doctor", help="Check local server and environment (no downloads)")
    doctor.add_argument("--server", default="http://127.0.0.1:8080")
    speak = sub.add_parser("speak", help="Speak once; Ctrl-C cancels and releases the output")
    speak.add_argument("--text", required=True)
    speak.add_argument("--language", default="ja")
    speak.add_argument("--device", required=True, help="Exact ID from devices; never defaults to speakers")
    speak.add_argument("--japanese-url", default="http://127.0.0.1:8080")
    speak.add_argument("--japanese-voice", default="none")
    speak.add_argument("--multilingual-url", default="")
    speak.add_argument("--multilingual-voice", default="ryan")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        report = {"os": platform.platform(), "python": platform.python_version(),
                  "pw_cat": bool(shutil.which("pw-cat")), "speech_health": "unavailable"}
        url = urlsplit(local_url(args.server))
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
        try:
            conn.request("GET", "/health")
            response = conn.getresponse()
            if response.status == 200 and json.loads(response.read(1024)).get("status") == "ok":
                report["speech_health"] = "ok"
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            conn.close()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["speech_health"] == "ok" else 1
    if args.command == "devices":
        try:
            print(json.dumps(enumerate_outputs(), ensure_ascii=False, indent=2))
            return 0
        except Exception:
            print('{"error":"audio_devices_unavailable"}')
            return 1
    settings = VoiceSettings.from_dict({"mode": "original", "output_device": args.device,
        "japanese_url": args.japanese_url, "japanese_voice": args.japanese_voice,
        "multilingual_url": args.multilingual_url, "multilingual_voice": args.multilingual_voice})
    bus = VoiceEventBus(settings)
    try:
        bus.publish(SpeechMessageEvent("cli-1", "chat", args.text, source_language=args.language))
        while True:
            status = bus.status()
            if status["completed"] or status["errors"] or status["dropped"]:
                print(json.dumps({**status, "measurement_boundary": "event_to_first_pcm_write",
                                  "vrchat_latency_measured": False}))
                return 0 if status["completed"] else 1
            time.sleep(0.02)
    except KeyboardInterrupt:
        return 130
    finally:
        bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
