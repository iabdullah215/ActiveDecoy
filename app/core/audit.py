"""Structured audit logging for sensitive operator actions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any


AUDIT_LOGGER_NAME = "activedecoy.audit"


def get_audit_logger() -> logging.Logger:
    return logging.getLogger(AUDIT_LOGGER_NAME)


def audit_event(
    action: str,
    *,
    actor: str = "anonymous",
    outcome: str = "success",
    request: Any | None = None,
    **details: Any,
) -> None:
    """Emit a single JSON audit line (no secrets)."""

    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "actor": actor or "anonymous",
        "outcome": outcome,
    }
    if request is not None:
        client = getattr(request, "client", None)
        payload["ip"] = client.host if client else "unknown"
        payload["path"] = str(getattr(getattr(request, "url", None), "path", ""))
    if details:
        payload["details"] = details

    get_audit_logger().info(json.dumps(payload, default=str, separators=(",", ":")))


def client_ip(request: Any) -> str:
    """Best-effort client IP for rate limiting (direct connection preferred)."""

    if request is None:
        return "unknown"
    forwarded = ""
    headers = getattr(request, "headers", None)
    if headers is not None:
        forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    client = getattr(request, "client", None)
    return client.host if client else "unknown"
