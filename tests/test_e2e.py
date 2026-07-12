"""End-to-end API workflow and concurrency tests."""

from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.agent_registry import AgentRegistry
from app.core.monitoring_engine import MonitoringEngine
from app.main import app, settings


class EndToEndWorkflowTests(unittest.TestCase):
    """connect → deploy → simulate/ingest event → ack."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "changeme-dev-only"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)

    def test_connect_deploy_simulate_ack(self) -> None:
        save = self.client.post(
            "/api/connection/save",
            data={
                "ldap_host": "dc01.lab.local",
                "ldap_port": "389",
                "ldap_use_ssl": "false",
                "ldap_bind_dn": "CN=admin,DC=lab,DC=local",
                "ldap_password": "lab-pass",
                "ldap_base_dn": "DC=lab,DC=local",
                "hypervisor_type": "vmware",
                "hypervisor_endpoint": "",
                "hypervisor_username": "",
                "hypervisor_password": "",
                "hypervisor_vm_name": "Washu-DC",
            },
        )
        self.assertEqual(save.status_code, 200)
        self.assertTrue(save.json()["success"])

        profile = self.client.get("/api/connection/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["profile"]["ldap_host"], "dc01.lab.local")

        deploy = self.client.post(
            "/api/deception/deploy",
            data={
                "modules": ["honey_users", "honey_servers"],
                "sync_to_graph": "false",
                "provision_ad": "false",
                "dry_run": "false",
            },
        )
        self.assertEqual(deploy.status_code, 200)
        body = deploy.json()
        self.assertTrue(body["success"])
        self.assertGreaterEqual(len(body["objects"]), 5)
        self.assertIn("policy", body)

        simulate = self.client.post("/api/monitoring/simulate", data={"count": "2"})
        self.assertEqual(simulate.status_code, 200)
        sim = simulate.json()
        self.assertTrue(sim["success"])
        self.assertGreaterEqual(len(sim["events"]), 1)
        honey_uid = sim["events"][0]["uid"]

        events = self.client.get("/api/monitoring/events", params={"honey_only": "true", "limit": 20})
        self.assertEqual(events.status_code, 200)
        feed = events.json()["events"]
        self.assertTrue(any(item["uid"] == honey_uid for item in feed))

        ack = self.client.post("/api/monitoring/acknowledge", data={"uid": str(honey_uid)})
        self.assertEqual(ack.status_code, 200)
        self.assertTrue(ack.json()["success"])

        playbook = self.client.get("/api/policy/playbook", params={"uid": honey_uid})
        self.assertEqual(playbook.status_code, 200)
        self.assertIn("playbook", playbook.json())

        export = self.client.get(
            "/api/policy/export",
            params={"format": "json", "honey_only": "true", "exclude_baseline": "true"},
        )
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export.json()["format"], "activedecoy.alerts.json.v1")

    def test_ingest_then_ack_with_token(self) -> None:
        prior = settings.agent_ingest_token
        object.__setattr__(settings, "agent_ingest_token", "e2e-token")
        try:
            deploy = self.client.post(
                "/api/deception/deploy",
                data={"modules": ["honey_users"], "sync_to_graph": "false", "provision_ad": "false"},
            )
            honey_name = deploy.json()["objects"][0]["name"]
            ingest = self.client.post(
                "/api/monitoring/ingest",
                headers={"X-Agent-Token": "e2e-token"},
                json={
                    "agent_id": "e2e-agent",
                    "events": [
                        {
                            "event_id": 4768,
                            "actor": "WKS-E2E",
                            "target": honey_name,
                            "severity": "high",
                            "description": "E2E TGT",
                        }
                    ],
                },
            )
            self.assertEqual(ingest.status_code, 200)
            accepted = ingest.json()["events"]
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0]["honey_object"], honey_name)

            heartbeat = self.client.post(
                "/api/agents/heartbeat",
                headers={"X-Agent-Token": "e2e-token"},
                json={"agent_id": "e2e-agent", "status": "ok", "vm_name": "Washu-DC"},
            )
            self.assertEqual(heartbeat.status_code, 200)
            self.assertEqual(heartbeat.json()["agent"]["health"], "healthy")

            ack = self.client.post(
                "/api/monitoring/acknowledge",
                data={"uid": str(accepted[0]["uid"])},
            )
            self.assertTrue(ack.json()["success"])
        finally:
            object.__setattr__(settings, "agent_ingest_token", prior)


class ConcurrencyTests(unittest.TestCase):
    def test_monitoring_engine_concurrent_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = MonitoringEngine(
                seed=3,
                store_path=Path(tmp) / "events.json",
                seed_baseline=False,
            )
            engine.register_deployment(
                [{"object_type": "HoneyUser", "name": "hw_concurrent", "attributes": {}}]
            )

            def worker(idx: int) -> int:
                result = engine.ingest_events(
                    [
                        {
                            "event_id": 4625,
                            "actor": f"host-{idx}",
                            "target": "hw_concurrent",
                            "severity": "medium",
                            "description": f"spray {idx}",
                        }
                    ],
                    agent_id=f"agent-{idx % 3}",
                )
                return int(result.get("accepted") or 0)

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(worker, i) for i in range(40)]
                accepted = sum(future.result() for future in as_completed(futures))

            self.assertEqual(accepted, 40)
            events = engine.list_events(honey_only=True, limit=500)
            self.assertEqual(len(events), 40)
            stats = engine.stats()
            self.assertEqual(stats["ingested_events"], 40)
            self.assertEqual(stats["honey_triggers"], 40)

    def test_agent_registry_concurrent_heartbeats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = AgentRegistry(store_path=Path(tmp) / "agents.json", stale_seconds=60)
            errors: list[BaseException] = []

            def beat(idx: int) -> None:
                try:
                    registry.heartbeat(
                        agent_id=f"agent-{idx % 5}",
                        hostname=f"host-{idx}",
                        status="ok",
                        events_forwarded=idx,
                    )
                    registry.note_ingest(f"agent-{idx % 5}", 1)
                except BaseException as exc:  # noqa: BLE001 - collect for thread assertion
                    errors.append(exc)

            threads = [threading.Thread(target=beat, args=(i,)) for i in range(50)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            summary = registry.summary()
            self.assertEqual(summary["total"], 5)
            self.assertEqual(summary["healthy"], 5)


if __name__ == "__main__":
    unittest.main()
