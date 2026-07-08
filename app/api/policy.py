"""Policy & ITDR API: status, playbooks, deny-logon artifacts, alert export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from app.core.agent_registry import AgentRegistry
from app.core.config import Settings
from app.core.export import render_export
from app.core.monitoring_engine import MonitoringEngine
from app.core.playbooks import list_playbooks, playbook_for_event
from app.core.policy import PolicyEngine


def build_policy_router(
    *,
    settings: Settings,
    monitoring_engine: MonitoringEngine,
    agent_registry: AgentRegistry | None,
    require_auth,
) -> APIRouter:
    router = APIRouter(prefix="/api/policy", tags=["policy"])

    def _engine() -> PolicyEngine:
        return PolicyEngine(settings)

    def _healthy_agents() -> int:
        if agent_registry is None:
            return 0
        return int(agent_registry.summary().get("healthy") or 0)

    @router.get("/status")
    def policy_status(request: Request) -> dict[str, Any]:
        require_auth(request)
        objects: list[dict[str, Any]] = []
        last = request.session.get("last_deployment")
        if isinstance(last, dict):
            objects = list(last.get("objects") or [])
        report = _engine().evaluate(
            objects=objects,
            provision_ad=False,
            agent_healthy=_healthy_agents(),
        )
        return {"report": report.to_dict()}

    @router.get("/deny-logon")
    def deny_logon_guide(request: Request) -> dict[str, Any]:
        require_auth(request)
        usernames: list[str] = []
        last = request.session.get("last_deployment")
        if isinstance(last, dict):
            for item in last.get("objects") or []:
                if str(item.get("object_type") or "") == "HoneyUser":
                    usernames.append(str(item.get("name") or ""))
        return {"deny_logon": _engine().deny_logon_artifacts(usernames)}

    @router.get("/playbooks")
    def playbooks(request: Request) -> dict[str, Any]:
        require_auth(request)
        return {"playbooks": list_playbooks()}

    @router.get("/playbook")
    def playbook_for(
        request: Request,
        event_id: int | None = None,
        uid: int | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        event: dict[str, Any] = {"event_id": event_id or 0}
        if uid is not None:
            for item in monitoring_engine.list_events(limit=500):
                if item.get("uid") == uid:
                    event = item
                    break
        return {"playbook": playbook_for_event(event)}

    @router.get("/export")
    def export_alerts(
        request: Request,
        format: str = Query(default="json", alias="format"),
        honey_only: bool = False,
        exclude_baseline: bool = True,
        download: bool = False,
        limit: int = 200,
    ) -> Any:
        require_auth(request)
        fmt = (format or "json").lower()
        if fmt not in {"json", "stix", "syslog"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="format must be json, stix, or syslog",
            )
        events = monitoring_engine.list_events(
            honey_only=honey_only,
            exclude_baseline=exclude_baseline,
            limit=limit,
        )
        # Enrich with playbook id for operators exporting evidence packs.
        enriched = []
        for event in events:
            row = dict(event)
            row["playbook_id"] = playbook_for_event(event).get("id")
            enriched.append(row)

        if not download and fmt == "json":
            from app.core.export import export_json_bundle

            return export_json_bundle(enriched)

        body, media, filename = render_export(enriched, fmt)
        if download or fmt in {"stix", "syslog"}:
            return Response(
                content=body,
                media_type=media,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        if fmt == "stix":
            import json

            return json.loads(body)
        return Response(content=body, media_type=media)

    return router
