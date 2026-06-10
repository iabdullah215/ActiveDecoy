"""Monitoring engine for ActiveDecoy.

Maintains an in-memory event feed of authentication and Kerberos signals
(4768, 4769, 4625, 4624) and correlates honey-object interactions against the
objects produced by the deception engine. Intended for authorized lab use.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import random
import threading
from typing import Any


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


def event_to_dict(event: MonitoringEvent) -> dict[str, Any]:
    return asdict(event)


class MonitoringEngine:
    """Collects telemetry events and flags honey-object interaction."""

    MAX_EVENTS = 300

    BASELINE_TEMPLATES = [
        (4624, "info", "Workstation", "j.doe", "WKS-014", "Routine interactive logon."),
        (4624, "info", "Workstation", "svc-backup", "FILE03", "Scheduled service logon."),
        (4768, "info", "Domain Controller", "m.chen", "krbtgt", "Standard TGT issuance."),
        (4769, "info", "Domain Controller", "h.patel", "CIFS/FILE03.lab.local", "Service ticket for file share."),
        (4625, "medium", "Security Log", "a.silva", "WKS-022", "Single failed logon, likely mistyped password."),
        (4625, "medium", "Security Log", "unknown", "VPN-GW01", "Failed logon from remote gateway."),
    ]

    ATTACKER_HOSTS = ["WKS-031", "WKS-045", "LAPTOP-9F2", "10.10.14.7", "10.10.14.22"]

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)
        self._lock = threading.Lock()
        self._events: list[MonitoringEvent] = []
        self._uid_counter = 0
        self._honey_objects: list[dict[str, Any]] = []
        self._seed_baseline()

    # ——— internal helpers ———

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

    # ——— deployment correlation ———

    def register_deployment(self, objects: list[dict[str, Any]]) -> int:
        """Track deployed honey objects so interactions can be correlated."""

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
        return len(cleaned)

    @property
    def registered_honey_objects(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._honey_objects)

    # ——— event generation ———

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
        else:  # Breadcrumb or unknown decoy artifact
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
        """Generate interaction events against registered honey objects.

        Returns the newly created events. Raises ValueError when nothing is
        registered so callers can prompt for a deployment first.
        """

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
            return [event_to_dict(event) for event in created]

    def record_event(self, event_id: int, severity: str, source: str, actor: str, target: str, description: str = "") -> dict[str, Any]:
        """Record an arbitrary telemetry event (e.g. forwarded from an agent)."""

        if severity not in SEVERITIES:
            severity = "info"
        with self._lock:
            event = MonitoringEvent(
                uid=self._next_uid(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_id=event_id,
                label=EVENT_LABELS.get(event_id, f"Event {event_id}"),
                severity=severity,
                source=source,
                actor=actor,
                target=target,
                description=description,
            )
            self._append(event)
            return event_to_dict(event)

    # ——— querying ———

    def list_events(
        self,
        *,
        severity: str | None = None,
        event_id: int | None = None,
        honey_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)

        if severity:
            events = [event for event in events if event.severity == severity]
        if event_id:
            events = [event for event in events if event.event_id == event_id]
        if honey_only:
            events = [event for event in events if event.honey_object]

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
        last_event_at = ""
        for event in events:
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
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
            "last_event_at": last_event_at,
        }

    # ——— triage ———

    def acknowledge(self, uid: int) -> bool:
        with self._lock:
            for event in self._events:
                if event.uid == uid:
                    event.acknowledged = True
                    return True
        return False

    def acknowledge_all(self) -> int:
        with self._lock:
            updated = 0
            for event in self._events:
                if event.honey_object and not event.acknowledged:
                    event.acknowledged = True
                    updated += 1
            return updated
