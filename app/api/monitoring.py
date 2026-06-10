"""Monitoring API routes: event feed, stats, simulation, and triage."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request

from app.core.monitoring_engine import SEVERITIES, MonitoringEngine


def build_monitoring_router(
    monitoring_engine: MonitoringEngine,
    require_auth,
) -> APIRouter:
    router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

    def _ensure_registered(request: Request) -> None:
        """Backfill honey-object registration from the session deployment."""

        if monitoring_engine.registered_honey_objects:
            return
        deployment = request.session.get("last_deployment")
        if isinstance(deployment, dict):
            monitoring_engine.register_deployment(deployment.get("objects", []))

    @router.get("/events")
    def monitoring_events(
        request: Request,
        severity: str | None = None,
        event_id: int | None = None,
        honey_only: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        require_auth(request)
        if severity and severity not in SEVERITIES:
            severity = None
        events = monitoring_engine.list_events(
            severity=severity,
            event_id=event_id,
            honey_only=honey_only,
            limit=limit,
        )
        return {"events": events, "stats": monitoring_engine.stats()}

    @router.get("/stats")
    def monitoring_stats(request: Request) -> dict[str, Any]:
        require_auth(request)
        return monitoring_engine.stats()

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
