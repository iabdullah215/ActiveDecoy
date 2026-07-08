"""Orchestrates AD enumeration and optional Neo4j graph import."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.connection_manager import LDAPConfig
from app.core.directory_enumerator import (
    DirectoryEnumerator,
    DirectorySnapshot,
    snapshot_to_dict,
)
from app.core.graph_store import GraphStore


def enumerate_directory(
    config: LDAPConfig,
    settings: Settings,
    *,
    enumerator: DirectoryEnumerator | None = None,
) -> DirectorySnapshot:
    engine = enumerator or DirectoryEnumerator(
        page_size=settings.ldap_page_size,
        max_objects=settings.ldap_max_objects,
    )
    return engine.enumerate(config)


def import_directory_to_graph(
    snapshot: DirectorySnapshot,
    graph_store: GraphStore,
    *,
    replace: bool = True,
) -> dict[str, Any]:
    health = graph_store.health()
    if not health.configured:
        return {
            "success": False,
            "message": "Neo4j is not configured. Set NEO4J_PASSWORD and retry.",
            "counts": {},
            "errors": ["Neo4j not configured."],
        }
    if not health.connected:
        return {
            "success": False,
            "message": f"Neo4j unreachable: {health.message}",
            "counts": {},
            "errors": [health.message],
        }
    return graph_store.sync_directory_snapshot(snapshot, replace=replace)


def run_directory_import(
    config: LDAPConfig,
    settings: Settings,
    graph_store: GraphStore,
    *,
    sync_to_graph: bool = True,
    replace: bool = True,
    enumerator: DirectoryEnumerator | None = None,
) -> dict[str, Any]:
    """Enumerate LDAP and optionally sync topology into Neo4j."""

    snapshot = enumerate_directory(config, settings, enumerator=enumerator)
    payload: dict[str, Any] = {
        "success": True,
        "message": "Directory enumeration complete.",
        "snapshot": snapshot_to_dict(snapshot),
        "summary": snapshot.summary(),
        "synced": False,
        "graph_sync": None,
    }

    if not sync_to_graph:
        payload["message"] = "Directory enumerated (Neo4j sync skipped)."
        return payload

    graph_sync = import_directory_to_graph(snapshot, graph_store, replace=replace)
    payload["graph_sync"] = graph_sync
    payload["synced"] = bool(graph_sync.get("success"))
    if graph_sync.get("success"):
        counts = graph_sync.get("counts", {})
        payload["message"] = (
            "Imported directory topology: "
            f"{counts.get('users', 0)} users, {counts.get('groups', 0)} groups, "
            f"{counts.get('computers', 0)} computers, {counts.get('trusts', 0)} trusts."
        )
    else:
        payload["success"] = False
        payload["message"] = graph_sync.get("message") or "Directory enumerated but Neo4j sync failed."
    return payload
