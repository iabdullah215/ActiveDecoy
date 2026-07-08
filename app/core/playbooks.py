"""Recommended response playbooks for honey-object telemetry."""

from __future__ import annotations

from typing import Any


PLAYBOOKS: list[dict[str, Any]] = [
    {
        "id": "tgt-honey-user",
        "title": "4768 — TGT requested for honey user",
        "event_ids": [4768],
        "severity": "high",
        "summary": "A Kerberos TGT was requested for a decoy identity that should never authenticate.",
        "steps": [
            "Confirm the target matches a deployed honey user (prefix + honey OU).",
            "Identify requesting host / account from the actor field and DC Security log.",
            "Isolate the requesting workstation if compromise is plausible.",
            "Reset any overlapping production credentials that may have been sprayed.",
            "Preserve 4768/4769 evidence; acknowledge the alert after containment notes are logged.",
        ],
        "references": ["ITDR", "Kerberos", "Honey identity"],
    },
    {
        "id": "tgs-honey-spn",
        "title": "4769 — Service ticket for bait SPN",
        "event_ids": [4769],
        "severity": "critical",
        "summary": "Service ticket activity against a honey SPN is a strong Kerberoasting / targeting signal.",
        "steps": [
            "Map the target SPN to the honey server object in Neo4j / Deception history.",
            "Check for subsequent TGS requests and hash export tooling on the actor host.",
            "Block the actor host at the network edge if lateral movement continues.",
            "Rotate any real service accounts that share naming patterns with the bait.",
            "Document the path in the case notes and acknowledge when mitigation is complete.",
        ],
        "references": ["Kerberoasting", "SPN bait"],
    },
    {
        "id": "failed-logon-honey",
        "title": "4625 — Failed logon against honey account",
        "event_ids": [4625],
        "severity": "high",
        "summary": "Password spray or stuffing against a decoy identity.",
        "steps": [
            "Correlate source IP / workstation across other failed logons.",
            "Confirm the honey account remains disabled and deny-logon GPO is linked.",
            "If volume is high, rate-limit or block the source at the VPN / firewall.",
            "Search for success (4624) against neighboring production accounts from the same actor.",
            "Acknowledge after spray containment.",
        ],
        "references": ["Password spray", "4625"],
    },
    {
        "id": "success-logon-honey",
        "title": "4624 — Successful logon using honey / breadcrumb creds",
        "event_ids": [4624],
        "severity": "critical",
        "summary": "Interactive or network logon succeeded with bait credentials — assume credential theft.",
        "steps": [
            "Immediately disable / revoke the used breadcrumb secret if it was planted deliberately.",
            "Isolate the destination host and collect process / network evidence.",
            "Hunt for follow-on activity (file access, new local admins, outbound C2).",
            "Reset related production passwords that shared the breadcrumb location.",
            "Escalate per incident severity; acknowledge only after containment.",
        ],
        "references": ["Credential theft", "Breadcrumbs"],
    },
    {
        "id": "generic-honey",
        "title": "Generic honey-object interaction",
        "event_ids": [],
        "severity": "medium",
        "summary": "Any verified interaction with a decoy is high-confidence malice or unauthorized testing.",
        "steps": [
            "Verify deployment history and honey OU membership.",
            "Follow the event-specific playbook when Event ID is known.",
            "Notify lab owners if activity falls outside the authorized test window.",
            "Export the alert bundle for evidence retention.",
        ],
        "references": ["ITDR"],
    },
]


def list_playbooks() -> list[dict[str, Any]]:
    return [dict(item) for item in PLAYBOOKS]


def playbook_for_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return the best matching playbook for a monitoring event."""

    try:
        event_id = int(event.get("event_id") or 0)
    except (TypeError, ValueError):
        event_id = 0

    for item in PLAYBOOKS:
        if event_id and event_id in (item.get("event_ids") or []):
            matched = dict(item)
            matched["matched_on"] = "event_id"
            matched["event"] = {
                "uid": event.get("uid"),
                "target": event.get("target"),
                "honey_object": event.get("honey_object"),
                "actor": event.get("actor"),
            }
            return matched

    fallback = dict(PLAYBOOKS[-1])
    fallback["matched_on"] = "honey_generic" if event.get("honey_object") else "default"
    fallback["event"] = {
        "uid": event.get("uid"),
        "target": event.get("target"),
        "honey_object": event.get("honey_object"),
        "actor": event.get("actor"),
    }
    return fallback
