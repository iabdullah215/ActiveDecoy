"""Tests for Washu Agent registry, heartbeat API, and agent package."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.agent_registry import AgentRegistry
from app.main import app, settings
from washu_agent.collectors import DemoCollector, FileEventCollector, _normalize_payload
from washu_agent.config import AgentConfig
from washu_agent.service import AgentService


class AgentRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "agents.json"
        self.registry = AgentRegistry(store_path=self.path, stale_seconds=60)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_heartbeat_persists_and_lists_healthy(self) -> None:
        record = self.registry.heartbeat(
            agent_id="washu-1",
            hostname="monitor-vm",
            version="0.9.0",
            vm_name="Washu-DC",
            status="ok",
        )
        self.assertEqual(record["health"], "healthy")
        self.assertTrue(self.path.exists())
        summary = self.registry.summary()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["healthy"], 1)

    def test_note_ingest_increments(self) -> None:
        self.registry.heartbeat(agent_id="washu-1")
        self.registry.note_ingest("washu-1", 3)
        row = self.registry.get("washu-1")
        assert row is not None
        self.assertEqual(row["events_forwarded"], 3)

    def test_stale_when_old_last_seen(self) -> None:
        self.registry.heartbeat(agent_id="old-agent")
        with self.registry._lock:
            self.registry._agents["old-agent"].last_seen = "2020-01-01T00:00:00+00:00"
        row = self.registry.get("old-agent")
        assert row is not None
        self.assertEqual(row["health"], "stale")


class AgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._token = settings.agent_ingest_token
        object.__setattr__(settings, "agent_ingest_token", "agent-test-token")

    def tearDown(self) -> None:
        object.__setattr__(settings, "agent_ingest_token", self._token)

    def test_heartbeat_requires_token(self) -> None:
        response = self.client.post(
            "/api/agents/heartbeat",
            json={"agent_id": "washu-agent", "status": "ok"},
        )
        self.assertEqual(response.status_code, 401)

    def test_heartbeat_registers_agent(self) -> None:
        response = self.client.post(
            "/api/agents/heartbeat",
            json={
                "agent_id": "washu-lab",
                "hostname": "washu-host",
                "vm_name": "Washu-DC",
                "version": "0.9.0",
                "status": "ok",
                "capability": ["demo"],
                "events_forwarded": 2,
            },
            headers={"X-Agent-Token": "agent-test-token"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["agent"]["health"], "healthy")
        self.assertEqual(body["agent"]["agent_id"], "washu-lab")

    def test_list_agents_requires_auth(self) -> None:
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 401)

    def test_list_agents_when_authenticated(self) -> None:
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "changeme-dev-only"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        self.client.post(
            "/api/agents/heartbeat",
            json={"agent_id": "listed-agent", "status": "ok"},
            headers={"X-Agent-Token": "agent-test-token"},
        )
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["total"], 1)
        self.assertIn("registered_vm_name", body)

    def test_monitoring_page_includes_agent_card(self) -> None:
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "changeme-dev-only"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        page = self.client.get("/monitoring")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Washu Agent", page.text)
        self.assertIn("data-agent-list", page.text)


class WashuAgentPackageTests(unittest.TestCase):
    def test_normalize_payload(self) -> None:
        event = _normalize_payload(
            {
                "event_id": 4769,
                "actor": "WKS-1",
                "target": "hw_sql.svc",
                "description": "Service ticket",
            },
            agent_id="a1",
        )
        assert event is not None
        self.assertEqual(event.severity, "high")
        self.assertEqual(event.agent_id, "a1")

    def test_file_collector_reads_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.ndjson"
            path.write_text(
                json.dumps(
                    {
                        "event_id": 4625,
                        "actor": "10.0.0.8",
                        "target": "hw_alex.hale",
                        "description": "Failed logon",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            # Start at EOF then rewrite so poll sees new bytes
            collector = FileEventCollector(path, agent_id="file-agent")
            path.write_text(
                json.dumps(
                    {
                        "event_id": 4625,
                        "actor": "10.0.0.8",
                        "target": "hw_alex.hale",
                        "description": "Failed logon",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            collector._offset = 0
            events = collector.poll()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_id, 4625)

    def test_demo_collector_emits(self) -> None:
        collector = DemoCollector(("hw_alex.hale",), agent_id="demo")
        first = collector.poll()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].target, "hw_alex.hale")

    def test_service_run_once_dry_run(self) -> None:
        config = AgentConfig(
            console_url="http://127.0.0.1:8000",
            ingest_token="unused",
            agent_id="dry-agent",
            hostname="lab",
            vm_name="Washu-DC",
            heartbeat_interval=30,
            poll_interval=10,
            event_source="demo",
            event_log_path="",
            honey_targets=("hw_alex.hale",),
            dry_run=True,
        )
        service = AgentService(config)
        result = service.run_once()
        self.assertIn("heartbeat", result)
        self.assertTrue(result["heartbeat"].get("dry_run"))


if __name__ == "__main__":
    unittest.main()
