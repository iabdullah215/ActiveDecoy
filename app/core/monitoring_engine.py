"""Monitoring engine for ActiveDecoy.

Maintains an event feed of authentication and Kerberos signals
(4768, 4769, 4625, 4624), correlates honey-object interactions, persists to
disk, and notifies SSE subscribers. Intended for authorized lab use.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import threading
from typing import Any, Callable

from app.core.monitoring_store import MonitoringStore


SEVERITIES = ("critical", "high", "medium", "info")

EVENT_LABELS = {
    4768: "Kerberos TGT requested",
    4769: "Kerberos service ticket requested",
    4625: "Failed logon",
    4624: "Successful logon",
}


@dataclass
class MonitoringEvent:
    uid: int
    timestamp: str
    event_id: int
    label: str
    severity: str
    source: str
    actor: str
    target: str
    honey_object: str = ""
    object_type: str = ""
    description: str = ""
    acknowledged: bool = False
    ingested: bool = False
    agent_id: str = ""


def event_to_dict(event: MonitoringEvent) -> dict[str, Any]:
    return asdict(event)


def _event_from_dict(data: dict[str, Any]) -> MonitoringEvent | None:
    if not isinstance(data, dict):
        return None
    allowed = {item.name for item in fields(MonitoringEvent)}
    payload = {key: value for key, value in data.items() if key in allowed}
    try:
        return MonitoringEvent(
            uid=int(payload.get("uid") or 0),
            timestamp=str(payload.get("timestamp") or ""),
            event_id=int(payload.get("event_id") or 0),
            label=str(payload.get("label") or ""),
            severity=str(payload.get("severity") or "info"),
            source=str(payload.get("source") or ""),
            actor=str(payload.get("actor") or ""),
            target=str(payload.get("target") or ""),
            honey_object=str(payload.get("honey_object") or ""),
            object_type=str(payload.get("object_type") or ""),
            description=str(payload.get("description") or ""),
            acknowledged=bool(payload.get("acknowledged", False)),
            ingested=bool(payload.get("ingested", False)),
            agent_id=str(payload.get("agent_id") or ""),
        )
    except Exception:
        return None


class MonitoringEngine:
    """Collects telemetry events and flags honey-object interaction."""

    MAX_EVENTS = 500

    BASELINE_TEMPLATES = [
        (4624, "info", "Workstation", "j.doe", "WKS-014", "Routine interactive logon."),
        (4624, "info", "Workstation", "svc-backup", "FILE03", "Scheduled service logon."),
        (4768, "info", "Domain Controller", "m.chen", "krbtgt", "Standard TGT issuance."),
        (4769, "info", "Domain Controller", "h.patel", "CIFS/FILE03.lab.local", "Service ticket for file share."),
        (4625, "medium", "Security Log", "a.silva", "WKS-022", "Single failed logon, likely mistyped password."),
        (4625, "medium", "Security Log", "unknown", "VPN-GW01", "Failed logon from remote gateway."),
    ]

    ATTACKER_HOSTS = ["WKS-031", "WKS-045", "LAPTOP-9F2", "10.10.14.7", "10.10.14.22"]

    def __init__(
        self,
        seed: int | None = None,
        *,
        store_path: Path | None = None,
        seed_baseline: bool = True,
    ) -> None:
        self.random = random.Random(seed)
        self._lock = threading.Lock()
        self._events: list[MonitoringEvent] = []
        self._uid_counter = 0
        self._honey_objects: list[dict[str, Any]] = []
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._store = MonitoringStore(store_path, max_events=self.MAX_EVENTS) if store_path else None

        loaded = False
        if self._store is not None:
            loaded = self._restore()
        if not loaded and seed_baseline:
            self._seed_baseline()

    def _restore(self) -> bool:
        assert self._store is not None
        snapshot = self._store.load()
        events_raw = snapshot.get("events") or []
        restored: list[MonitoringEvent] = []
        for item in events_raw:
            event = _event_from_dict(item)
            if event is not None and event.uid > 0:
                restored.append(event)
        if not restored and not snapshot.get("honey_objects"):
            return False
        with self._lock:
            self._events = restored[-self.MAX_EVENTS :]
            self._honey_objects = list(snapshot.get("honey_objects") or [])
            max_uid = max((event.uid for event in self._events), default=0)
            self._uid_counter = max(int(snapshot.get("uid_counter") or 0), max_uid)
        return True

    def _persist(self) -> None:
        if self._store is None:
            return
        with self._lock:
            events = list(self._events)
            honey = list(self._honey_objects)
            uid_counter = self._uid_counter
        self._store.save_snapshot(events=events, honey_objects=honey, uid_counter=uid_counter)

    def _notify(self, event: MonitoringEvent) -> None:
        payload = event_to_dict(event)
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(payload)
            except Exception:
                continue

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return _unsubscribe

    def _next_uid(self) -> int:
        self._uid_counter += 1
        return self._uid_counter

    def _append(self, event: MonitoringEvent) -> None:
        self._events.append(event)
        if len(self._events) > self.MAX_EVENTS:
            del self._events[: len(self._events) - self.MAX_EVENTS]

    def _seed_baseline(self) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            for offset, template in enumerate(self.BASELINE_TEMPLATES):
                event_id, severity, source, actor, target, description = template
                timestamp = (now - timedelta(minutes=4 * (len(self.BASELINE_TEMPLATES) - offset))).isoformat()
                self._append(
                    MonitoringEvent(
                        uid=self._next_uid(),
                        timestamp=timestamp,
                        event_id=event_id,
                        label=EVENT_LABELS[event_id],
                        severity=severity,
                        source=source,
                        actor=actor,
                        target=target,
                        description=description,
                    )
                )
        self._persist()

    def register_deployment(self, objects: list[dict[str, Any]]) -> int:
        cleaned = [
            {
                "name": item.get("name", ""),
                "object_type": item.get("object_type", ""),
                "attributes": item.get("attributes", {}) or {},
            }
            for item in objects
            if item.get("name")
        ]
        with self._lock:
            self._honey_objects = cleaned
        self._persist()
        return len(cleaned)

    @property
    def registered_honey_objects(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._honey_objects)

    def _correlate(self, *, actor: str, target: str, event_id: int) -> tuple[str, str, str, str]:
        """Return honey_object, object_type, severity_override, description_suffix."""

        with self._lock:
            honey_objects = list(self._honey_objects)

        actor_l = actor.lower()
        target_l = target.lower()
        for honey in honey_objects:
            name = str(honey.get("name") or "")
            if not name:
                continue
            name_l = name.lower()
            attributes = honey.get("attributes") or {}
            spns = [str(item).lower() for item in (attributes.get("spns") or [])]
            matched = (
                name_l in target_l
                or name_l == actor_l
                or any(spn and spn in target_l for spn in spns)
            )
            if not matched:
                continue
            object_type = str(honey.get("object_type") or "")
            if object_type == "HoneyUser":
                severity = "critical"
                description = f" correlated with honey account '{name}'."
            elif object_type == "HoneyServer":
                severity = "critical"
                description = f" correlated with bait server/SPN '{name}'."
            elif object_type == "HoneyDC":
                severity = "critical"
                description = f" correlated with shadow DC '{name}'."
            else:
                severity = "high" if event_id == 4625 else "critical"
                description = f" correlated with decoy artifact '{name}'."
            return name, object_type, severity, description
        return "", "", "", ""

    def _honey_event_for(self, honey: dict[str, Any], attacker_host: str) -> MonitoringEvent:
        object_type = honey.get("object_type", "")
        name = honey.get("name", "")
        attributes = honey.get("attributes", {})

        if object_type == "HoneyUser":
            event_id = self.random.choice([4768, 4625])
            target = name
            if event_id == 4768:
                description = f"TGT requested for honey account '{name}' — no legitimate workflow uses this identity."
            else:
                description = f"Failed logon attempt against honey account '{name}'."
            severity = "critical"
            source = "Domain Controller" if event_id == 4768 else "Security Log"
        elif object_type == "HoneyServer":
            event_id = 4769
            spns = attributes.get("spns") or [f"HTTP/{name}.lab.local"]
            target = self.random.choice(spns)
            description = f"Service ticket requested for bait SPN on '{name}' — consistent with Kerberoasting."
            severity = "critical"
            source = "Domain Controller"
        elif object_type == "HoneyDC":
            event_id = 4769
            target = f"LDAP/{name}.lab.local"
            description = f"Directory service ticket requested against shadow DC '{name}'."
            severity = "critical"
            source = "Domain Controller"
        else:
            event_id = self.random.choice([4625, 4624])
            target = name
            verb = "used" if event_id == 4624 else "attempted"
            description = f"Decoy breadcrumb credential '{name}' was {verb} from {attacker_host}."
            severity = "critical" if event_id == 4624 else "high"
            source = "Security Log"

        return MonitoringEvent(
            uid=self._next_uid(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_id=event_id,
            label=EVENT_LABELS[event_id],
            severity=severity,
            source=source,
            actor=attacker_host,
            target=target,
            honey_object=name,
            object_type=object_type,
            description=description,
        )

    def simulate_honey_interaction(self, count: int = 3) -> list[dict[str, Any]]:
        with self._lock:
            if not self._honey_objects:
                raise ValueError("No honey objects registered. Deploy a deception plan first.")
            count = max(1, min(count, 10))
            created: list[MonitoringEvent] = []
            attacker_host = self.random.choice(self.ATTACKER_HOSTS)
            for _ in range(count):
                honey = self.random.choice(self._honey_objects)
                event = self._honey_event_for(honey, attacker_host)
                self._append(event)
                created.append(event)

        for event in created:
            self._notify(event)
        self._persist()
        return [event_to_dict(event) for event in created]

    def record_event(
        self,
        event_id: int,
        severity: str,
        source: str,
        actor: str,
        target: str,
        description: str = "",
        *,
        timestamp: str | None = None,
        ingested: bool = False,
        agent_id: str = "",
        auto_correlate: bool = True,
    ) -> dict[str, Any]:
        if severity not in SEVERITIES:
            severity = "info"

        honey_object = ""
        object_type = ""
        if auto_correlate:
            honey_object, object_type, severity_override, suffix = self._correlate(
                actor=actor,
                target=target,
                event_id=event_id,
            )
            if honey_object:
                severity = severity_override or severity
                if suffix and suffix not in description:
                    description = (description or EVENT_LABELS.get(event_id, f"Event {event_id}")) + suffix

        with self._lock:
            event = MonitoringEvent(
                uid=self._next_uid(),
                timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
                event_id=event_id,
                label=EVENT_LABELS.get(event_id, f"Event {event_id}"),
                severity=severity,
                source=source,
                actor=actor,
                target=target,
                honey_object=honey_object,
                object_type=object_type,
                description=description,
                ingested=ingested,
                agent_id=agent_id,
            )
            self._append(event)

        self._notify(event)
        self._persist()
        return event_to_dict(event)

    def ingest_events(self, events: list[dict[str, Any]], *, agent_id: str = "") -> dict[str, Any]:
        """Bulk-ingest telemetry payloads from an agent or SIEM forwarder."""

        created: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, item in enumerate(events):
            if not isinstance(item, dict):
                errors.append(f"item[{index}] is not an object")
                continue
            try:
                event_id = int(item.get("event_id"))
            except (TypeError, ValueError):
                errors.append(f"item[{index}] missing/invalid event_id")
                continue
            actor = str(item.get("actor") or "").strip()
            target = str(item.get("target") or "").strip()
            if not actor or not target:
                errors.append(f"item[{index}] requires actor and target")
                continue
            severity = str(item.get("severity") or "info").lower()
            source = str(item.get("source") or agent_id or "agent")
            description = str(item.get("description") or "")
            timestamp = str(item.get("timestamp") or "") or None
            created.append(
                self.record_event(
                    event_id,
                    severity,
                    source,
                    actor,
                    target,
                    description,
                    timestamp=timestamp,
                    ingested=True,
                    agent_id=agent_id or str(item.get("agent_id") or ""),
                    auto_correlate=True,
                )
            )
        return {
            "success": not errors,
            "accepted": len(created),
            "errors": errors,
            "events": created,
            "stats": self.stats(),
        }

    def list_events(
        self,
        *,
        severity: str | None = None,
        event_id: int | None = None,
        honey_only: bool = False,
        limit: int = 50,
        since_uid: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)

        if severity:
            events = [event for event in events if event.severity == severity]
        if event_id:
            events = [event for event in events if event.event_id == event_id]
        if honey_only:
            events = [event for event in events if event.honey_object]
        if since_uid is not None:
            events = [event for event in events if event.uid > since_uid]

        events.sort(key=lambda event: event.timestamp, reverse=True)
        limit = max(1, min(limit, self.MAX_EVENTS))
        return [event_to_dict(event) for event in events[:limit]]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)
            honey_count = len(self._honey_objects)

        by_severity = {severity: 0 for severity in SEVERITIES}
        honey_triggers = 0
        unacknowledged = 0
        ingested = 0
        last_event_at = ""
        for event in events:
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
            if event.ingested:
                ingested += 1
            if event.honey_object:
                honey_triggers += 1
                if not event.acknowledged:
                    unacknowledged += 1
            if event.timestamp > last_event_at:
                last_event_at = event.timestamp

        return {
            "total_events": len(events),
            "by_severity": by_severity,
            "honey_triggers": honey_triggers,
            "unacknowledged": unacknowledged,
            "registered_honey_objects": honey_count,
            "ingested_events": ingested,
            "last_event_at": last_event_at,
        }

    def acknowledge(self, uid: int) -> bool:
        updated = False
        with self._lock:
            for event in self._events:
                if event.uid == uid:
                    event.acknowledged = True
                    updated = True
                    break
        if updated:
            self._persist()
        return updated

    def acknowledge_all(self) -> int:
        with self._lock:
            updated = 0
            for event in self._events:
                if event.honey_object and not event.acknowledged:
                    event.acknowledged = True
                    updated += 1
        if updated:
            self._persist()
        return updated
