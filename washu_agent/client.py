"""HTTP client for ActiveDecoy ingest and heartbeat APIs."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from washu_agent import __version__
from washu_agent.config import AgentConfig


class ConsoleClient:
    """Thin urllib client for agent → console traffic."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"WashuAgent/{__version__}",
            "X-Agent-Token": self.config.ingest_token,
        }
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach console at {url}: {exc.reason}") from exc

    def heartbeat(
        self,
        *,
        status: str = "ok",
        events_forwarded: int = 0,
        capability: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "agent_id": self.config.agent_id,
            "hostname": self.config.hostname,
            "version": __version__,
            "status": status,
            "vm_name": self.config.vm_name,
            "capability": capability or ["security-events", "heartbeat"],
            "events_forwarded": events_forwarded,
            "meta": meta or {},
        }
        if self.config.dry_run:
            return {"success": True, "dry_run": True, "payload": payload}
        return self._request("POST", "/api/agents/heartbeat", payload)

    def ingest(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "agent_id": self.config.agent_id,
            "events": events,
        }
        if self.config.dry_run:
            return {"success": True, "dry_run": True, "accepted": len(events), "payload": payload}
        return self._request("POST", "/api/monitoring/ingest", payload)

    def health_check(self) -> dict[str, Any]:
        """Unauthenticated reachability probe against OpenAPI docs."""

        if self.config.dry_run:
            return {"ok": True, "dry_run": True}
        url = f"{self.config.base_url}/openapi.json"
        try:
            with urllib.request.urlopen(url, timeout=8) as response:
                return {"ok": response.status == 200, "status": response.status}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
