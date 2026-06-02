"""Neo4j graph store for deception object persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


HONEY_LABELS = ("HoneyUser", "HoneyServer", "HoneyDC", "Breadcrumb")


@dataclass
class GraphHealth:
    configured: bool
    connected: bool
    message: str
    node_count: int = 0


class GraphStore:
    """Thin wrapper around the Neo4j Python driver."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._driver: Any | None = None

    def _get_driver(self) -> Any:
        if self._driver is not None:
            return self._driver

        if not self.settings.neo4j_configured:
            raise RuntimeError("Neo4j is not configured. Set NEO4J_URI and NEO4J_PASSWORD in .env.")

        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_username, self.settings.neo4j_password),
        )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def health(self) -> GraphHealth:
        if not self.settings.neo4j_configured:
            return GraphHealth(
                configured=False,
                connected=False,
                message="Neo4j credentials not configured.",
            )

        try:
            driver = self._get_driver()
            driver.verify_connectivity()
            with driver.session(database=self.settings.neo4j_database) as session:
                result = session.run(
                    "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) RETURN count(n) AS count",
                    labels=list(HONEY_LABELS),
                )
                node_count = int(result.single()["count"])
            return GraphHealth(
                configured=True,
                connected=True,
                message="Connected",
                node_count=node_count,
            )
        except Exception as exc:
            return GraphHealth(
                configured=True,
                connected=False,
                message=str(exc),
            )

    def execute_queries(self, queries: list[str]) -> dict[str, Any]:
        if not queries:
            return {"success": True, "executed": 0, "errors": []}

        driver = self._get_driver()
        executed = 0
        errors: list[str] = []

        with driver.session(database=self.settings.neo4j_database) as session:
            for query in queries:
                statement = query.strip().rstrip(";")
                if not statement:
                    continue
                try:
                    session.run(statement)
                    executed += 1
                except Exception as exc:
                    errors.append(f"{statement[:80]}... -> {exc}")

        return {
            "success": not errors,
            "executed": executed,
            "errors": errors,
        }

    def fetch_honey_nodes(self) -> list[dict[str, Any]]:
        driver = self._get_driver()
        label_filter = " OR ".join(f"n:{label}" for label in HONEY_LABELS)
        query = f"""
        MATCH (n)
        WHERE {label_filter}
        RETURN labels(n)[0] AS object_type, n.name AS name, n.role AS role, n.color AS color
        ORDER BY n.name
        """

        with driver.session(database=self.settings.neo4j_database) as session:
            result = session.run(query)
            rows: list[dict[str, Any]] = []
            for record in result:
                rows.append(
                    {
                        "object_type": record["object_type"],
                        "name": record["name"],
                        "role": record["role"] or "",
                        "color": record["color"] or "blue",
                    }
                )
            return rows

    def import_cypher_file(self, content: str) -> dict[str, Any]:
        statements = [part.strip() for part in content.split(";") if part.strip()]
        return self.execute_queries([f"{statement};" for statement in statements])
