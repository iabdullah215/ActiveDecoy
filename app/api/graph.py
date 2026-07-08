"""Graph-related API routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request

from app.core.deception_engine import DeceptionEngine, deployment_to_dict
from app.core.graph_store import AD_LABELS, GRAPH_LABELS, HONEY_LABELS, GraphStore


def build_graph_router(
    graph_store: GraphStore,
    deception_engine: DeceptionEngine,
    require_auth,
) -> APIRouter:
    router = APIRouter(prefix="/api/graph", tags=["graph"])

    @router.get("/health")
    def graph_health(request: Request) -> dict[str, Any]:
        require_auth(request)
        health = graph_store.health()
        return {
            "configured": health.configured,
            "connected": health.connected,
            "message": health.message,
            "node_count": health.node_count,
            "honey_count": health.honey_count,
            "ad_count": health.ad_count,
        }

    @router.get("/nodes")
    def graph_nodes(
        request: Request,
        kind: str = "honey",
        limit: int = 200,
    ) -> dict[str, Any]:
        require_auth(request)
        health = graph_store.health()
        if not health.connected:
            return {"source": "offline", "nodes": [], "health": health.__dict__}

        try:
            normalized = (kind or "honey").strip().lower()
            if normalized == "ad":
                nodes = graph_store.fetch_nodes(labels=AD_LABELS, limit=limit)
            elif normalized == "all":
                nodes = graph_store.fetch_nodes(labels=GRAPH_LABELS, limit=limit)
            else:
                nodes = graph_store.fetch_nodes(labels=HONEY_LABELS, limit=limit)
            return {"source": "neo4j", "kind": normalized, "nodes": nodes, "health": health.__dict__}
        except Exception as exc:
            return {"source": "error", "nodes": [], "error": str(exc), "health": health.__dict__}

    @router.get("/preview")
    def graph_preview(request: Request) -> dict[str, Any]:
        require_auth(request)
        deployment = request.session.get("last_deployment") or deployment_to_dict(
            deception_engine.build_deployment(["honey_users", "breadcrumbs"])
        )
        return {
            "nodes": deployment.get("objects", []),
            "cypher_queries": deployment.get("cypher_queries", []),
        }

    @router.post("/sync")
    def graph_sync(request: Request) -> dict[str, Any]:
        require_auth(request)
        deployment = request.session.get("last_deployment")
        if not deployment:
            return {"success": False, "message": "No deployment in session. Deploy deception first."}

        result = graph_store.execute_queries(deployment.get("cypher_queries", []))
        health = graph_store.health()
        result["node_count"] = health.node_count if result["success"] else 0
        result["honey_count"] = health.honey_count if result["success"] else 0
        result["ad_count"] = health.ad_count if result["success"] else 0
        return result

    @router.post("/import-sample")
    def graph_import_sample(
        request: Request,
        cypher_text: Annotated[str, Form()] = "",
    ) -> dict[str, Any]:
        require_auth(request)
        if not cypher_text.strip():
            return {"success": False, "message": "No Cypher content provided."}
        return graph_store.import_cypher_file(cypher_text)

    return router
