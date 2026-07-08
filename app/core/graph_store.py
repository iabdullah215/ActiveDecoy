"""Neo4j graph store for deception objects and AD topology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.directory_enumerator import DirectorySnapshot


HONEY_LABELS = ("HoneyUser", "HoneyServer", "HoneyDC", "Breadcrumb")
AD_LABELS = ("ADUser", "ADGroup", "ADComputer", "ADTrust", "ADDomain")
GRAPH_LABELS = HONEY_LABELS + AD_LABELS


@dataclass
class GraphHealth:
    configured: bool
    connected: bool
    message: str
    node_count: int = 0
    honey_count: int = 0
    ad_count: int = 0


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
                honey = session.run(
                    "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) RETURN count(n) AS count",
                    labels=list(HONEY_LABELS),
                ).single()
                ad = session.run(
                    "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) RETURN count(n) AS count",
                    labels=list(AD_LABELS),
                ).single()
                honey_count = int(honey["count"]) if honey else 0
                ad_count = int(ad["count"]) if ad else 0
            return GraphHealth(
                configured=True,
                connected=True,
                message="Connected",
                node_count=honey_count + ad_count,
                honey_count=honey_count,
                ad_count=ad_count,
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
        return self.fetch_nodes(labels=HONEY_LABELS)

    def fetch_ad_nodes(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self.fetch_nodes(labels=AD_LABELS, limit=limit)

    def fetch_nodes(self, *, labels: tuple[str, ...] | list[str], limit: int = 500) -> list[dict[str, Any]]:
        driver = self._get_driver()
        label_list = list(labels)
        query = """
        MATCH (n)
        WHERE any(label IN labels(n) WHERE label IN $labels)
        RETURN elementId(n) AS id,
               labels(n)[0] AS object_type,
               coalesce(n.name, n.sam_account_name, n.dn, '') AS name,
               coalesce(n.role, n.object_type, labels(n)[0], '') AS role,
               coalesce(n.color, CASE WHEN labels(n)[0] STARTS WITH 'Honey' THEN 'blue' ELSE 'slate' END) AS color,
               coalesce(n.dn, '') AS dn,
               coalesce(n.enabled, true) AS enabled
        ORDER BY object_type, name
        LIMIT $limit
        """
        with driver.session(database=self.settings.neo4j_database) as session:
            result = session.run(query, labels=label_list, limit=max(1, limit))
            rows: list[dict[str, Any]] = []
            for record in result:
                rows.append(
                    {
                        "id": str(record["id"]),
                        "object_type": record["object_type"],
                        "name": record["name"],
                        "role": record["role"] or "",
                        "color": record["color"] or "blue",
                        "dn": record["dn"] or "",
                        "enabled": bool(record["enabled"]),
                    }
                )
            return rows

    def fetch_topology(
        self,
        *,
        labels: tuple[str, ...] | list[str],
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return nodes + relationships for the native visualization canvas."""

        nodes = self.fetch_nodes(labels=labels, limit=limit)
        if not nodes:
            return {"nodes": [], "edges": []}

        driver = self._get_driver()
        label_list = list(labels)
        edge_query = """
        MATCH (a)-[r]->(b)
        WHERE any(label IN labels(a) WHERE label IN $labels)
          AND any(label IN labels(b) WHERE label IN $labels)
        RETURN elementId(a) AS source,
               elementId(b) AS target,
               type(r) AS rel_type
        LIMIT $limit
        """
        edges: list[dict[str, Any]] = []
        with driver.session(database=self.settings.neo4j_database) as session:
            result = session.run(edge_query, labels=label_list, limit=max(1, limit * 3))
            node_ids = {node["id"] for node in nodes}
            for record in result:
                source = str(record["source"])
                target = str(record["target"])
                if source in node_ids and target in node_ids:
                    edges.append(
                        {
                            "id": f"{source}->{record['rel_type']}->{target}",
                            "source": source,
                            "target": target,
                            "rel_type": record["rel_type"],
                        }
                    )
        return {"nodes": nodes, "edges": edges}

    def import_cypher_file(self, content: str) -> dict[str, Any]:
        statements = [part.strip() for part in content.split(";") if part.strip()]
        return self.execute_queries([f"{statement};" for statement in statements])

    def sync_directory_snapshot(self, snapshot: DirectorySnapshot, *, replace: bool = True) -> dict[str, Any]:
        """Upsert AD topology nodes/relationships from an enumeration snapshot."""

        driver = self._get_driver()
        errors: list[str] = []
        counts = {
            "users": 0,
            "groups": 0,
            "computers": 0,
            "trusts": 0,
            "memberships": 0,
            "domain": 0,
        }

        with driver.session(database=self.settings.neo4j_database) as session:
            try:
                if replace:
                    session.run(
                        """
                        MATCH (n)
                        WHERE any(label IN labels(n) WHERE label IN $labels)
                        DETACH DELETE n
                        """,
                        labels=list(AD_LABELS),
                    )
                session.run(
                    """
                    MERGE (d:ADDomain {dn: $dn})
                    SET d.name = $name,
                        d.domain = $domain,
                        d.enumerated_at = $enumerated_at,
                        d.color = 'slate',
                        d.role = 'Directory domain'
                    """,
                    dn=snapshot.base_dn,
                    name=snapshot.domain or snapshot.base_dn,
                    domain=snapshot.domain,
                    enumerated_at=snapshot.enumerated_at,
                )
                counts["domain"] = 1

                for user in snapshot.users:
                    session.run(
                        """
                        MERGE (u:ADUser {dn: $dn})
                        SET u.name = $name,
                            u.sam_account_name = $name,
                            u.display_name = $display_name,
                            u.mail = $mail,
                            u.description = $description,
                            u.enabled = $enabled,
                            u.color = 'slate',
                            u.role = 'Directory user',
                            u.object_type = 'ADUser'
                        WITH u
                        MATCH (d:ADDomain {dn: $base_dn})
                        MERGE (u)-[:IN_DOMAIN]->(d)
                        """,
                        dn=user.dn,
                        name=user.name,
                        display_name=user.attributes.get("display_name", user.name),
                        mail=user.attributes.get("mail", ""),
                        description=user.attributes.get("description", ""),
                        enabled=bool(user.attributes.get("enabled", True)),
                        base_dn=snapshot.base_dn,
                    )
                    counts["users"] += 1

                for group in snapshot.groups:
                    session.run(
                        """
                        MERGE (g:ADGroup {dn: $dn})
                        SET g.name = $name,
                            g.sam_account_name = $name,
                            g.description = $description,
                            g.color = 'slate',
                            g.role = 'Directory group',
                            g.object_type = 'ADGroup'
                        WITH g
                        MATCH (d:ADDomain {dn: $base_dn})
                        MERGE (g)-[:IN_DOMAIN]->(d)
                        """,
                        dn=group.dn,
                        name=group.name,
                        description=group.attributes.get("description", ""),
                        base_dn=snapshot.base_dn,
                    )
                    counts["groups"] += 1

                for computer in snapshot.computers:
                    session.run(
                        """
                        MERGE (c:ADComputer {dn: $dn})
                        SET c.name = $name,
                            c.sam_account_name = $name,
                            c.dns_hostname = $dns_hostname,
                            c.operating_system = $operating_system,
                            c.description = $description,
                            c.enabled = $enabled,
                            c.color = 'slate',
                            c.role = 'Directory computer',
                            c.object_type = 'ADComputer'
                        WITH c
                        MATCH (d:ADDomain {dn: $base_dn})
                        MERGE (c)-[:IN_DOMAIN]->(d)
                        """,
                        dn=computer.dn,
                        name=computer.name,
                        dns_hostname=computer.attributes.get("dns_hostname", ""),
                        operating_system=computer.attributes.get("operating_system", ""),
                        description=computer.attributes.get("description", ""),
                        enabled=bool(computer.attributes.get("enabled", True)),
                        base_dn=snapshot.base_dn,
                    )
                    counts["computers"] += 1

                for trust in snapshot.trusts:
                    session.run(
                        """
                        MERGE (t:ADTrust {dn: $dn})
                        SET t.name = $name,
                            t.partner = $partner,
                            t.direction = $direction,
                            t.color = 'amber',
                            t.role = 'Directory trust',
                            t.object_type = 'ADTrust'
                        WITH t
                        MATCH (d:ADDomain {dn: $base_dn})
                        MERGE (d)-[:TRUSTS {direction: $direction}]->(t)
                        """,
                        dn=trust.dn,
                        name=trust.name,
                        partner=trust.partner,
                        direction=trust.direction,
                        base_dn=snapshot.base_dn,
                    )
                    counts["trusts"] += 1

                for membership in snapshot.memberships:
                    result = session.run(
                        """
                        MATCH (member) WHERE member.dn = $member_dn
                        MATCH (group:ADGroup {dn: $group_dn})
                        MERGE (member)-[:MEMBER_OF]->(group)
                        RETURN count(*) AS linked
                        """,
                        member_dn=membership.member_dn,
                        group_dn=membership.group_dn,
                    ).single()
                    if result and int(result["linked"]) > 0:
                        counts["memberships"] += 1
            except Exception as exc:
                errors.append(str(exc))

        health = self.health()
        return {
            "success": not errors,
            "counts": counts,
            "errors": errors,
            "node_count": health.node_count,
            "ad_count": health.ad_count,
            "honey_count": health.honey_count,
            "truncated": snapshot.truncated,
            "domain": snapshot.domain,
            "base_dn": snapshot.base_dn,
            "enumerated_at": snapshot.enumerated_at,
        }
