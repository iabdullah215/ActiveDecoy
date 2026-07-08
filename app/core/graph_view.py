"""Helpers for filtering graph inventory/topology payloads."""

from __future__ import annotations

from typing import Any


def resolve_graph_kind(kind: str | None) -> str:
    normalized = (kind or "all").strip().lower()
    if normalized in {"honey", "ad", "all"}:
        return normalized
    return "all"


def is_honey_type(object_type: str) -> bool:
    return str(object_type or "").startswith("Honey")


def filter_graph_nodes(
    nodes: list[dict[str, Any]],
    *,
    kind: str = "all",
    query: str = "",
    role: str = "",
    active_only: bool = False,
    honey_only: bool = False,
) -> list[dict[str, Any]]:
    """Filter node dictionaries for the visualization table/canvas."""

    kind = resolve_graph_kind(kind)
    query_l = query.strip().lower()
    role_l = role.strip().lower()
    filtered: list[dict[str, Any]] = []

    for node in nodes:
        object_type = str(node.get("object_type") or "")
        if kind == "honey" and not is_honey_type(object_type):
            continue
        if kind == "ad" and is_honey_type(object_type):
            continue
        if honey_only and not is_honey_type(object_type):
            continue

        name = str(node.get("name") or "")
        node_role = str(node.get("role") or "")
        if query_l and query_l not in name.lower() and query_l not in object_type.lower():
            continue
        if role_l and role_l not in node_role.lower():
            continue
        if active_only and node.get("enabled") is False:
            continue
        filtered.append(node)
    return filtered


def filter_graph_edges(
    edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ids = {str(node.get("id") or node.get("name") or "") for node in nodes}
    return [
        edge
        for edge in edges
        if str(edge.get("source", "")) in ids and str(edge.get("target", "")) in ids
    ]


def topology_payload(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    kind: str = "all",
    query: str = "",
    role: str = "",
    active_only: bool = False,
    honey_only: bool = False,
) -> dict[str, Any]:
    filtered_nodes = filter_graph_nodes(
        nodes,
        kind=kind,
        query=query,
        role=role,
        active_only=active_only,
        honey_only=honey_only,
    )
    # Ensure every node has a stable id for the canvas.
    for index, node in enumerate(filtered_nodes):
        if not node.get("id"):
            node["id"] = str(node.get("dn") or node.get("name") or f"node-{index}")
    filtered_edges = filter_graph_edges(edges, filtered_nodes)
    return {
        "nodes": filtered_nodes,
        "edges": filtered_edges,
        "counts": {
            "nodes": len(filtered_nodes),
            "edges": len(filtered_edges),
            "honey": sum(1 for node in filtered_nodes if is_honey_type(str(node.get("object_type") or ""))),
            "ad": sum(1 for node in filtered_nodes if not is_honey_type(str(node.get("object_type") or ""))),
        },
    }
