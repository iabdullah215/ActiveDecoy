"""Washu Agent registry API: heartbeat and health listing."""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.agent_registry import AgentRegistry
from app.core.audit import audit_event
from app.core.config import Settings
from app.core.connection_profile import load_session_profile


class HeartbeatRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    hostname: str = ""
    version: str = ""
    status: str = "ok"
    vm_name: str = ""
    capability: list[str] = Field(default_factory=list)
    events_forwarded: int | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


def build_agents_router(
    agent_registry: AgentRegistry,
    require_auth,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/agents", tags=["agents"])

    def _require_agent_token(
        authorization: str | None,
        x_agent_token: str | None,
    ) -> None:
        expected = settings.agent_ingest_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent APIs are disabled. Set AGENT_INGEST_TOKEN in .env.",
            )
        provided = ""
        if x_agent_token:
            provided = x_agent_token.strip()
        elif authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid agent token.",
            )

    @router.post("/heartbeat")
    def agent_heartbeat(
        payload: HeartbeatRequest,
        authorization: Annotated[str | None, Header()] = None,
        x_agent_token: Annotated[str | None, Header(alias="X-Agent-Token")] = None,
    ) -> dict[str, Any]:
        _require_agent_token(authorization, x_agent_token)
        try:
            record = agent_registry.heartbeat(
                agent_id=payload.agent_id.strip(),
                hostname=payload.hostname.strip(),
                version=payload.version.strip(),
                status=payload.status.strip() or "ok",
                vm_name=payload.vm_name.strip(),
                capability=payload.capability,
                events_forwarded=payload.events_forwarded,
                meta=payload.meta,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        audit_event(
            "agent.heartbeat",
            actor=payload.agent_id,
            outcome="success",
            health=record.get("health"),
            vm_name=record.get("vm_name"),
        )
        return {"success": True, "agent": record}

    @router.get("/")
    def list_agents(request: Request) -> dict[str, Any]:
        require_auth(request)
        summary = agent_registry.summary()
        profile = load_session_profile(request.session, settings)
        summary["registered_vm_name"] = profile.hypervisor_vm_name
        return summary

    @router.get("/{agent_id}")
    def get_agent(request: Request, agent_id: str) -> dict[str, Any]:
        require_auth(request)
        record = agent_registry.get(agent_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
        return {"agent": record}

    return router
