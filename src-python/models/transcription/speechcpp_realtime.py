"""One-loop local Realtime transport; capture and final consumers are separate."""

import asyncio
import base64
from contextlib import suppress
from dataclasses import replace
import json
import logging
from time import monotonic, monotonic_ns
from urllib.parse import urlencode
from uuid import uuid4

from websockets.asyncio.client import connect

from models.tts.settings import local_url
from models.voice_events import AudioFrame
from .realtime_events import TranscriptEvents

PENDING_TIMEOUT = 15.0
MAX_EVENT = 1024 * 1024


class RealtimeError(Exception):
    """Safe fixed code, never server text or audio."""


class _NoRedirect(connect):
    # websockets15.0.1's connect normally follows HTTP redirects. Returning the
    # original exception refuses every redirect, including same-host changes.
    def process_redirect(self, exc):
        return exc


class SpeechCppRealtime:
    def __init__(self, base_url, model, language, source, server_vad=True, options=None):
        self.base_url = local_url(base_url)
        options = dict(options or {})
        if (
            any(
                not isinstance(v, str)
                or not 0 < len(v) <= 200
                or any(ord(c) < 32 for c in v)
                for v in (model, language)
            )
            or type(server_vad) is not bool
            # Only the vocabulary members; their values are checked by asr_vocabulary.
            or set(options) - {"keywords", "prompt"}
            or not isinstance(options.get("keywords", []), list)
            or not isinstance(options.get("prompt", ""), str)
        ):
            raise ValueError("invalid_realtime_settings")
        self.model, self.language, self.server_vad = model, language, server_vad
        self.options = options
        self.namespace = uuid4().hex
        self._events = TranscriptEvents(source, self.namespace)
        self.state, self.error = "new", None
        self._updates = asyncio.Queue(maxsize=32)
        self._clear_ack = asyncio.Event()
        self._ws = self._reader = self._starting = None
        self._sending = False
        self._pending_since = {}
        self._commit_sent_at = None

    def _settings(self):
        return {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": self.model, "language": self.language, **self.options},
                    "turn_detection": {"type": "server_vad"}
                    if self.server_vad
                    else None,
                    "noise_reduction": None,
                }
            },
        }

    @staticmethod
    def _decode(raw):
        if not isinstance(raw, str) or len(raw) > MAX_EVENT:
            raise RealtimeError("invalid_event")
        try:
            value = json.loads(raw)
        except (ValueError, RecursionError):
            raise RealtimeError("invalid_event") from None
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise RealtimeError("invalid_event")
        if value["type"] == "error":
            raise RealtimeError("server_error")
        return value

    def _check_config(self, event):
        try:
            session = event["session"]
            audio = session["audio"]["input"]
            transcription = audio["transcription"]
            vad = audio["turn_detection"]
            matches = (
                event["type"] == "session.updated"
                and session["type"] == "transcription"
                and audio["format"] == {"type": "audio/pcm", "rate": 24000}
                and transcription["model"] == self.model
                and transcription["language"] == self.language
                # The server echoes the vocabulary it will use; anything else is not ours.
                and all(transcription.get(key) == value for key, value in self.options.items())
                and audio.get("noise_reduction") is None
                and audio.get("diarization") is None
                and (
                    (isinstance(vad, dict) and vad.get("type") == "server_vad")
                    if self.server_vad
                    else vad is None
                )
            )
        except (KeyError, TypeError):
            matches = False
        if not matches:
            raise RealtimeError("configuration_rejected")

    async def start(self):
        if self.state != "new":
            raise RealtimeError("new_session_required")
        self.state = "connecting"
        self._starting = asyncio.current_task()
        # Don't let a global DEBUG setting log PCM frames or transcript bodies.
        logger = logging.Logger("vrct.private.realtime")
        logger.disabled = True
        try:
            async with asyncio.timeout(2):
                self._ws = await _NoRedirect(
                    self.base_url.replace("http://", "ws://", 1)
                    + "/v1/realtime?"
                    + urlencode({"model": self.model}),
                    proxy=None,
                    compression=None,
                    open_timeout=2,
                    close_timeout=0.5,
                    max_size=MAX_EVENT,
                    max_queue=8,
                    write_limit=4096,
                    logger=logger,
                    ping_interval=10,
                    ping_timeout=2,
                )
                created = self._decode(await self._ws.recv())
                if created["type"] != "session.created":
                    raise RealtimeError("session_not_created")
                await self._ws.send(
                    json.dumps({"type": "session.update", "session": self._settings()})
                )
                self._check_config(self._decode(await self._ws.recv()))
            if self.state != "connecting":
                raise RealtimeError("stopped")
            self.state = "ready"
            self._reader = asyncio.create_task(self._read())
        except asyncio.CancelledError:
            await self._shutdown("cancelled", False)
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, RealtimeError) else "connection_failed"
            await self._shutdown(code, True)
            raise RealtimeError(code) from None
        finally:
            self._starting = None

    def _flush_updates(self):
        while not self._updates.empty():
            self._updates.get_nowait()

    async def _shutdown(self, reason, failed):
        if self.state in ("failed", "closed"):
            return
        self.state, self.error = ("failed" if failed else "closed"), reason
        self._events.close()
        self._pending_since.clear()
        self._commit_sent_at = None
        self._flush_updates()
        self._updates.put_nowait(None)
        self._clear_ack.set()
        current = asyncio.current_task()
        for task in (self._reader, self._starting):
            if task is not None and task is not current:
                task.cancel()
        ws = self._ws
        if ws is not None:
            try:
                with suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(ws.close(), 0.5)
            finally:
                ws.transport.abort()

    async def stop(self):
        tasks = [
            t
            for t in (self._reader, self._starting)
            if t is not None and t is not asyncio.current_task()
        ]
        await self._shutdown("stopped", False)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _read(self):
        try:
            while self.state in ("ready", "clearing"):
                if (
                    self._commit_sent_at is not None
                    and monotonic() - self._commit_sent_at > PENDING_TIMEOUT
                ):
                    raise RealtimeError("commit_ack_timeout")
                if any(
                    monotonic() - stamp > PENDING_TIMEOUT
                    for stamp in self._pending_since.values()
                ):
                    raise RealtimeError("utterance_timeout")
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), 0.1)
                except TimeoutError:
                    continue
                event = self._decode(raw)
                if event["type"] == "session.updated":
                    self._check_config(event)
                previous_pending = self._events.pending_ids
                for update in self._events.accept(event):
                    self._updates.put_nowait(replace(update, received_ns=monotonic_ns()))
                pending = self._events.pending_ids
                # Manual mode has no speech_started: a successful commit must
                # register a fresh item. Replayed/retired items cannot ack it.
                if (
                    not self.server_vad
                    and event["type"] == "input_audio_buffer.committed"
                    and event.get("item_id") in pending
                    and event["item_id"] not in previous_pending
                ):
                    self._commit_sent_at = None
                self._pending_since = {
                    item: self._pending_since.get(item, monotonic()) for item in pending
                }
                if (
                    event["type"] == "input_audio_buffer.cleared"
                    and self.state == "clearing"
                    and not self._events.clearing
                ):
                    self.state = "ready"
                    self._clear_ack.set()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            code = str(exc) if isinstance(exc, RealtimeError) else "stream_failed"
            await self._shutdown(code, True)

    async def _send(self, message, timeout=1.0):
        if self._sending:
            await self._shutdown("concurrent_send", True)
            raise RealtimeError("concurrent_send")
        self._sending = True
        try:
            if timeout <= 0:
                raise RealtimeError("stale_audio")
            async with asyncio.timeout(timeout):
                await self._ws.send(json.dumps(message))
            if self.state not in ("ready", "clearing"):
                raise RealtimeError("stopped")
        except asyncio.CancelledError:
            await self._shutdown("cancelled", True)
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, RealtimeError) else "send_failed"
            await self._shutdown(code, True)
            raise RealtimeError(code) from None
        finally:
            self._sending = False

    async def feed(self, audio, captured_ns):
        if self.state != "ready":
            raise RealtimeError("not_ready")
        now = monotonic_ns()
        if (
            not isinstance(audio, AudioFrame)
            or audio.sample_rate != 24000
            or audio.channels != 1
            or not 0 < len(audio.pcm) <= 4800
            or type(captured_ns) is not int
            or not 0 <= now - captured_ns <= 250_000_000
        ):
            await self._shutdown("invalid_or_stale_audio", True)
            raise RealtimeError("invalid_or_stale_audio")
        await self._send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio.pcm).decode(),
            },
            min(1.0, (captured_ns + 250_000_000 - monotonic_ns()) / 1e9),
        )

    async def commit(self):
        if self.state != "ready" or self.server_vad:
            raise RealtimeError("manual_commit_unavailable")
        if self._commit_sent_at is not None:
            raise RealtimeError("commit_pending")
        # Register before send; an immediate acknowledgement may race send's
        # completion. Ping/Pong is independent of this application response.
        self._commit_sent_at = monotonic()
        await self._send({"type": "input_audio_buffer.commit"})

    async def clear(self):
        if self.state != "ready":
            raise RealtimeError("not_ready")
        self.state = "clearing"
        self._clear_ack.clear()
        self._flush_updates()
        for update in self._events.begin_clear():
            self._updates.put_nowait(update)
        self._pending_since.clear()
        self._commit_sent_at = None
        try:
            await self._send({"type": "input_audio_buffer.clear"})
            await asyncio.wait_for(self._clear_ack.wait(), 2)
            if self.state != "ready":
                raise RealtimeError("stopped")
        except asyncio.CancelledError:
            await self._shutdown("cancelled", True)
            raise
        except Exception:
            await self._shutdown("clear_failed", True)
            raise RealtimeError("clear_failed") from None

    async def next_update(self):
        if self.state not in ("ready", "clearing"):
            raise RealtimeError(self.error or "not_ready")
        update = await self._updates.get()
        if update is None or self.state not in ("ready", "clearing"):
            raise RealtimeError(self.error or "stopped")
        return update
