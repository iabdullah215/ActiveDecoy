"""Tests for policy engine, playbooks, and alert export."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.export import export_json_bundle, export_stix_bundle, export_syslog_lines, render_export
from app.core.monitoring_engine import MonitoringEngine
from app.core.playbooks import playbook_for_event
from app.core.policy import PolicyEngine, domain_from_dn
from app.main import app, settings
from tests.test_config import _settings


class PolicyEngineUnitTests(unittest.TestCase):
    def test_domain_from_dn(self) -> None:
        self.assertEqual(domain_from_dn("OU=Honey,OU=Lab,DC=lab,DC=local"), "lab.local")

    def test_evaluate_warns_without_honey_ou(self) -> None:
        engine = PolicyEngine(_settings(ad_honey_ou=""))
        report = engine.evaluate(provision_ad=False)
        statuses = {item.id: item.status for item in report.checks}
        self.assertEqual(statuses["honey_ou"], "warn")

    def test_gate_blocks_provision_without_ou(self) -> None:
        engine = PolicyEngine(_settings(ad_honey_ou="", ad_require_name_prefix=True, ad_honey_name_prefix="hw_"))
        gate = engine.gate_provision(
            [{"object_type": "HoneyUser", "name": "hw_alex.hale"}],
            dry_run=False,
        )
        self.assertTrue(gate["blocked"])

    def test_gate_allows_dry_run(self) -> None:
        engine = PolicyEngine(_settings(ad_honey_ou=""))
        gate = engine.gate_provision([], dry_run=True)
        self.assertFalse(gate["blocked"])

    def test_stamped_objects_pass_name_check(self) -> None:
        engine = PolicyEngine(
            _settings(
                ad_honey_ou="OU=Honey,DC=lab,DC=local",
                ad_honey_name_prefix="hw_",
                ad_require_name_prefix=True,
                agent_ingest_token="tok",
            )
        )
        report = engine.evaluate(
            objects=[{"object_type": "HoneyUser", "name": "hw_alex.hale"}],
            provision_ad=True,
        )
        self.assertTrue(report.ok)
        name_check = next(item for item in report.checks if item.id == "object_names")
        self.assertEqual(name_check.status, "pass")


class PlaybookTests(unittest.TestCase):
    def test_playbook_for_4769(self) -> None:
        pb = playbook_for_event({"event_id": 4769, "honey_object": "hw_sql$"})
        self.assertEqual(pb["matched_on"], "event_id")
        self.assertIn(4769, pb["event_ids"])


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = [
            {
                "uid": 1,
                "event_id": 4768,
                "severity": "high",
                "actor": "WKS-1",
                "target": "hw_alex.hale",
                "honey_object": "hw_alex.hale",
                "label": "TGT",
                "description": "TGT requested",
                "timestamp": "2026-07-08T12:00:00+00:00",
            }
        ]

    def test_json_bundle(self) -> None:
        bundle = export_json_bundle(self.events)
        self.assertEqual(bundle["count"], 1)

    def test_stix_bundle(self) -> None:
        bundle = export_stix_bundle(self.events)
        self.assertEqual(bundle["type"], "bundle")
        types = {obj["type"] for obj in bundle["objects"]}
        self.assertIn("indicator", types)

    def test_syslog_lines(self) -> None:
        text = export_syslog_lines(self.events)
        self.assertIn("event_id=4768", text)

    def test_render_export_formats(self) -> None:
        body, media, name = render_export(self.events, "stix")
        self.assertIn("application/stix", media)
        self.assertTrue(name.endswith(".json"))
        json.loads(body)


class NoiseSuppressionTests(unittest.TestCase):
    def test_exclude_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = MonitoringEngine(
                seed=1,
                store_path=Path(tmp) / "events.json",
                seed_baseline=True,
            )
            all_events = engine.list_events(limit=100)
            filtered = engine.list_events(exclude_baseline=True, limit=100)
            self.assertGreater(len(all_events), 0)
            self.assertLessEqual(len(filtered), len(all_events))
            for event in filtered:
                self.assertTrue(event["honey_object"] or event["ingested"] or event["agent_id"])


class PolicyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _login(self) -> None:
        login = self.client.post(
            "/login",
            data={"username": "HwatSauce", "password": "Active-Decoy!2026"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)

    def test_policy_page(self) -> None:
        self._login()
        page = self.client.get("/policy")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Deny-logon", page.text)
        self.assertIn("Response playbooks", page.text)

    def test_policy_status_api(self) -> None:
        self._login()
        response = self.client.get("/api/policy/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("report", body)
        self.assertIn("checks", body["report"])

    def test_export_json(self) -> None:
        self._login()
        response = self.client.get("/api/policy/export?format=json&honey_only=false&exclude_baseline=false")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["format"], "activedecoy.alerts.json.v1")

    def test_playbooks_list(self) -> None:
        self._login()
        response = self.client.get("/api/policy/playbooks")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["playbooks"]), 4)


class DeployPolicyGateTests(unittest.TestCase):
    def test_deploy_includes_policy_report(self) -> None:
        client = TestClient(app)
        login = client.post(
            "/login",
            data={"username": "HwatSauce", "password": "Active-Decoy!2026"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        form = {
            "modules": ["honey_users"],
            "sync_to_graph": "false",
            "provision_ad": "false",
            "dry_run": "false",
        }
        response = client.post("/api/deception/deploy", data=form)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("policy", body)
        self.assertIn("score", body["policy"])


if __name__ == "__main__":
    unittest.main()
