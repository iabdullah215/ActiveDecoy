"""Tests for monitoring ingest, correlation, persistence, and SSE."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.monitoring_engine import MonitoringEngine


HONEY_OBJECTS = [
    {
        "object_type": "HoneyUser",
        "name": "hw_alex.hale",
        "attributes": {"display_name": "Alex Hale"},
    },
    {
        "object_type": "HoneyServer",
        "name": "FILE01",
        "attributes": {"spns": ["HTTP/FILE01.lab.local"]},
    },
]


class MonitoringIngestUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "events.json"
        self.engine = MonitoringEngine(seed=3, store_path=self.store_path, seed_baseline=False)

    def test_ingest_correlates_honey_user(self) -> None:
        self.engine.register_deployment(HONEY_OBJECTS)
        result = self.engine.ingest_events(
            [
                {
                    "event_id": 4768,
                    "actor": "WKS-031",
                    "target": "hw_alex.hale",
                    "severity": "info",
                    "source": "Domain Controller",
                    "description": "TGT requested",
                }
            ],
            agent_id="lab-agent",
        )
        self.assertEqual(result["accepted"], 1)
        event = result["events"][0]
        self.assertEqual(event["honey_object"], "hw_alex.hale")
        self.assertEqual(event["severity"], "critical")
        self.assertTrue(event["ingested"])
        self.assertEqual(self.engine.stats()["ingested_events"], 1)

    def test_persistence_roundtrip(self) -> None:
        self.engine.register_deployment(HONEY_OBJECTS)
        self.engine.record_event(
            4625,
            "medium",
            "Security Log",
            "10.10.14.7",
            "hw_alex.hale",
            "failed",
            ingested=True,
            agent_id="a1",
        )
        restored = MonitoringEngine(seed=1, store_path=self.store_path, seed_baseline=False)
        self.assertGreaterEqual(restored.stats()["total_events"], 1)
        self.assertEqual(len(restored.registered_honey_objects), 2)
        honey = restored.list_events(honey_only=True, limit=10)
        self.assertTrue(any(event["honey_object"] == "hw_alex.hale" for event in honey))

    def test_subscribe_notified(self) -> None:
        seen: list[dict] = []
        self.engine.subscribe(seen.append)
        self.engine.record_event(4624, "info", "Workstation", "j.doe", "WKS-014", "ok")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["event_id"], 4624)


def _httpx_available() -> bool:
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_httpx_available(), "httpx is required for API integration tests")
class MonitoringIngestApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app, login_rate_limiter, monitoring_engine, settings

        self.client = TestClient(app)
        self.engine = monitoring_engine
        self.settings = settings
        login_rate_limiter.reset("testclient")
        self.engine.register_deployment(HONEY_OBJECTS)

    def test_ingest_disabled_without_token(self) -> None:
        object.__setattr__(self.settings, "agent_ingest_token", "")
        response = self.client.post(
            "/api/monitoring/ingest",
            json={
                "agent_id": "agent-1",
                "events": [
                    {
                        "event_id": 4625,
                        "actor": "host",
                        "target": "hw_alex.hale",
                    }
                ],
            },
            headers={"X-Agent-Token": "x"},
        )
        self.assertEqual(response.status_code, 503)

    def test_ingest_rejects_bad_token(self) -> None:
        object.__setattr__(self.settings, "agent_ingest_token", "good-token")
        response = self.client.post(
            "/api/monitoring/ingest",
            json={
                "agent_id": "agent-1",
                "events": [{"event_id": 4625, "actor": "host", "target": "user"}],
            },
            headers={"X-Agent-Token": "bad-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_ingest_accepts_valid_token(self) -> None:
        object.__setattr__(self.settings, "agent_ingest_token", "good-token")
        response = self.client.post(
            "/api/monitoring/ingest",
            json={
                "agent_id": "agent-1",
                "events": [
                    {
                        "event_id": 4768,
                        "actor": "WKS-031",
                        "target": "hw_alex.hale",
                        "severity": "info",
                        "source": "Domain Controller",
                        "description": "TGT",
                    }
                ],
            },
            headers={"X-Agent-Token": "good-token"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["accepted"], 1)
        self.assertEqual(payload["events"][0]["honey_object"], "hw_alex.hale")
        object.__setattr__(self.settings, "agent_ingest_token", "")

    def test_stream_requires_auth(self) -> None:
        response = self.client.get("/api/monitoring/stream")
        self.assertEqual(response.status_code, 401)

    def test_stream_ready_when_authenticated(self) -> None:
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "changeme-dev-only"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        response = self.client.get("/api/monitoring/stream?once=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        self.assertIn("event: ready", response.text)


if __name__ == "__main__":
    unittest.main()
