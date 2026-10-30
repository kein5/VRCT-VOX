"""Compatibility facade: telemetry is disabled in VRCT-VOX.

Never import a stale telemetry_keys.py or create an upstream SDK client.
The async interface remains so existing feature callers need not change.
"""


class AptabaseWrapper:
    APP_KEY = None

    def __init__(self):
        self.client = None

    async def start(self, app_version="1.0.0"):
        pass

    async def track(self, event_name, properties=None):
        pass

    async def stop(self):
        pass
