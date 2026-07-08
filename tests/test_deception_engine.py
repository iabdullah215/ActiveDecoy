"""Unit tests for the deception planning engine."""

from __future__ import annotations

import unittest

from app.core.deception_engine import DeceptionEngine, HoneyObject, deployment_to_dict


class DeceptionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DeceptionEngine(seed=7)

    def test_build_deployment_modules(self) -> None:
        deployment = self.engine.build_deployment(
            ["honey_users", "honey_servers", "honey_dc", "breadcrumbs", "ignored"]
        )
        types = {item.object_type for item in deployment.objects}
        self.assertEqual(types, {"HoneyUser", "HoneyServer", "HoneyDC", "Breadcrumb"})
        self.assertEqual(
            deployment.selected_modules,
            ["honey_users", "honey_servers", "honey_dc", "breadcrumbs", "ignored"],
        )
        self.assertEqual(len(deployment.cypher_queries), len(deployment.objects))
        self.assertEqual(sum(1 for item in deployment.objects if item.object_type == "HoneyUser"), 3)
        self.assertEqual(sum(1 for item in deployment.objects if item.object_type == "HoneyServer"), 2)
        self.assertEqual(sum(1 for item in deployment.objects if item.object_type == "HoneyDC"), 1)
        self.assertEqual(sum(1 for item in deployment.objects if item.object_type == "Breadcrumb"), 3)

    def test_seed_is_deterministic(self) -> None:
        a = DeceptionEngine(seed=42).generate_honey_users(2)
        b = DeceptionEngine(seed=42).generate_honey_users(2)
        self.assertEqual([item.name for item in a], [item.name for item in b])

    def test_cypher_escapes_quotes(self) -> None:
        obj = HoneyObject(
            object_type="HoneyUser",
            name="o'brien",
            role="test",
            notes="say 'hello'",
            attributes={"flag": True, "n": 3, "tags": ["a", "b"]},
        )
        query = self.engine.to_cypher(obj)
        self.assertIn("MERGE (n:HoneyUser", query)
        self.assertIn(r"o\'brien", query)
        self.assertIn("true", query)
        self.assertIn("[", query)

    def test_summarize_graph_rows(self) -> None:
        rows = self.engine.summarize_graph_rows(self.engine.generate_honey_servers(1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object_type"], "HoneyServer")
        self.assertIn("name", rows[0])

    def test_deployment_to_dict(self) -> None:
        deployment = self.engine.build_deployment(["honey_users"])
        payload = deployment_to_dict(deployment)
        self.assertIn("objects", payload)
        self.assertEqual(payload["selected_modules"], ["honey_users"])
        self.assertEqual(len(payload["objects"]), 3)
        self.assertEqual(payload["objects"][0]["object_type"], "HoneyUser")

    def test_empty_selection(self) -> None:
        deployment = self.engine.build_deployment([])
        self.assertEqual(deployment.objects, [])
        self.assertEqual(deployment.cypher_queries, [])


if __name__ == "__main__":
    unittest.main()
