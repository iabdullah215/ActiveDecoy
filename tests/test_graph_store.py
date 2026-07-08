"""GraphStore tests using a fake Neo4j driver (no live Database required)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from app.core.directory_enumerator import (
    DirectoryMembership,
    DirectoryObject,
    DirectorySnapshot,
    DirectoryTrust,
)
from app.core.graph_store import GraphStore
from tests.test_config import _settings


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None, single_row: dict[str, Any] | None = None) -> None:
        self._rows = rows or ([] if single_row is None else [single_row])
        self._single = single_row if single_row is not None else (self._rows[0] if self._rows else None)

    def single(self) -> dict[str, Any] | None:
        return self._single

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def run(self, query: str, **params: Any) -> _FakeResult:
        self.calls.append((query, params))
        q = " ".join(query.split())
        if "RETURN count(n) AS count" in q:
            labels = params.get("labels") or []
            if any(str(item).startswith("Honey") for item in labels):
                return _FakeResult(single_row={"count": 2})
            return _FakeResult(single_row={"count": 5})
        if "RETURN elementId(n) AS id" in q:
            return _FakeResult(
                rows=[
                    {
                        "id": "n1",
                        "object_type": "HoneyUser",
                        "name": "hw_alex.hale",
                        "role": "bait",
                        "color": "blue",
                        "dn": "",
                        "enabled": False,
                    },
                    {
                        "id": "n2",
                        "object_type": "ADUser",
                        "name": "jdoe",
                        "role": "Directory user",
                        "color": "slate",
                        "dn": "CN=jdoe,DC=lab,DC=local",
                        "enabled": True,
                    },
                ]
            )
        if "type(r) AS rel_type" in q:
            return _FakeResult(
                rows=[
                    {"source": "n1", "target": "n2", "rel_type": "MEMBER_OF"},
                    {"source": "n9", "target": "n2", "rel_type": "IGNORED"},
                ]
            )
        if "RETURN count(*) AS linked" in q:
            return _FakeResult(single_row={"linked": 1})
        return _FakeResult(single_row={})


class _FakeDriver:
    def __init__(self) -> None:
        self.session_obj = _FakeSession()
        self.closed = False
        self.verified = False

    def verify_connectivity(self) -> None:
        self.verified = True

    def session(self, database: str | None = None) -> _FakeSession:
        return self.session_obj

    def close(self) -> None:
        self.closed = True


class GraphStoreTests(unittest.TestCase):
    def test_health_when_not_configured(self) -> None:
        store = GraphStore(_settings(neo4j_password=""))
        health = store.health()
        self.assertFalse(health.configured)
        self.assertFalse(health.connected)

    def test_health_connected_with_fake_driver(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))
        fake = _FakeDriver()
        store._driver = fake
        health = store.health()
        self.assertTrue(health.configured)
        self.assertTrue(health.connected)
        self.assertEqual(health.honey_count, 2)
        self.assertEqual(health.ad_count, 5)
        self.assertEqual(health.node_count, 7)
        self.assertTrue(fake.verified)

    def test_health_reports_failure(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))

        class Boom:
            def verify_connectivity(self) -> None:
                raise RuntimeError("bolt down")

        store._driver = Boom()
        health = store.health()
        self.assertTrue(health.configured)
        self.assertFalse(health.connected)
        self.assertIn("bolt down", health.message)

    def test_execute_queries(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))
        fake = _FakeDriver()
        store._driver = fake
        result = store.execute_queries(["MERGE (n:HoneyUser {name:'a'});", "  ;", "RETURN 1;"])
        self.assertTrue(result["success"])
        self.assertEqual(result["executed"], 2)

    def test_execute_queries_unconfigured_raises(self) -> None:
        store = GraphStore(_settings(neo4j_password=""))
        with self.assertRaises(RuntimeError):
            store.execute_queries(["RETURN 1"])

    def test_fetch_nodes_and_topology(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))
        fake = _FakeDriver()
        store._driver = fake
        nodes = store.fetch_honey_nodes()
        self.assertEqual(len(nodes), 2)
        topology = store.fetch_topology(labels=("HoneyUser", "ADUser"))
        self.assertEqual(len(topology["nodes"]), 2)
        self.assertEqual(len(topology["edges"]), 1)
        self.assertEqual(topology["edges"][0]["rel_type"], "MEMBER_OF")

    def test_import_cypher_file(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))
        store._driver = _FakeDriver()
        result = store.import_cypher_file("CREATE (a); CREATE (b);")
        self.assertEqual(result["executed"], 2)

    def test_sync_directory_snapshot(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))
        fake = _FakeDriver()
        store._driver = fake
        snapshot = DirectorySnapshot(
            enumerated_at="2026-07-08T00:00:00+00:00",
            base_dn="DC=lab,DC=local",
            domain="lab.local",
            users=[
                DirectoryObject("ADUser", "jdoe", "CN=jdoe,DC=lab,DC=local", {"enabled": True})
            ],
            groups=[
                DirectoryObject("ADGroup", "Domain Admins", "CN=Domain Admins,DC=lab,DC=local", {})
            ],
            computers=[
                DirectoryObject("ADComputer", "DC01$", "CN=DC01,DC=lab,DC=local", {"enabled": True})
            ],
            memberships=[
                DirectoryMembership("CN=jdoe,DC=lab,DC=local", "CN=Domain Admins,DC=lab,DC=local")
            ],
            trusts=[
                DirectoryTrust("partner.local", "CN=partner.local,DC=lab,DC=local", "bidirectional", "partner.local")
            ],
        )
        result = store.sync_directory_snapshot(snapshot, replace=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["counts"]["users"], 1)
        self.assertEqual(result["counts"]["groups"], 1)
        self.assertEqual(result["counts"]["computers"], 1)
        self.assertEqual(result["counts"]["trusts"], 1)
        self.assertEqual(result["counts"]["memberships"], 1)
        self.assertGreaterEqual(len(fake.session_obj.calls), 6)

    def test_close_resets_driver(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))
        fake = _FakeDriver()
        store._driver = fake
        store.close()
        self.assertTrue(fake.closed)
        self.assertIsNone(store._driver)

    def test_get_driver_uses_neo4j_module(self) -> None:
        store = GraphStore(_settings(neo4j_password="secret"))
        fake = _FakeDriver()

        class FakeGraphDatabase:
            @staticmethod
            def driver(uri: str, auth: Any = None) -> _FakeDriver:
                return fake

        with patch.dict("sys.modules", {"neo4j": type("M", (), {"GraphDatabase": FakeGraphDatabase})()}):
            driver = store._get_driver()
        self.assertIs(driver, fake)


if __name__ == "__main__":
    unittest.main()
