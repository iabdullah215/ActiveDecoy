#!/usr/bin/env python3
"""Import data/sample_graph.cypher into the configured Neo4j instance."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.graph_store import GraphStore


def main() -> int:
    sample_path = PROJECT_ROOT / "data" / "sample_graph.cypher"
    if not sample_path.exists():
        print(f"Sample file not found: {sample_path}")
        return 1

    settings = get_settings()
    store = GraphStore(settings)
    health = store.health()
    if not health.connected:
        print(f"Neo4j unavailable: {health.message}")
        return 1

    content = sample_path.read_text(encoding="utf-8")
    result = store.import_cypher_file(content)
    store.close()

    if result["success"]:
        print(f"Imported {result['executed']} statement(s) from {sample_path.name}.")
        return 0

    print("Import failed:")
    for error in result["errors"]:
        print(f"  - {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
