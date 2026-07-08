"""Persistent deployment history for deception plans.

Stores compact deployment records on disk (no LDAP passwords). Used for
teardown, audit, and UI listing beyond the session cookie.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import threading
from pathlib import Path
from typing import Any


@dataclass
class DeploymentRecord:
    deployment_id: str
    created_at: str
    actor: str
    modules: list[str] = field(default_factory=list)
    objects: list[dict[str, Any]] = field(default_factory=list)
    provisioned: list[dict[str, Any]] = field(default_factory=list)
    graph_synced: bool = False
    ad_provisioned: bool = False
    dry_run: bool = False
    status: str = "active"  # active | torn_down | plan_only
    teardown_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeploymentRecord:
        return cls(
            deployment_id=str(data.get("deployment_id", "")),
            created_at=str(data.get("created_at", "")),
            actor=str(data.get("actor", "")),
            modules=list(data.get("modules") or []),
            objects=list(data.get("objects") or []),
            provisioned=list(data.get("provisioned") or []),
            graph_synced=bool(data.get("graph_synced", False)),
            ad_provisioned=bool(data.get("ad_provisioned", False)),
            dry_run=bool(data.get("dry_run", False)),
            status=str(data.get("status", "active")),
            teardown_at=str(data.get("teardown_at", "")),
            notes=str(data.get("notes", "")),
        )


class DeploymentHistoryStore:
    """Thread-safe JSON-backed deployment history."""

    def __init__(self, path: Path, *, max_records: int = 100) -> None:
        self.path = path
        self.max_records = max(1, max_records)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_records(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            records = self._load()
        return [item.to_dict() for item in records[: max(1, limit)]]

    def get(self, deployment_id: str) -> DeploymentRecord | None:
        with self._lock:
            for item in self._load():
                if item.deployment_id == deployment_id:
                    return item
        return None

    def add(self, record: DeploymentRecord) -> DeploymentRecord:
        with self._lock:
            records = self._load()
            records.insert(0, record)
            self._save(records[: self.max_records])
        return record

    def mark_torn_down(self, deployment_id: str, *, notes: str = "") -> DeploymentRecord | None:
        with self._lock:
            records = self._load()
            updated: DeploymentRecord | None = None
            for item in records:
                if item.deployment_id == deployment_id:
                    item.status = "torn_down"
                    item.teardown_at = datetime.now(timezone.utc).isoformat()
                    if notes:
                        item.notes = notes
                    updated = item
                    break
            if updated:
                self._save(records)
            return updated

    def _load(self) -> list[DeploymentRecord]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        return [DeploymentRecord.from_dict(item) for item in raw if isinstance(item, dict)]

    def _save(self, records: list[DeploymentRecord]) -> None:
        payload = [item.to_dict() for item in records]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)
