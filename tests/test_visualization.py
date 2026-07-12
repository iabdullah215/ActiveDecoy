"""Tests for visualization filters and topology API."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.graph_view import filter_graph_nodes, resolve_graph_kind, topology_payload


SAMPLE_NODES = [
    {
        "id": "1",
        "object_type": "HoneyUser",
        "name": "hw_alex.hale",
        "role": "Privilege bait account",
        "color": "blue",
        "enabled": False,
    },
    {
        "id": "2",
        "object_type": "ADUser",
        "name": "jdoe",
        "role": "Directory user",
        "color": "slate",
        "enabled": True,
    },
    {
        "id": "3",
        "object_type": "ADGroup",
        "name": "Domain Admins",
        "role": "Directory group",
        "color": "slate",
        "enabled": True,
    },
]

SAMPLE_EDGES = [
    {"id": "e1", "source": "2", "target": "3", "rel_type": "MEMBER_OF"},
    {"id": "e2", "source": "1", "target": "3", "rel_type": "RELATED"},
]


class GraphViewHelperTests(unittest.TestCase):
    def test_resolve_kind(self) -> None:
        self.assertEqual(resolve_graph_kind("AD"), "ad")
        self.assertEqual(resolve_graph_kind("nope"), "all")

    def test_filter_by_kind_and_query(self) -> None:
        honey = filter_graph_nodes(SAMPLE_NODES, kind="honey")
        self.assertEqual(len(honey), 1)
        self.assertEqual(honey[0]["name"], "hw_alex.hale")

        named = filter_graph_nodes(SAMPLE_NODES, query="domain")
        self.assertEqual(len(named), 1)
        self.assertEqual(named[0]["object_type"], "ADGroup")

        active = filter_graph_nodes(SAMPLE_NODES, active_only=True)
        self.assertEqual(len(active), 2)

    def test_topology_payload_prunes_edges(self) -> None:
        payload = topology_payload(SAMPLE_NODES, SAMPLE_EDGES, kind="ad")
        self.assertEqual(payload["counts"]["nodes"], 2)
        self.assertEqual(payload["counts"]["edges"], 1)
        self.assertEqual(payload["edges"][0]["rel_type"], "MEMBER_OF")


def _httpx_available() -> bool:
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_httpx_available(), "httpx is required for API integration tests")
class VisualizationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app, login_rate_limiter

        self.client = TestClient(app)
        login_rate_limiter.reset("testclient")

    def _login(self) -> None:
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "changeme-dev-only"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_topology_requires_auth(self) -> None:
        response = self.client.get("/api/graph/topology")
        self.assertEqual(response.status_code, 401)

    def test_topology_preview_without_neo4j(self) -> None:
        self._login()
        # Deploy first so preview has session objects, but topology can also synthesize.
        self.client.post(
            "/api/deception/deploy",
            data={"modules": ["honey_users", "honey_servers"], "sync_to_graph": "false"},
        )
        response = self.client.get("/api/graph/topology", params={"kind": "honey"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["source"], {"preview", "neo4j"})
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)
        self.assertIn("counts", payload)
        self.assertGreaterEqual(len(payload["nodes"]), 1)

    def test_topology_filters_query(self) -> None:
        self._login()
        self.client.post(
            "/api/deception/deploy",
            data={"modules": ["honey_users"], "sync_to_graph": "false"},
        )
        response = self.client.get("/api/graph/topology", params={"kind": "all", "q": "zzzz-missing"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["nodes"], 0)

    def test_visualization_page_renders_canvas(self) -> None:
        self._login()
        page = self.client.get("/visualization")
        self.assertEqual(page.status_code, 200)
        self.assertIn("data-graph-canvas", page.text)
        self.assertIn("Graph filters", page.text)
        self.assertIn("data-action=\"viz-fullscreen\"", page.text)
        self.assertIn("data-action=\"viz-reset-view\"", page.text)

    def test_nodes_endpoint_accepts_filters(self) -> None:
        self._login()
        with patch("app.api.graph.GraphStore.fetch_nodes", create=False):
            response = self.client.get("/api/graph/nodes", params={"kind": "all", "q": "a"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("nodes", response.json())


if __name__ == "__main__":
    unittest.main()
