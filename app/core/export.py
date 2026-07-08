"""Alert export helpers: JSON bundle, STIX 2.1, and syslog lines."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from typing import Any


def export_json_bundle(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": "activedecoy.alerts.json.v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(events),
        "events": events,
    }


def _stix_id(kind: str) -> str:
    return f"{kind}--{uuid.uuid4()}"


def export_stix_bundle(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal STIX 2.1 bundle of indicators + observed-data style notes."""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    objects: list[dict[str, Any]] = []
    for event in events:
        indicator_id = _stix_id("indicator")
        pattern_target = str(event.get("honey_object") or event.get("target") or "unknown").replace(
            "\\", "\\\\"
        ).replace("'", "\\'")
        objects.append(
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": indicator_id,
                "created": now,
                "modified": now,
                "name": f"ActiveDecoy {event.get('event_id')} honey interaction",
                "description": str(event.get("description") or event.get("label") or ""),
                "indicator_types": ["malicious-activity"],
                "pattern": f"[user-account:user_id = '{pattern_target}']",
                "pattern_type": "stix",
                "valid_from": now,
                "labels": ["activedecoy", "honey", f"event-{event.get('event_id')}"],
                "external_references": [
                    {
                        "source_name": "activedecoy",
                        "external_id": str(event.get("uid") or ""),
                        "description": f"severity={event.get('severity')} actor={event.get('actor')}",
                    }
                ],
            }
        )
        objects.append(
            {
                "type": "observed-data",
                "spec_version": "2.1",
                "id": _stix_id("observed-data"),
                "created": now,
                "modified": now,
                "first_observed": str(event.get("timestamp") or now),
                "last_observed": str(event.get("timestamp") or now),
                "number_observed": 1,
                "objects": {
                    "0": {
                        "type": "user-account",
                        "user_id": str(event.get("target") or ""),
                    },
                    "1": {
                        "type": "ipv4-addr" if _looks_ip(str(event.get("actor") or "")) else "domain-name",
                        "value": str(event.get("actor") or "unknown"),
                    },
                },
            }
        )
    return {
        "type": "bundle",
        "id": _stix_id("bundle"),
        "objects": objects,
    }


def _looks_ip(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def export_syslog_lines(events: list[dict[str, Any]]) -> str:
    """RFC5424-ish single-line records suitable for lab SIEM intake."""

    lines: list[str] = []
    for event in events:
        ts = str(event.get("timestamp") or datetime.now(timezone.utc).isoformat())
        line = (
            f"{ts} activedecoy alert "
            f"uid={event.get('uid')} event_id={event.get('event_id')} "
            f"severity={event.get('severity')} actor={_syslog_escape(event.get('actor'))} "
            f"target={_syslog_escape(event.get('target'))} "
            f"honey={_syslog_escape(event.get('honey_object'))} "
            f"msg=\"{_syslog_escape(event.get('description') or event.get('label'))}\""
        )
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def _syslog_escape(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_export(events: list[dict[str, Any]], fmt: str) -> tuple[str, str, str]:
    """Return (body, media_type, filename) for the requested format."""

    fmt = (fmt or "json").lower().strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if fmt == "stix":
        body = json.dumps(export_stix_bundle(events), indent=2)
        return body, "application/stix+json", f"activedecoy-alerts-{stamp}.json"
    if fmt == "syslog":
        return export_syslog_lines(events), "text/plain; charset=utf-8", f"activedecoy-alerts-{stamp}.log"
    body = json.dumps(export_json_bundle(events), indent=2)
    return body, "application/json", f"activedecoy-alerts-{stamp}.json"
