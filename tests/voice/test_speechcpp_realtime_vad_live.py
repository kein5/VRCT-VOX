"""Consented Silero + existing ASR, two file-fed server_vad sessions."""

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import wave

import pytest

from models.transcription.realtime_audio import Pcm24kStream, RealtimeIngress
from models.transcription.speechcpp_asr import ASRError, SpeechCppASR
from models.transcription.speechcpp_realtime import SpeechCppRealtime
from models.voice_events import AudioFrame


@pytest.mark.skipif(
    not os.environ.get("VRCT_SPEECH_VAD_MODEL"),
    reason="consented local Silero required",
)
def test_real_server_vad_two_sources_partial_final_and_silence(tmp_path):
    binary = Path(os.environ["VRCT_SPEECH_BINARY"]).resolve(strict=True)
    asr_model = Path(os.environ["VRCT_SPEECH_ASR_MODEL"]).resolve(strict=True)
    vad_model = Path(os.environ["VRCT_SPEECH_VAD_MODEL"]).resolve(strict=True)
    source = Path(os.environ["VRCT_SPEECH_ASR_INPUT"]).resolve(strict=True)
    with wave.open(str(source), "rb") as wav:
        assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
        rate = wav.getframerate()
        assert rate == 48000, "native_48k_fixture_required"
        pcm = wav.readframes(wav.getnframes()) + b"\0\0" * rate
    width = rate // 50 * 2
    normalizer = Pcm24kStream(rate, 1)
    reference_pcm = b"".join(
        chunk.audio.pcm
        for index, offset in enumerate(range(0, len(pcm), width))
        for chunk in normalizer.process(
            AudioFrame(pcm[offset : offset + width], rate), 1 + index * 20_000_000
        )
    )
    normalizer.close()
    # Offline VAD sees the same continuously filtered samples as live ingress.
    reference = tmp_path / "fixture.wav"
    with wave.open(str(reference), "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(reference_pcm)
    result = subprocess.run(
        [
            str(binary),
            "vad",
            str(vad_model),
            "--format",
            "json",
            "--threshold",
            ".5",
            "--min-silence-duration-ms",
            "500",
            "--speech-pad-ms",
            "300",
            "--max-speech-duration-s",
            "10",
            str(reference),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    expected_regions = json.loads(result.stdout)["regions"]
    assert len(expected_regions) >= 1
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    async def run(model_id):
        async def one(source_name):
            client = SpeechCppRealtime(url, model_id, "ja", source_name)
            await client.start()
            updates = []
            completed = asyncio.Event()
            wire = []
            decode = client._decode

            def record(raw):
                event = decode(raw)
                # Timing/type only. Never persist transcript, PCM or server bodies.
                wire.append(
                    {
                        k: event[k]
                        for k in ("type", "item_id", "audio_start_ms", "audio_end_ms")
                        if k in event
                    }
                )
                wire[-1]["received_ns"] = time.monotonic_ns()
                return event

            client._decode = record

            async def collect():
                while True:
                    update = await client.next_update()
                    updates.append(update)
                    if sum(u.is_final for u in updates) >= len(expected_regions):
                        completed.set()

            ingress = RealtimeIngress(rate, 1)
            feed_ages_ms = []
            feed = client.feed

            async def measured_feed(audio, captured_ns):
                assert audio.sample_rate == 24000 and audio.channels == 1
                feed_ages_ms.append((time.monotonic_ns() - captured_ns) / 1e6)
                await feed(audio, captured_ns)

            client.feed = measured_feed
            pump = asyncio.create_task(ingress.pump(client))
            collector = asyncio.create_task(collect())
            start = time.monotonic_ns()
            try:
                for index, offset in enumerate(range(0, len(pcm), width)):
                    stamp = start + index * 20_000_000
                    await asyncio.sleep(
                        max(0, (stamp + 20_000_000 - time.monotonic_ns()) / 1e9)
                    )
                    assert ingress.push(
                        AudioFrame(pcm[offset : offset + width], rate), stamp
                    )
                await asyncio.wait_for(completed.wait(), 10)
                await asyncio.sleep(0.1)
                finals = [u for u in updates if u.is_final]
                assert len(finals) == len(expected_regions)
                assert len({u.item_id for u in finals}) == len(finals)
                assert all(u.text.strip() for u in finals)
                partials = [u for u in updates if u.state == "partial"]
                assert partials, "real_vad_partial_not_observed"
                assert all(
                    u.source == source_name and u.namespace == client.namespace
                    for u in updates
                )
                return {
                    "source": source_name,
                    "namespace": client.namespace,
                    "finals": len(finals),
                    "partial_updates": len(partials),
                    "characters": [len(u.text) for u in finals],
                    "wire": wire,
                    "feed_base_ns": start,
                    "fixture_regions": expected_regions,
                    "input_rate": rate,
                    "max_scheduled_capture_to_feed_ms": max(feed_ages_ms),
                }
            finally:
                collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
                ingress.close()
                await asyncio.wait_for(pump, 1)
                assert client.state == "closed"
                assert not ingress.push(
                    AudioFrame(pcm[:width], rate), time.monotonic_ns()
                )

        rows = await asyncio.gather(one("mic"), one("speaker"))
        assert len({r["namespace"] for r in rows}) == 2
        # A separate all-silence session must not invent captions.
        silent = SpeechCppRealtime(url, model_id, "ja", "mic")
        await silent.start()
        silence_ingress = RealtimeIngress(rate, 1)
        silence_pump = asyncio.create_task(silence_ingress.pump(silent))
        try:
            for _ in range(60):
                stamp = time.monotonic_ns()
                await asyncio.sleep(0.02)
                assert silence_ingress.push(
                    AudioFrame(b"\0\0" * (rate // 50), rate), stamp
                )
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(silent.next_update(), 0.25)
        finally:
            silence_ingress.close()
            await asyncio.wait_for(silence_pump, 1)
        return rows

    with (tmp_path / "server.log").open("wb") as log:
        process = subprocess.Popen(
            [
                str(binary),
                "serve",
                str(asr_model),
                str(vad_model),
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
            rest = SpeechCppASR(url)
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None
                try:
                    models = rest.recognizers()
                    break
                except ASRError:
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
            rows = asyncio.run(run(models[0].id))
            (tmp_path / "report.json").write_text(
                json.dumps(
                    {
                        "mode": "server_vad",
                        "physical_capture": False,
                        "production_ingress": True,
                        "silence_no_updates": True,
                        "results": rows,
                    },
                    indent=2,
                )
                + "\n"
            )
        finally:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
