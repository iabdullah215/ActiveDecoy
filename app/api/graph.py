"""Graph-related API routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request

from app.core.deception_engine import DeceptionEngine, deployment_to_dict
from app.core.graph_store import GraphStore


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
        }

    @router.get("/nodes")
    def graph_nodes(request: Request) -> dict[str, Any]:
        require_auth(request)
        health = graph_store.health()
        if not health.connected:
            return {"source": "deployment", "nodes": [], "health": health.__dict__}

        try:
            nodes = graph_store.fetch_honey_nodes()
            return {"source": "neo4j", "nodes": nodes, "health": health.__dict__}
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
        result["node_count"] = graph_store.health().node_count if result["success"] else 0
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
