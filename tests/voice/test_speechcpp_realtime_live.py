"""Opt-in existing ASR model, synthetic file input and manual commit only."""

import asyncio
import audioop
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import wave

import pytest

from models.transcription.speechcpp_asr import ASRError, SpeechCppASR
from models.transcription.speechcpp_realtime import RealtimeError, SpeechCppRealtime
from models.voice_events import AudioFrame


@pytest.mark.skipif(
    not os.environ.get("VRCT_SPEECH_ASR_MODEL"),
    reason="existing consented local model/input required",
)
def test_two_real_sessions_manual_commit_and_no_vad_fallback(tmp_path):
    binary = Path(os.environ["VRCT_SPEECH_BINARY"]).resolve(strict=True)
    model = Path(os.environ["VRCT_SPEECH_ASR_MODEL"]).resolve(strict=True)
    source = Path(os.environ["VRCT_SPEECH_ASR_INPUT"]).resolve(strict=True)
    with wave.open(str(source), "rb") as wav:
        assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
        # Test fixture normalization, not a production capture/resampler claim.
        pcm, _ = audioop.ratecv(
            wav.readframes(wav.getnframes()), 2, 1, wav.getframerate(), 24000, None
        )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    async def run(model_id):
        missing = SpeechCppRealtime(url, model_id, "ja", "mic")
        with pytest.raises(RealtimeError, match="server_error"):
            await missing.start()
        assert missing.state == "failed"

        async def session(source_name):
            client = SpeechCppRealtime(
                url, model_id, "ja", source_name, server_vad=False
            )
            await client.start()
            updates = []
            final_at = None

            async def collect():
                nonlocal final_at
                while True:
                    update = await client.next_update()
                    updates.append(update)
                    if update.is_final:
                        final_at = time.monotonic_ns()
                        return

            receiver = asyncio.create_task(collect())
            started = time.monotonic_ns()
            try:
                for index, offset in enumerate(range(0, len(pcm), 960)):
                    await asyncio.sleep(
                        max(
                            0,
                            (started + index * 20_000_000 - time.monotonic_ns()) / 1e9,
                        )
                    )
                    await client.feed(
                        AudioFrame(pcm[offset : offset + 960], 24000),
                        time.monotonic_ns(),
                    )
                committed = time.monotonic_ns()
                await client.commit()
                await asyncio.wait_for(receiver, 10)
                finals = [u for u in updates if u.is_final]
                assert len(finals) == 1 and finals[0].text.strip()
                assert all(
                    u.source == source_name and u.namespace == client.namespace
                    for u in updates
                )
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(client.next_update(), 0.1)
                return {
                    "source": source_name,
                    "namespace": client.namespace,
                    "finals": len(finals),
                    "partial_updates": len(updates) - 1,
                    "characters": len(finals[0].text),
                    "commit_to_final_ms": (final_at - committed) / 1e6,
                    "first_append_to_final_ms": (final_at - started) / 1e6,
                }
            finally:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
                await client.stop()

        rows = await asyncio.gather(session("mic"), session("speaker"))
        assert len({r["namespace"] for r in rows}) == 2
        return rows

    with (tmp_path / "server.log").open("wb") as log:
        process = subprocess.Popen(
            [
                str(binary),
                "serve",
                str(model),
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
            end = time.monotonic() + 20
            while True:
                assert process.poll() is None
                try:
                    models = rest.recognizers()
                    break
                except ASRError:
                    assert time.monotonic() < end
                    time.sleep(0.05)
            rows = asyncio.run(run(models[0].id))
            (tmp_path / "report.json").write_text(
                json.dumps(
                    {
                        "mode": "manual_commit",
                        "server_vad_tested": False,
                        "source": "existing synthetic file, no physical capture",
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
