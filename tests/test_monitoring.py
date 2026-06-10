"""Tests for the monitoring engine and monitoring API routes."""

from __future__ import annotations

import unittest

from app.core.monitoring_engine import MonitoringEngine


HONEY_OBJECTS = [
    {
        "object_type": "HoneyUser",
        "name": "alex.hale",
        "attributes": {"display_name": "Alex Hale"},
    },
    {
        "object_type": "HoneyServer",
        "name": "FILE01",
        "attributes": {"spns": ["HTTP/FILE01.lab.local", "MSSQLSvc/FILE01.lab.local:1433"]},
    },
    {
        "object_type": "Breadcrumb",
        "name": "canary-seed-1",
        "attributes": {"artifact_type": "registry_key"},
    },
]


class MonitoringEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MonitoringEngine(seed=7)

    def test_baseline_events_seeded(self) -> None:
        events = self.engine.list_events(limit=100)
        self.assertGreater(len(events), 0)
        self.assertTrue(all(not event["honey_object"] for event in events))

    def test_simulate_requires_registration(self) -> None:
        with self.assertRaises(ValueError):
            self.engine.simulate_honey_interaction()

    def test_simulate_generates_correlated_events(self) -> None:
        registered = self.engine.register_deployment(HONEY_OBJECTS)
        self.assertEqual(registered, 3)

        created = self.engine.simulate_honey_interaction(count=5)
        self.assertEqual(len(created), 5)
        honey_names = {item["name"] for item in HONEY_OBJECTS}
        for event in created:
            self.assertIn(event["honey_object"], honey_names)
            self.assertIn(event["severity"], {"critical", "high"})
            self.assertIn(event["event_id"], {4768, 4769, 4625, 4624})

    def test_filters(self) -> None:
        self.engine.register_deployment(HONEY_OBJECTS)
        self.engine.simulate_honey_interaction(count=4)

        honey_only = self.engine.list_events(honey_only=True, limit=100)
        self.assertEqual(len(honey_only), 4)

        critical = self.engine.list_events(severity="critical", limit=100)
        self.assertTrue(all(event["severity"] == "critical" for event in critical))

        tgt_events = self.engine.list_events(event_id=4768, limit=100)
        self.assertTrue(all(event["event_id"] == 4768 for event in tgt_events))

    def test_stats_and_acknowledge(self) -> None:
        self.engine.register_deployment(HONEY_OBJECTS)
        created = self.engine.simulate_honey_interaction(count=3)

        stats = self.engine.stats()
        self.assertEqual(stats["honey_triggers"], 3)
        self.assertEqual(stats["unacknowledged"], 3)
        self.assertEqual(stats["registered_honey_objects"], 3)

        self.assertTrue(self.engine.acknowledge(created[0]["uid"]))
        self.assertEqual(self.engine.stats()["unacknowledged"], 2)

        self.assertEqual(self.engine.acknowledge_all(), 2)
        self.assertEqual(self.engine.stats()["unacknowledged"], 0)

    def test_acknowledge_unknown_uid(self) -> None:
        self.assertFalse(self.engine.acknowledge(99999))

    def test_event_cap(self) -> None:
        self.engine.register_deployment(HONEY_OBJECTS)
        for _ in range(40):
            self.engine.simulate_honey_interaction(count=10)
        self.assertLessEqual(self.engine.stats()["total_events"], MonitoringEngine.MAX_EVENTS)


def _httpx_available() -> bool:
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_httpx_available(), "httpx is required for API integration tests")
class MonitoringApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app, monitoring_engine

        self.client = TestClient(app)
        self.engine = monitoring_engine

    def _login(self) -> None:
        response = self.client.post(
            "/login",
            data={"username": "HwatSauce", "password": "Active-Decoy!2026"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_events_require_auth(self) -> None:
        response = self.client.get("/api/monitoring/events")
        self.assertEqual(response.status_code, 401)

    def test_events_feed(self) -> None:
        self._login()
        response = self.client.get("/api/monitoring/events")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("events", payload)
        self.assertIn("stats", payload)
        self.assertGreater(payload["stats"]["total_events"], 0)

    def test_deploy_then_simulate_and_acknowledge(self) -> None:
        self._login()

        deploy = self.client.post(
            "/api/deception/deploy",
            data={"modules": ["honey_users", "honey_servers"], "sync_to_graph": "false"},
        )
        self.assertEqual(deploy.status_code, 200)
        self.assertGreater(deploy.json()["monitored_objects"], 0)

        simulate = self.client.post("/api/monitoring/simulate", data={"count": "3"})
        self.assertEqual(simulate.status_code, 200)
        sim_payload = simulate.json()
        self.assertTrue(sim_payload["success"])
        self.assertEqual(len(sim_payload["events"]), 3)

        honey = self.client.get("/api/monitoring/events", params={"honey_only": "true"})
        self.assertGreaterEqual(len(honey.json()["events"]), 3)

        ack = self.client.post("/api/monitoring/acknowledge", data={"ack_all": "true"})
        self.assertTrue(ack.json()["success"])
        self.assertEqual(ack.json()["stats"]["unacknowledged"], 0)

    def test_monitoring_page_renders(self) -> None:
        self._login()
        response = self.client.get("/monitoring")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Event stream", response.text)
        self.assertIn("Simulate interaction", response.text)


if __name__ == "__main__":
    unittest.main()
