"""Security event collectors for the Washu Agent.

Sources:
  - winlog: Windows Security log via win32evtlog (optional)
  - file: NDJSON or EVTX-style JSON lines from a path
  - demo: synthetic lab events for corridor demos
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import platform
import re
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

WATCHED_EVENT_IDS = {4624, 4625, 4768, 4769}


@dataclass
class CollectedEvent:
    event_id: int
    actor: str
    target: str
    severity: str
    source: str
    description: str
    timestamp: str
    agent_id: str = ""

    def to_ingest_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _severity_for(event_id: int) -> str:
    return {
        4768: "info",
        4769: "high",
        4625: "medium",
        4624: "info",
    }.get(event_id, "info")


def _normalize_payload(raw: dict[str, Any], *, agent_id: str = "") -> CollectedEvent | None:
    try:
        event_id = int(raw.get("event_id") or raw.get("EventID") or 0)
    except (TypeError, ValueError):
        return None
    if event_id not in WATCHED_EVENT_IDS:
        return None
    target = str(raw.get("target") or raw.get("TargetUserName") or raw.get("AccountName") or "")
    actor = str(raw.get("actor") or raw.get("IpAddress") or raw.get("WorkstationName") or raw.get("source") or "")
    if not target and not actor:
        return None
    description = str(
        raw.get("description")
        or raw.get("Message")
        or f"Security event {event_id} target={target or 'unknown'}"
    )
    timestamp = str(raw.get("timestamp") or raw.get("TimeCreated") or _utcnow())
    source = str(raw.get("source") or "Security")
    return CollectedEvent(
        event_id=event_id,
        actor=actor or "unknown",
        target=target or "unknown",
        severity=str(raw.get("severity") or _severity_for(event_id)),
        source=source,
        description=description,
        timestamp=timestamp,
        agent_id=agent_id,
    )


class FileEventCollector:
    """Tail a newline-delimited JSON event file (lab / SIEM export)."""

    def __init__(self, path: Path, *, agent_id: str = "") -> None:
        self.path = path
        self.agent_id = agent_id
        self._offset = 0
        if path.exists():
            self._offset = path.stat().st_size

    def poll(self) -> list[CollectedEvent]:
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self._offset:
            self._offset = 0
        events: list[CollectedEvent] = []
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self._offset)
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event = _normalize_payload(payload, agent_id=self.agent_id)
                if event:
                    events.append(event)
            self._offset = handle.tell()
        return events


class WinlogCollector:
    """Read recent Windows Security events (requires pywin32 on Windows)."""

    def __init__(self, *, agent_id: str = "", max_events: int = 40) -> None:
        self.agent_id = agent_id
        self.max_events = max_events
        self._last_record: int | None = None

    def available(self) -> bool:
        if platform.system().lower() != "windows":
            return False
        try:
            import win32evtlog  # noqa: F401
        except ImportError:
            return False
        return True

    def poll(self) -> list[CollectedEvent]:
        if not self.available():
            return []
        import win32evtlog
        import win32evtlogutil

        handle = win32evtlog.OpenEventLog(None, "Security")
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        events: list[CollectedEvent] = []
        try:
            while len(events) < self.max_events:
                records = win32evtlog.ReadEventLog(handle, flags, 0)
                if not records:
                    break
                for record in records:
                    event_id = int(record.EventID & 0xFFFF)
                    if event_id not in WATCHED_EVENT_IDS:
                        continue
                    if self._last_record is not None and record.RecordNumber <= self._last_record:
                        continue
                    try:
                        message = win32evtlogutil.SafeFormatMessage(record, "Security")
                    except Exception:
                        message = f"Event {event_id}"
                    target = _extract_field(message, r"Account Name:\s+(\S+)") or "unknown"
                    actor = _extract_field(message, r"Source Network Address:\s+(\S+)") or (
                        _extract_field(message, r"Workstation Name:\s+(\S+)") or "unknown"
                    )
                    events.append(
                        CollectedEvent(
                            event_id=event_id,
                            actor=actor,
                            target=target,
                            severity=_severity_for(event_id),
                            source="Windows Security",
                            description=message.splitlines()[0][:240] if message else f"Event {event_id}",
                            timestamp=record.TimeGenerated.isoformat()
                            if hasattr(record.TimeGenerated, "isoformat")
                            else _utcnow(),
                            agent_id=self.agent_id,
                        )
                    )
                    if self._last_record is None or record.RecordNumber > self._last_record:
                        self._last_record = record.RecordNumber
                    if len(events) >= self.max_events:
                        break
        finally:
            win32evtlog.CloseEventLog(handle)
        return list(reversed(events))


def _extract_field(message: str, pattern: str) -> str | None:
    match = re.search(pattern, message, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    if value in {"-", ""}:
        return None
    return value


class DemoCollector:
    """Generate one synthetic honey interaction per call (lab demos)."""

    def __init__(self, honey_targets: tuple[str, ...], *, agent_id: str = "") -> None:
        self.honey_targets = honey_targets or ("hw_alex.hale",)
        self.agent_id = agent_id
        self._tick = 0

    def poll(self) -> list[CollectedEvent]:
        self._tick += 1
        # Only emit on first poll and then every ~6th to avoid flooding demos if loop runs.
        if self._tick != 1 and self._tick % 6 != 0:
            return []
        target = self.honey_targets[(self._tick - 1) % len(self.honey_targets)]
        event_id = (4768, 4769, 4625, 4624)[(self._tick - 1) % 4]
        return [
            CollectedEvent(
                event_id=event_id,
                actor="WKS-DEMO",
                target=target,
                severity=_severity_for(event_id),
                source="washu-demo",
                description=f"Demo {event_id} involving {target}",
                timestamp=_utcnow(),
                agent_id=self.agent_id,
            )
        ]


def build_collectors(
    *,
    event_source: str,
    event_log_path: str,
    honey_targets: tuple[str, ...],
    agent_id: str,
) -> list[Any]:
    """Select collectors from configuration."""

    source = (event_source or "auto").lower()
    collectors: list[Any] = []

    if source in {"file", "auto"} and event_log_path:
        collectors.append(FileEventCollector(Path(event_log_path), agent_id=agent_id))

    if source in {"winlog", "auto"}:
        winlog = WinlogCollector(agent_id=agent_id)
        if winlog.available() or source == "winlog":
            collectors.append(winlog)

    if source == "demo" or (source == "auto" and not collectors):
        collectors.append(DemoCollector(honey_targets, agent_id=agent_id))

    return collectors


def collect_events(collectors: list[Any]) -> list[dict[str, Any]]:
    """Poll all collectors and return ingest-ready dicts."""

    events: list[dict[str, Any]] = []
    for collector in collectors:
        try:
            batch: Iterator[CollectedEvent] | list[CollectedEvent] = collector.poll()
        except Exception:
            logger.exception("Collector %s failed", type(collector).__name__)
            continue
        for item in batch:
            events.append(item.to_ingest_dict())
    return events
