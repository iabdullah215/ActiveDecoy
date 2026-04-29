"""Deception planning utilities for ActiveDecoy.

The engine generates structured honey-object plans and Neo4j/Cypher payloads
for authorized lab environments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import random
from typing import Any


@dataclass
class HoneyObject:
    object_type: str
    name: str
    role: str
    color: str = "blue"
    notes: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeceptionDeployment:
    created_at: str
    selected_modules: list[str]
    objects: list[HoneyObject]
    cypher_queries: list[str]


class DeceptionEngine:
    """Builds honey-object plans and graph payloads."""

    FIRST_NAMES = [
        "Alex",
        "Jordan",
        "Morgan",
        "Taylor",
        "Avery",
        "Casey",
        "Drew",
        "Quinn",
    ]

    LAST_NAMES = [
        "Hale",
        "Warren",
        "Stone",
        "Parker",
        "Reed",
        "Brooks",
        "Miller",
        "Carter",
    ]

    SERVER_NAMES = ["FILE", "APP", "JUMP", "OPS", "LOG", "VAULT", "ARCHIVE"]

    def __init__(self, seed: int | None = None) -> None:
        self.random = random.Random(seed)

    def build_deployment(self, selections: list[str]) -> DeceptionDeployment:
        modules = [selection for selection in selections if selection]
        objects: list[HoneyObject] = []
        cypher_queries: list[str] = []

        if "honey_users" in modules:
            objects.extend(self.generate_honey_users(3))
        if "honey_servers" in modules:
            objects.extend(self.generate_honey_servers(2))
        if "honey_dc" in modules:
            objects.append(self.generate_shadow_dc())
        if "breadcrumbs" in modules:
            objects.extend(self.generate_breadcrumb_nodes(3))

        for honey_object in objects:
            cypher_queries.append(self.to_cypher(honey_object))

        return DeceptionDeployment(
            created_at=datetime.now(timezone.utc).isoformat(),
            selected_modules=modules,
            objects=objects,
            cypher_queries=cypher_queries,
        )

    def generate_honey_users(self, count: int) -> list[HoneyObject]:
        users: list[HoneyObject] = []
        for _ in range(count):
            first = self.random.choice(self.FIRST_NAMES)
            last = self.random.choice(self.LAST_NAMES)
            name = f"{first.lower()}.{last.lower()}"
            users.append(
                HoneyObject(
                    object_type="HoneyUser",
                    name=name,
                    role="Privilege bait account",
                    notes="Provisioned with deny-logon controls and alerting hooks.",
                    attributes={
                        "display_name": f"{first} {last}",
                        "status": "inactive",
                        "color": "blue",
                    },
                )
            )
        return users

    def generate_honey_servers(self, count: int) -> list[HoneyObject]:
        servers: list[HoneyObject] = []
        for index in range(count):
            prefix = self.random.choice(self.SERVER_NAMES)
            hostname = f"{prefix}{index + 1:02d}"
            servers.append(
                HoneyObject(
                    object_type="HoneyServer",
                    name=hostname,
                    role="Kerberoasting bait",
                    notes="Includes fake service principal names and monitoring tags.",
                    attributes={
                        "spns": [f"HTTP/{hostname}.lab.local", f"MSSQLSvc/{hostname}.lab.local:1433"],
                        "color": "blue",
                    },
                )
            )
        return servers

    def generate_shadow_dc(self) -> HoneyObject:
        return HoneyObject(
            object_type="HoneyDC",
            name="shadow-dc01",
            role="Deceptive directory controller advertisement",
            notes="Advertises a monitored DC persona without participating in real replication.",
            attributes={"color": "blue", "visibility": "covert"},
        )

    def generate_breadcrumb_nodes(self, count: int) -> list[HoneyObject]:
        breadcrumbs: list[HoneyObject] = []
        for index in range(count):
            breadcrumbs.append(
                HoneyObject(
                    object_type="Breadcrumb",
                    name=f"canary-seed-{index + 1}",
                    role="Decoy credential or registry breadcrumb",
                    notes="Tracks interaction attempts from hostile or accidental discovery.",
                    attributes={
                        "artifact_type": self.random.choice(["registry_key", "flat_file", "share_marker"]),
                        "color": "blue",
                    },
                )
            )
        return breadcrumbs

    def to_cypher(self, honey_object: HoneyObject) -> str:
        properties = {
            "name": honey_object.name,
            "role": honey_object.role,
            "color": honey_object.color,
            "notes": honey_object.notes,
            **honey_object.attributes,
        }

        property_string = ", ".join(
            f"{key}: {self._cypher_value(value)}" for key, value in properties.items()
        )
        return f"MERGE (n:{honey_object.object_type} {{name: {self._cypher_value(honey_object.name)}}}) SET n += {{{property_string}}};"

    def summarize_graph_rows(self, objects: list[HoneyObject]) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "role": item.role,
                "color": item.color,
                "object_type": item.object_type,
            }
            for item in objects
        ]

    def _cypher_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            return "[" + ", ".join(self._cypher_value(item) for item in value) + "]"
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"


def deployment_to_dict(deployment: DeceptionDeployment) -> dict[str, Any]:
    return {
        "created_at": deployment.created_at,
        "selected_modules": deployment.selected_modules,
        "objects": [asdict(item) for item in deployment.objects],
        "cypher_queries": deployment.cypher_queries,
    }
