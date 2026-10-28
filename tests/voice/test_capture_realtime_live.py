"""Opt-in private OS capture -> ingress -> actual server VAD, no host recording."""

import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import shlex
import subprocess
import sys
from threading import Event, Thread
import time
import wave

import numpy as np
import pytest

from models.audio_routing.devices_pipewire import PipeWireOutput
from models.transcription.capture_pipewire import PipeWireCapture, enumerate_endpoints
from models.transcription.realtime_audio import RealtimeIngress
from models.transcription.speechcpp_asr import ASRError, SpeechCppASR
from models.transcription.speechcpp_realtime import RealtimeError, SpeechCppRealtime
from models.tts.speechcpp_tts import CancelToken
from tools.voice_acceptance import private_graph, loopback, nodes, stop_process


@pytest.mark.skipif(
    sys.platform != "linux" or not os.environ.get("VRCT_SPEECH_VAD_MODEL"),
    reason="consented local Silero and Linux capture required",
)
def test_private_os_capture_two_sources_to_real_server_vad(tmp_path):
    binary = Path(os.environ["VRCT_SPEECH_BINARY"]).resolve(strict=True)
    asr = Path(os.environ["VRCT_SPEECH_ASR_MODEL"]).resolve(strict=True)
    vad = Path(os.environ["VRCT_SPEECH_VAD_MODEL"]).resolve(strict=True)
    fixture = Path(os.environ["VRCT_SPEECH_ASR_INPUT"]).resolve(strict=True)
    with wave.open(str(fixture), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
            48000,
            1,
            2,
        )
        pcm = wav.readframes(wav.getnframes())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    async def run(model):
        clients, ingresses, captures, pumps, collectors = [], [], [], [], []
        observations = []
        failure = []
        try:
            for kind in ("mic", "speaker"):
                client = SpeechCppRealtime(url, model, "ja", kind)
                clients.append(client)
                await client.start()
                ingress = RealtimeIngress(48000, 1)
                ingresses.append(ingress)
                record = {
                    "source": kind,
                    "updates": [],
                    "capture_ages": [],
                    "feed_ages": [],
                    "nonzero_frames": 0,
                }
                observations.append(record)
                feed = client.feed

                async def measured_feed(audio, captured_ns, feed=feed, record=record):
                    record["feed_ages"].append(
                        (time.monotonic_ns() - captured_ns) / 1e6
                    )
                    await feed(audio, captured_ns)

                client.feed = measured_feed
                pumps.append(asyncio.create_task(ingress.pump(client)))

                async def collect(client=client, record=record):
                    while True:
                        record["updates"].append(await client.next_update())

                collectors.append(asyncio.create_task(collect()))
                endpoint = next(
                    row["endpoint"]
                    for row in enumerate_endpoints(kind)
                    if row["endpoint"].name
                    == "vrct.capture.live." + ("source" if kind == "mic" else "sink")
                )

                def audio(frame, ingress=ingress, record=record):
                    record["capture_ages"].append(
                        (time.monotonic_ns() - frame.captured_ns) / 1e6
                    )
                    record["nonzero_frames"] += bool(any(frame.audio.pcm))
                    return ingress.push(frame.audio, frame.captured_ns)

                def error(code, ingress=ingress):
                    failure.append(code)
                    ingress.close()

                helper = tmp_path / ("capture-" + kind)
                native = Path(
                    os.environ.get(
                        "VRCT_ASR_CAPTURE_HELPER",
                        str(
                            Path(__file__).resolve().parents[2]
                            / "build/vrct-asr-capture"
                        ),
                    )
                )
                helper.write_text(
                    "#!/bin/sh\nexec "
                    + shlex.quote(str(native))
                    + ' "$@" 2>'
                    + shlex.quote(str(tmp_path / ("capture-" + kind + ".log")))
                    + "\n"
                )
                helper.chmod(0o700)
                capture = PipeWireCapture(endpoint, kind, audio, error, helper=helper)
                captures.append(capture)
                await asyncio.to_thread(capture.start)
            # Both capture sessions receive actual OS silence before any speech.
            await asyncio.sleep(1.2)
            assert not failure and all(not r["updates"] for r in observations)

            emit.set()
            assert await asyncio.to_thread(emitted.wait, 10)
            assert not producer_errors, producer_errors
            deadline = time.monotonic() + 5
            while not all(
                sum(u.is_final for u in r["updates"]) >= 2 for r in observations
            ):
                assert not failure, failure
                assert time.monotonic() < deadline, [
                    (r["source"], len(r["updates"])) for r in observations
                ]
                await asyncio.sleep(0.02)
            for capture in captures:
                await asyncio.to_thread(capture.stop)
            for ingress in ingresses:
                ingress.close()
            await asyncio.wait_for(asyncio.gather(*pumps), 1)
            for task in collectors:
                task.cancel()
            await asyncio.gather(*collectors, return_exceptions=True)
            rows = []
            assert not failure
            assert all(c.state == "closed" for c in clients)
            for client in clients:
                with pytest.raises(RealtimeError):
                    await client.next_update()
            assert len({c.namespace for c in clients}) == 2
            assert not any(name.startswith("vrct.asr.capture.") for name in nodes())
            for client, record in zip(clients, observations):
                finals = [u for u in record["updates"] if u.is_final]
                partials = [u for u in record["updates"] if u.state == "partial"]
                assert len(finals) == 2 and partials
                assert len({u.item_id for u in finals}) == len(finals)
                assert all(
                    u.text.strip()
                    and u.source == record["source"]
                    and u.namespace == client.namespace
                    for u in finals
                )
                assert record["nonzero_frames"] > 0
                rows.append(
                    {
                        "source": record["source"],
                        "finals": len(finals),
                        "partials": len(partials),
                        "characters": [len(u.text) for u in finals],
                        "nonzero_frames": record["nonzero_frames"],
                        "capture_bound_to_callback_ms": dict(
                            zip(
                                ("p50", "p95", "max"),
                                np.percentile(
                                    record["capture_ages"], [50, 95, 100]
                                ).tolist(),
                            )
                        ),
                        "capture_bound_to_feed_ms": dict(
                            zip(
                                ("p50", "p95", "max"),
                                np.percentile(
                                    record["feed_ages"], [50, 95, 100]
                                ).tolist(),
                            )
                        ),
                    }
                )
            return rows
        finally:
            for capture in captures:
                await asyncio.to_thread(capture.stop)
            for ingress in ingresses:
                ingress.close()
            await asyncio.gather(*pumps, return_exceptions=True)
            for client in clients:
                await client.stop()
            for task in collectors:
                task.cancel()
            await asyncio.gather(*collectors, return_exceptions=True)

    with (
        private_graph(),
        ExitStack() as stack,
        (tmp_path / "server.log").open("wb") as log,
    ):
        loopback(stack, "vrct.capture.live")
        # Keep topology and reported capture latency stable for this run.
        # Opening a producer after capture changes the source path from 1Q to 2Q
        # and correctly trips the native epoch guard (separate regression).
        emit, emitted = Event(), Event()
        producer_errors = []
        token = CancelToken()
        output = PipeWireOutput("vrct.capture.live.sink", 48000, 1)

        def produce():
            data = b"\0\0" * 24000 + pcm + b"\0\0" * 72000
            offset = 0
            try:
                while not token.is_set():
                    chunk = b"\0" * 1920
                    if emit.is_set() and offset < len(data):
                        chunk = data[offset : offset + 1920].ljust(1920, b"\0")
                        offset += 1920
                    output.write(chunk, token)
                    if offset >= len(data):
                        emitted.set()
            except Exception as exc:
                if not token.is_set():
                    producer_errors.append(type(exc).__name__)
            finally:
                output.close(drain=False, token=token)

        producer = Thread(target=produce, daemon=True)
        producer.start()

        def stop_producer():
            token.cancel()
            producer.join(3)
            assert not producer.is_alive()

        stack.callback(stop_producer)
        process = subprocess.Popen(
            [
                str(binary),
                "serve",
                str(asr),
                str(vad),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--device",
                "gpu",
            ],
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None
                try:
                    models = SpeechCppASR(url).recognizers()
                    break
                except ASRError:
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
            rows = asyncio.run(run(models[0].id))
            (tmp_path / "report.json").write_text(
                json.dumps(
                    {
                        "private_os_capture": True,
                        "physical_capture": False,
                        "raw_capture_saved": False,
                        "results": rows,
                    },
                    indent=2,
                )
                + "\n"
            )
        finally:
            stop_process(process)
