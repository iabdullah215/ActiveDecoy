"""JSON-backed persistence for monitoring events and honey registrations."""

from __future__ import annotations

from dataclasses import asdict
import json
import threading
from pathlib import Path
from typing import Any


class MonitoringStore:
    """Thread-safe on-disk store for monitoring state."""

    def __init__(self, path: Path, *, max_events: int = 500) -> None:
        self.path = path
        self.max_events = max(1, max_events)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def save_snapshot(
        self,
        *,
        events: list[Any],
        honey_objects: list[dict[str, Any]],
        uid_counter: int,
    ) -> None:
        with self._lock:
            serialized = []
            for event in events[-self.max_events :]:
                if hasattr(event, "__dataclass_fields__"):
                    serialized.append(asdict(event))
                elif isinstance(event, dict):
                    serialized.append(event)
            payload = {
                "uid_counter": uid_counter,
                "honey_objects": honey_objects,
                "events": serialized,
            }
            self._write(payload)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"uid_counter": 0, "honey_objects": [], "events": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"uid_counter": 0, "honey_objects": [], "events": []}
        if not isinstance(raw, dict):
            return {"uid_counter": 0, "honey_objects": [], "events": []}
        return {
            "uid_counter": int(raw.get("uid_counter") or 0),
            "honey_objects": list(raw.get("honey_objects") or []),
            "events": list(raw.get("events") or []),
        }

    def _write(self, payload: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)
