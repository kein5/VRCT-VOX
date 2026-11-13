"""
テレメトリ状態管理
- enable/disable フラグ
- 日次デデュープを永続 JSON で管理（app_started と error）
"""
import json
import os
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

# How many sent events stay readable on this PC.
SENT_LIMIT = 20


def _today() -> str:
    # The day in UTC, the day of the timestamp an event itself carries: the receiver
    # counts by that day, so "once a day" has to mean the same day here.
    return datetime.now(timezone.utc).date().isoformat()


def _is_sent_row(row) -> bool:
    return (isinstance(row, dict) and isinstance(row.get("at"), str) and isinstance(row.get("body"), dict)
            and type(row.get("accepted")) is bool)


class TelemetryState:
    """テレメトリ有効/無効と、日次デデュープ用の永続状態を管理する。

    永続ファイルのスキーマ:
        {
            "last_app_started_date": "YYYY-MM-DD",
            "errors_sent": {"YYYY-MM-DD": ["ERROR_CODE_1", ...]},
            "sent": [{"at": "YYYY-MM-DD HH:MM", "accepted": true, "body": {...}}, ...]
        }
    書き込み時に当日以外のエントリを掃除する。日付は UTC。
    sent は送った内容そのものの直近 SENT_LIMIT 件で、設定画面から見られる（at はこの PC の時刻）。
    """

    def __init__(self, storage_path: Optional[str] = None):
        self._enabled = True  # デフォルト有効
        self._storage_path = storage_path
        self._lock = Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if not self._storage_path or not os.path.exists(self._storage_path):
            return {"last_app_started_date": None, "errors_sent": {}, "sent": []}
        try:
            with open(self._storage_path, "r", encoding="utf-8") as fp:
                loaded = json.load(fp)
            if not isinstance(loaded, dict):
                raise ValueError("telemetry state root is not a dict")
            sent = loaded.get("sent")
            return {
                "last_app_started_date": loaded.get("last_app_started_date"),
                "errors_sent": loaded.get("errors_sent") or {},
                "sent": [row for row in sent if _is_sent_row(row)][-SENT_LIMIT:] if isinstance(sent, list) else [],
            }
        except Exception:
            # 破損時は初期化。呼び出し元に例外を伝播させない。
            return {"last_app_started_date": None, "errors_sent": {}, "sent": []}

    def _save_locked(self):
        if not self._storage_path:
            return
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with open(self._storage_path, "w", encoding="utf-8") as fp:
                json.dump(self._data, fp, ensure_ascii=False, indent=2)
        except Exception:
            # 書き込み失敗は握りつぶし（テレメトリでアプリを止めない）
            pass

    def _prune_locked(self):
        """当日以外の errors_sent エントリを削除。"""
        today = _today()
        errors_sent = self._data.get("errors_sent") or {}
        self._data["errors_sent"] = {
            k: v for k, v in errors_sent.items() if k == today
        }

    def set_storage_path(self, storage_path: str):
        """遅延で保存先を差し替える（config 初期化順序への対応）。"""
        with self._lock:
            self._storage_path = storage_path
            self._data = self._load()

    def set_enabled(self, value: bool):
        with self._lock:
            self._enabled = bool(value)

    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def should_send_app_started_today(self) -> bool:
        with self._lock:
            return self._data.get("last_app_started_date") != _today()

    def mark_app_started_sent_today(self):
        with self._lock:
            self._data["last_app_started_date"] = _today()
            self._prune_locked()
            self._save_locked()

    def should_send_error_today(self, error_code: str) -> bool:
        if not error_code:
            return False
        today = _today()
        with self._lock:
            errors_sent = self._data.get("errors_sent") or {}
            return error_code not in (errors_sent.get(today) or [])

    def mark_error_sent_today(self, error_code: str):
        if not error_code:
            return
        today = _today()
        with self._lock:
            errors_sent = self._data.get("errors_sent") or {}
            today_list = list(errors_sent.get(today) or [])
            if error_code not in today_list:
                today_list.append(error_code)
            self._data["errors_sent"] = {today: today_list}
            self._save_locked()

    def record_sent(self, body: dict, accepted: bool):
        """送った内容そのものを残す（直近 SENT_LIMIT 件）。"""
        if not isinstance(body, dict):
            return
        row = {"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "accepted": bool(accepted), "body": body}
        with self._lock:
            self._data["sent"] = (list(self._data.get("sent") or []) + [row])[-SENT_LIMIT:]
            self._save_locked()

    def sent(self) -> list:
        """送った内容の記録（古い順）。"""
        with self._lock:
            return json.loads(json.dumps(self._data.get("sent") or []))

    def reset(self):
        """有効/無効フラグの実行時リセットのみ（永続データは保持）。"""
        # 永続データは削除しない。日次デデュープはプロセス終了後も維持したい。
        pass

    def get_debug_info(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "storage_path": self._storage_path,
                "last_app_started_date": self._data.get("last_app_started_date"),
                "errors_sent": dict(self._data.get("errors_sent") or {}),
            }
