"""Monitoring API routes: event feed, ingest, SSE, simulation, and triage."""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Form, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.audit import audit_event
from app.core.config import Settings
from app.core.monitoring_engine import SEVERITIES, MonitoringEngine
from app.core.agent_registry import AgentRegistry


class IngestEventItem(BaseModel):
    event_id: int
    actor: str
    target: str
    severity: str = "info"
    source: str = "agent"
    description: str = ""
    timestamp: str = ""
    agent_id: str = ""


class IngestRequest(BaseModel):
    events: list[IngestEventItem] = Field(default_factory=list)
    agent_id: str = "washu-agent"


def build_monitoring_router(
    monitoring_engine: MonitoringEngine,
    require_auth,
    settings: Settings,
    agent_registry: AgentRegistry | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

    def _ensure_registered(request: Request) -> None:
        if monitoring_engine.registered_honey_objects:
            return
        deployment = request.session.get("last_deployment")
        if isinstance(deployment, dict):
            monitoring_engine.register_deployment(deployment.get("objects", []))

    def _require_agent_token(
        authorization: str | None,
        x_agent_token: str | None,
    ) -> None:
        expected = settings.agent_ingest_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent ingest is disabled. Set AGENT_INGEST_TOKEN in .env.",
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

    @router.get("/events")
    def monitoring_events(
        request: Request,
        severity: str | None = None,
        event_id: int | None = None,
        honey_only: bool = False,
        exclude_baseline: bool = False,
        limit: int = 50,
        since_uid: int | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        if severity and severity not in SEVERITIES:
            severity = None
        events = monitoring_engine.list_events(
            severity=severity,
            event_id=event_id,
            honey_only=honey_only,
            exclude_baseline=exclude_baseline,
            limit=limit,
            since_uid=since_uid,
        )
        return {"events": events, "stats": monitoring_engine.stats()}

    @router.get("/stats")
    def monitoring_stats(request: Request) -> dict[str, Any]:
        require_auth(request)
        return monitoring_engine.stats()

    @router.get("/stream")
    async def monitoring_stream(request: Request) -> StreamingResponse:
        require_auth(request)
        once = request.query_params.get("once") == "1"
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=100)
        loop = asyncio.get_running_loop()

        def _on_event(payload: dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except Exception:
                pass

        unsubscribe = monitoring_engine.subscribe(_on_event)

        async def event_generator():
            try:
                yield f"event: ready\ndata: {json.dumps({'status': 'ok'})}\n\n"
                if once:
                    return
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                        if payload is None:
                            break
                        yield f"event: monitoring\ndata: {json.dumps(payload)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                unsubscribe()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/ingest")
    def monitoring_ingest(
        payload: IngestRequest,
        authorization: Annotated[str | None, Header()] = None,
        x_agent_token: Annotated[str | None, Header(alias="X-Agent-Token")] = None,
    ) -> dict[str, Any]:
        _require_agent_token(authorization, x_agent_token)
        if not payload.events:
            return {"success": False, "message": "No events provided.", "accepted": 0, "events": []}
        if len(payload.events) > 100:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Maximum 100 events per ingest request.",
            )
        result = monitoring_engine.ingest_events(
            [item.model_dump() for item in payload.events],
            agent_id=payload.agent_id or "washu-agent",
        )
        if agent_registry is not None:
            agent_registry.note_ingest(
                payload.agent_id or "washu-agent",
                int(result.get("accepted") or 0),
            )
        audit_event(
            "monitoring.ingest",
            actor=payload.agent_id or "washu-agent",
            outcome="success" if result.get("success") else "partial",
            accepted=result.get("accepted", 0),
            errors=len(result.get("errors") or []),
        )
        return result

    @router.post("/simulate")
    def monitoring_simulate(
        request: Request,
        count: Annotated[int, Form()] = 3,
    ) -> dict[str, Any]:
        require_auth(request)
        _ensure_registered(request)
        try:
            created = monitoring_engine.simulate_honey_interaction(count)
        except ValueError as exc:
            return {"success": False, "message": str(exc), "events": []}
        return {
            "success": True,
            "message": f"Generated {len(created)} honey-interaction event(s).",
            "events": created,
            "stats": monitoring_engine.stats(),
        }

    @router.post("/acknowledge")
    def monitoring_acknowledge(
        request: Request,
        uid: Annotated[int, Form()] = 0,
        ack_all: Annotated[str, Form()] = "false",
    ) -> dict[str, Any]:
        require_auth(request)
        if str(ack_all).lower() in {"1", "true", "yes", "on"}:
            updated = monitoring_engine.acknowledge_all()
            return {"success": True, "updated": updated, "stats": monitoring_engine.stats()}
        success = monitoring_engine.acknowledge(uid)
        return {
            "success": success,
            "updated": 1 if success else 0,
            "message": "" if success else f"Event {uid} not found.",
            "stats": monitoring_engine.stats(),
        }

    return router
