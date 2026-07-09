"""Graph-related API routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request

from app.core.audit import audit_event
from app.core.deception_engine import DeceptionEngine, deployment_to_dict
from app.core.graph_store import AD_LABELS, GRAPH_LABELS, HONEY_LABELS, GraphStore
from app.core.graph_view import resolve_graph_kind, topology_payload


def _labels_for_kind(kind: str) -> tuple[str, ...]:
    if kind == "ad":
        return AD_LABELS
    if kind == "honey":
        return HONEY_LABELS
    return GRAPH_LABELS


def _preview_topology(deception_engine: DeceptionEngine, request: Request, kind: str) -> dict[str, Any]:
    deployment = request.session.get("last_deployment") or deployment_to_dict(
        deception_engine.build_deployment(["honey_users", "honey_servers", "breadcrumbs"])
    )
    nodes: list[dict[str, Any]] = []
    for index, item in enumerate(deployment.get("objects") or []):
        object_type = str(item.get("object_type") or "HoneyUser")
        name = str(item.get("name") or f"object-{index}")
        nodes.append(
            {
                "id": f"preview-{index}-{name}",
                "object_type": object_type,
                "name": name,
                "role": str(item.get("role") or ""),
                "color": str(item.get("color") or (item.get("attributes") or {}).get("color") or "blue"),
                "dn": "",
                "enabled": (item.get("attributes") or {}).get("status", "active") != "inactive",
            }
        )
    # Soft links among preview honey objects for a readable canvas.
    edges: list[dict[str, Any]] = []
    for index in range(len(nodes) - 1):
        edges.append(
            {
                "id": f"preview-e-{index}",
                "source": nodes[index]["id"],
                "target": nodes[index + 1]["id"],
                "rel_type": "RELATED",
            }
        )
    return topology_payload(nodes, edges, kind=kind)


def build_graph_router(
    graph_store: GraphStore,
    deception_engine: DeceptionEngine,
    require_auth,
) -> APIRouter:
    router = APIRouter(prefix="/api/graph", tags=["graph"])

    def _actor(request: Request) -> str:
        return str(request.session.get("username") or "anonymous")

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
        q: str = "",
        role: str = "",
        active_only: bool = False,
        honey_only: bool = False,
    ) -> dict[str, Any]:
        require_auth(request)
        health = graph_store.health()
        # Preserve historical default: /api/graph/nodes defaults to honey.
        normalized = resolve_graph_kind(kind if (kind or "").strip() else "honey")
        if not (kind or "").strip():
            normalized = "honey"
        elif (kind or "").strip().lower() == "honey":
            normalized = "honey"

        if not health.connected:
            preview = _preview_topology(deception_engine, request, normalized)
            filtered = topology_payload(
                preview["nodes"],
                preview["edges"],
                kind=normalized,
                query=q,
                role=role,
                active_only=active_only,
                honey_only=honey_only,
            )
            return {
                "source": "preview",
                "kind": normalized,
                "nodes": filtered["nodes"],
                "health": health.__dict__,
                "counts": filtered["counts"],
            }

        try:
            nodes = graph_store.fetch_nodes(labels=_labels_for_kind(normalized), limit=limit)
            filtered = topology_payload(
                nodes,
                [],
                kind="all",
                query=q,
                role=role,
                active_only=active_only,
                honey_only=honey_only,
            )
            return {
                "source": "neo4j",
                "kind": normalized,
                "nodes": filtered["nodes"],
                "health": health.__dict__,
                "counts": filtered["counts"],
            }
        except Exception as exc:
            return {"source": "error", "nodes": [], "error": str(exc), "health": health.__dict__}

    @router.get("/topology")
    def graph_topology(
        request: Request,
        kind: str = "all",
        limit: int = 150,
        q: str = "",
        role: str = "",
        active_only: bool = False,
        honey_only: bool = False,
    ) -> dict[str, Any]:
        require_auth(request)
        health = graph_store.health()
        normalized = resolve_graph_kind(kind)

        if not health.connected:
            preview = _preview_topology(deception_engine, request, normalized)
            filtered = topology_payload(
                preview["nodes"],
                preview["edges"],
                kind=normalized,
                query=q,
                role=role,
                active_only=active_only,
                honey_only=honey_only,
            )
            return {
                "source": "preview",
                "kind": normalized,
                "nodes": filtered["nodes"],
                "edges": filtered["edges"],
                "counts": filtered["counts"],
                "health": health.__dict__,
            }

        try:
            raw = graph_store.fetch_topology(labels=_labels_for_kind(normalized), limit=limit)
            filtered = topology_payload(
                raw["nodes"],
                raw["edges"],
                kind="all",
                query=q,
                role=role,
                active_only=active_only,
                honey_only=honey_only,
            )
            return {
                "source": "neo4j",
                "kind": normalized,
                "nodes": filtered["nodes"],
                "edges": filtered["edges"],
                "counts": filtered["counts"],
                "health": health.__dict__,
            }
        except Exception as exc:
            return {
                "source": "error",
                "nodes": [],
                "edges": [],
                "error": str(exc),
                "health": health.__dict__,
            }

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
        audit_event(
            "graph.sync",
            actor=_actor(request),
            outcome="success" if result["success"] else "failure",
            request=request,
            executed=result.get("executed", 0),
            node_count=result["node_count"],
        )
        return result

    @router.post("/import-sample")
    def graph_import_sample(
        request: Request,
        cypher_text: Annotated[str, Form()] = "",
    ) -> dict[str, Any]:
        require_auth(request)
        if not cypher_text.strip():
            return {"success": False, "message": "No Cypher content provided."}
        result = graph_store.import_cypher_file(cypher_text)
        audit_event(
            "graph.import_sample",
            actor=_actor(request),
            outcome="success" if result.get("success") else "failure",
            request=request,
            executed=result.get("executed", 0),
        )
        return result

    return router
