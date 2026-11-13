"""
テレメトリコアロジック
- 受け側へのクライアントの起動/停止
- イベント送信と、送った内容の記録
"""
import asyncio

from .client import IngestClient, build_event, system_properties
from .state import TelemetryState


class TelemetryCore:
    def __init__(self, state: TelemetryState):
        self.state = state
        self.client = None
        try:
            self.client = IngestClient()
        except Exception:
            self.client = None

    def prepare(self):
        """Work that must not happen on the telemetry thread (see IngestClient.prepare)."""
        if self.client is not None:
            try:
                self.client.prepare()
            except Exception:
                self.client = None

    async def start(self, app_version: str = "1.0.0", locale: str = "", hardware=None):
        if self.client is None:
            return
        try:
            await self.client.start(app_version=app_version, locale=locale, hardware=hardware)
        except Exception:
            self.client = None

    async def stop(self):
        if self.client is not None:
            try:
                await self.client.stop()
            except Exception:
                pass

    async def send_event(self, event_name: str, payload: dict = None):
        if self.client is None:
            return
        body, accepted = await self.client.track(event_name, payload or {})
        if body is not None:
            # What left this PC stays readable on this PC (the settings show it).
            await asyncio.to_thread(self.state.record_sent, body, accepted)

    def preview(self, app_version: str, locale: str, hardware=None) -> dict:
        """What would be sent from this PC now, built by the call that builds what is sent.

        Only the timestamp differs from the event that goes out: it is the moment of asking.
        """
        return {
            "endpoint": self.client.endpoint if self.client is not None else None,
            "app_started": build_event("app_started", system_properties(app_version, locale, hardware)),
        }
