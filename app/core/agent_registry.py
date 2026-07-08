"""Washu Agent registry: heartbeats, health, and hypervisor VM binding."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import threading
from pathlib import Path
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class AgentRecord:
    agent_id: str
    hostname: str = ""
    version: str = ""
    status: str = "unknown"
    vm_name: str = ""
    capability: list[str] = field(default_factory=list)
    last_seen: str = ""
    last_heartbeat: dict[str, Any] = field(default_factory=dict)
    events_forwarded: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentRecord:
        return cls(
            agent_id=str(payload.get("agent_id") or ""),
            hostname=str(payload.get("hostname") or ""),
            version=str(payload.get("version") or ""),
            status=str(payload.get("status") or "unknown"),
            vm_name=str(payload.get("vm_name") or ""),
            capability=[str(item) for item in (payload.get("capability") or [])],
            last_seen=str(payload.get("last_seen") or ""),
            last_heartbeat=dict(payload.get("last_heartbeat") or {}),
            events_forwarded=int(payload.get("events_forwarded") or 0),
            meta=dict(payload.get("meta") or {}),
        )


class AgentRegistry:
    """Thread-safe agent registry with optional JSON persistence."""

    def __init__(
        self,
        *,
        store_path: Path | None = None,
        stale_seconds: int = 90,
    ) -> None:
        self.store_path = store_path
        self.stale_seconds = max(15, stale_seconds)
        self._lock = threading.Lock()
        self._agents: dict[str, AgentRecord] = {}
        if store_path:
            self._load()

    def _load(self) -> None:
        if not self.store_path or not self.store_path.exists():
            return
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        agents = raw.get("agents") if isinstance(raw, dict) else None
        if not isinstance(agents, list):
            return
        loaded: dict[str, AgentRecord] = {}
        for item in agents:
            if not isinstance(item, dict):
                continue
            record = AgentRecord.from_dict(item)
            if record.agent_id:
                loaded[record.agent_id] = record
        self._agents = loaded

    def _persist_unlocked(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _utcnow().isoformat(),
            "agents": [record.to_dict() for record in self._agents.values()],
        }
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.store_path)

    def heartbeat(
        self,
        *,
        agent_id: str,
        hostname: str = "",
        version: str = "",
        status: str = "ok",
        vm_name: str = "",
        capability: list[str] | None = None,
        events_forwarded: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not agent_id.strip():
            raise ValueError("agent_id is required")
        now = _utcnow().isoformat()
        with self._lock:
            record = self._agents.get(agent_id) or AgentRecord(agent_id=agent_id)
            record.hostname = hostname or record.hostname
            record.version = version or record.version
            record.status = status or "ok"
            record.vm_name = vm_name or record.vm_name
            if capability is not None:
                record.capability = list(capability)
            if events_forwarded is not None:
                record.events_forwarded = max(0, int(events_forwarded))
            if meta:
                record.meta = {**record.meta, **meta}
            record.last_seen = now
            record.last_heartbeat = {
                "status": record.status,
                "received_at": now,
            }
            self._agents[agent_id] = record
            self._persist_unlocked()
            return self._enrich(record)

    def note_ingest(self, agent_id: str, accepted: int) -> None:
        if not agent_id or accepted <= 0:
            return
        with self._lock:
            record = self._agents.get(agent_id)
            if not record:
                record = AgentRecord(agent_id=agent_id, status="ok", last_seen=_utcnow().isoformat())
                self._agents[agent_id] = record
            record.events_forwarded += accepted
            record.last_seen = _utcnow().isoformat()
            self._persist_unlocked()

    def _age_seconds(self, record: AgentRecord) -> float | None:
        ts = _parse_ts(record.last_seen)
        if not ts:
            return None
        return (_utcnow() - ts).total_seconds()

    def _enrich(self, record: AgentRecord) -> dict[str, Any]:
        payload = record.to_dict()
        age = self._age_seconds(record)
        payload["age_seconds"] = None if age is None else round(age, 1)
        if age is None:
            health = "unknown"
        elif age <= self.stale_seconds:
            health = "healthy"
        else:
            health = "stale"
        if record.status.lower() in {"error", "failed", "offline"}:
            health = "unhealthy"
        payload["health"] = health
        payload["stale_after_seconds"] = self.stale_seconds
        return payload

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [self._enrich(record) for record in self._agents.values()]
        rows.sort(key=lambda item: item.get("last_seen") or "", reverse=True)
        return rows

    def get(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._agents.get(agent_id)
            if not record:
                return None
            return self._enrich(record)

    def summary(self) -> dict[str, Any]:
        agents = self.list_agents()
        healthy = sum(1 for item in agents if item.get("health") == "healthy")
        return {
            "total": len(agents),
            "healthy": healthy,
            "stale": sum(1 for item in agents if item.get("health") == "stale"),
            "unhealthy": sum(1 for item in agents if item.get("health") == "unhealthy"),
            "stale_after_seconds": self.stale_seconds,
            "agents": agents,
        }
