"""Tests for AD provisioning, safety checks, and deployment history."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.ad_provisioner import ADProvisioner, stamp_provision_names
from app.core.connection_manager import LDAPConfig
from app.core.deception_engine import DeceptionEngine
from app.core.deception_service import run_deception_deploy, run_deception_teardown
from app.core.deployment_history import DeploymentHistoryStore, DeploymentRecord
from app.core.monitoring_engine import MonitoringEngine


class NamingSafetyTests(unittest.TestCase):
    def test_stamp_applies_prefix(self) -> None:
        objects = [
            {"object_type": "HoneyUser", "name": "alex.hale", "attributes": {}},
            {"object_type": "Breadcrumb", "name": "canary-seed-1", "attributes": {}},
        ]
        stamped = stamp_provision_names(objects, "hw_")
        self.assertEqual(stamped[0]["name"], "hw_alex.hale")
        self.assertEqual(stamped[1]["name"], "canary-seed-1")

    def test_is_safe_dn(self) -> None:
        provisioner = ADProvisioner(
            honey_ou="OU=Honey,DC=lab,DC=local",
            name_prefix="hw_",
            require_prefix=True,
        )
        self.assertTrue(provisioner._is_safe_dn("CN=hw_alex.hale,OU=Honey,DC=lab,DC=local"))
        self.assertFalse(provisioner._is_safe_dn("CN=alex.hale,OU=Honey,DC=lab,DC=local"))
        self.assertFalse(provisioner._is_safe_dn("CN=hw_alex.hale,CN=Users,DC=lab,DC=local"))


class PreflightTests(unittest.TestCase):
    def test_preflight_requires_ou(self) -> None:
        provisioner = ADProvisioner(honey_ou="")
        result = provisioner.preflight(LDAPConfig(host="dc01.lab.local"))
        self.assertFalse(result.ok)
        self.assertIn("AD_HONEY_OU", result.message)


class DeploymentHistoryTests(unittest.TestCase):
    def test_add_list_and_teardown_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DeploymentHistoryStore(Path(tmp) / "deployments.json")
            record = DeploymentRecord(
                deployment_id="dep-1",
                created_at="2026-07-08T00:00:00Z",
                actor="tester",
                modules=["honey_users"],
                objects=[{"object_type": "HoneyUser", "name": "hw_a"}],
                provisioned=[{"object_type": "HoneyUser", "name": "hw_a", "dn": "CN=hw_a,OU=Honey,DC=lab,DC=local"}],
                ad_provisioned=True,
                status="active",
            )
            store.add(record)
            listed = store.list_records()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["deployment_id"], "dep-1")
            updated = store.mark_torn_down("dep-1", notes="removed")
            assert updated is not None
            self.assertEqual(updated.status, "torn_down")
            self.assertTrue(updated.teardown_at)


class DeceptionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.core.config import get_settings

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.history = DeploymentHistoryStore(Path(self.tmp.name) / "deployments.json")
        self.engine = DeceptionEngine(seed=1)
        self.monitoring = MonitoringEngine(seed=1)
        self.graph = MagicMock()
        self.graph.health.return_value = MagicMock(node_count=0, honey_count=0, ad_count=0)
        self.graph.execute_queries.return_value = {"success": True, "executed": 1, "errors": []}

    def test_plan_only_deploy(self) -> None:
        from app.core.config import get_settings

        payload = run_deception_deploy(
            modules=["honey_users", "breadcrumbs"],
            settings=get_settings(),
            deception_engine=self.engine,
            monitoring_engine=self.monitoring,
            graph_store=self.graph,
            history=self.history,
            ldap_config=None,
            actor="tester",
            sync_to_graph=False,
            provision_ad=False,
            dry_run=False,
        )
        self.assertTrue(payload["success"])
        self.assertTrue(payload["ad_provision"].get("skipped"))
        self.assertTrue(any(obj["name"].startswith("hw_") for obj in payload["objects"] if obj["object_type"] == "HoneyUser"))
        self.assertEqual(len(self.history.list_records()), 1)

    def test_provision_blocked_without_ldap(self) -> None:
        from app.core.config import get_settings

        payload = run_deception_deploy(
            modules=["honey_users"],
            settings=get_settings(),
            deception_engine=self.engine,
            monitoring_engine=self.monitoring,
            graph_store=self.graph,
            history=self.history,
            ldap_config=None,
            actor="tester",
            provision_ad=True,
            dry_run=False,
        )
        self.assertFalse(payload["success"])
        self.assertFalse(payload["ad_provision"]["success"])

    def test_teardown_missing_deployment(self) -> None:
        from app.core.config import get_settings

        result = run_deception_teardown(
            deployment_id="missing",
            settings=get_settings(),
            history=self.history,
            ldap_config=LDAPConfig(host="dc01"),
        )
        self.assertFalse(result["success"])


def _httpx_available() -> bool:
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_httpx_available(), "httpx is required for API integration tests")
class DeceptionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app, login_rate_limiter

        self.client = TestClient(app)
        login_rate_limiter.reset("testclient")

    def _login(self) -> None:
        response = self.client.post(
            "/login",
            data={"username": "HwatSauce", "password": "Active-Decoy!2026"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_deploy_plan_only(self) -> None:
        self._login()
        response = self.client.post(
            "/api/deception/deploy",
            data={
                "modules": ["honey_users", "honey_servers"],
                "sync_to_graph": "false",
                "provision_ad": "false",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("deployment_id", payload)
        self.assertTrue(payload.get("success", True) or "objects" in payload)
        self.assertGreater(len(payload["objects"]), 0)

    def test_provision_requires_feature_flag(self) -> None:
        self._login()
        response = self.client.post(
            "/api/deception/deploy",
            data={
                "modules": ["honey_users"],
                "provision_ad": "true",
                "dry_run": "false",
                "sync_to_graph": "false",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # Default config has AD_PROVISION_ENABLED=false
        self.assertFalse(payload["success"])
        self.assertIn("disabled", payload["message"].lower())

    def test_history_endpoint(self) -> None:
        self._login()
        self.client.post(
            "/api/deception/deploy",
            data={"modules": ["breadcrumbs"], "sync_to_graph": "false"},
        )
        history = self.client.get("/api/deception/history")
        self.assertEqual(history.status_code, 200)
        self.assertIn("deployments", history.json())

    def test_deception_page_renders(self) -> None:
        self._login()
        page = self.client.get("/deception")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Provision in Active Directory", page.text)


if __name__ == "__main__":
    unittest.main()
