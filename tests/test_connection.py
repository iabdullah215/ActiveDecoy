"""Tests for connection profile and bridge status logic."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.core.config import Settings
from app.core.connection_manager import ConnectionManager
from app.core.connection_profile import ConnectionProfile
from app.core.connection_service import build_checklist, compute_bridge_status, run_connection_test


class ConnectionProfileTests(unittest.TestCase):
    def test_merge_secrets_keeps_password_when_blank(self) -> None:
        stored = ConnectionProfile(ldap_host="dc.lab", ldap_password="secret")
        incoming = ConnectionProfile(ldap_host="dc.lab", ldap_password="")
        merged = incoming.merge_secrets(stored)
        self.assertEqual(merged.ldap_password, "secret")

    def test_hypervisor_configured_vmware(self) -> None:
        profile = ConnectionProfile(hypervisor_type="vmware", hypervisor_endpoint="vcenter.local")
        self.assertTrue(profile.hypervisor_configured())
        empty = ConnectionProfile(hypervisor_type="vmware")
        self.assertFalse(empty.hypervisor_configured())


class BridgeStatusTests(unittest.TestCase):
    def test_connected_when_ldap_ok(self) -> None:
        self.assertEqual(
            compute_bridge_status(True, False, False, True),
            "connected",
        )

    def test_degraded_when_hypervisor_fails(self) -> None:
        self.assertEqual(
            compute_bridge_status(True, False, True, True),
            "degraded",
        )

    def test_failed_when_ldap_fails(self) -> None:
        self.assertEqual(
            compute_bridge_status(False, True, False, True),
            "failed",
        )


class ConnectionServiceTests(unittest.TestCase):
    def test_build_checklist_skipped_hypervisor(self) -> None:
        profile = ConnectionProfile(ldap_host="dc.lab", hypervisor_type="vmware")
        checklist = build_checklist(
            {"success": True, "message": "ok"},
            {"success": False, "message": "skip"},
            profile,
        )
        self.assertEqual(checklist["hypervisor"]["status"], "skipped")

    def test_run_connection_test_retries(self) -> None:
        manager = ConnectionManager()
        profile = ConnectionProfile(ldap_host="127.0.0.1", ldap_port=65535)

        with patch.object(
            manager,
            "validate_ldap_connection_with_retry",
            return_value={"success": False, "message": "fail", "debug": ["x"]},
        ) as mock_retry:
            result = run_connection_test(manager, profile, retries=2, retry_delay=0)
            mock_retry.assert_called_once()
            self.assertEqual(result["checklist"]["bridge"]["status"], "failed")


class ConnectionSessionTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        from app.core.config import get_settings
        from app.core.connection_profile import load_session_profile, save_session_profile

        session: dict = {}
        profile = ConnectionProfile(ldap_host="dc01.lab.local", ldap_password="test-secret")
        save_session_profile(session, profile)
        self.assertEqual(session["connection_profile"]["ldap_password"], "")
        self.assertIn("connection_secret_id", session)

        loaded = load_session_profile(session, get_settings())
        self.assertEqual(loaded.ldap_host, "dc01.lab.local")
        self.assertEqual(loaded.ldap_password, "test-secret")
        public = loaded.to_public_dict()
        self.assertEqual(public["ldap_password"], "")
        self.assertTrue(public["ldap_password_set"])

    def test_legacy_session_passwords_are_migrated(self) -> None:
        from app.core.config import get_settings
        from app.core.connection_profile import load_session_profile

        session = {
            "connection_profile": {
                "ldap_host": "dc01.lab.local",
                "ldap_password": "legacy-secret",
                "hypervisor_type": "vmware",
            }
        }
        loaded = load_session_profile(session, get_settings())
        self.assertEqual(loaded.ldap_password, "legacy-secret")
        self.assertEqual(session["connection_profile"]["ldap_password"], "")


def _httpx_available() -> bool:
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_httpx_available(), "httpx is required for API integration tests")
class ConnectionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        self.client = TestClient(app)

    def _login(self) -> None:
        response = self.client.post(
            "/login",
            data={"username": "HwatSauce", "password": "Active-Decoy!2026"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_profile_requires_auth(self) -> None:
        response = self.client.get("/api/connection/profile")
        self.assertEqual(response.status_code, 401)

    def test_save_and_status(self) -> None:
        self._login()
        save = self.client.post(
            "/api/connection/save",
            data={
                "ldap_host": "dc01.lab.local",
                "ldap_port": "389",
                "ldap_use_ssl": "false",
                "hypervisor_type": "vmware",
                "auto_test_on_load": "false",
            },
        )
        self.assertEqual(save.status_code, 200)
        self.assertTrue(save.json()["success"])

        status = self.client.get("/api/connection/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["profile_configured"])


if __name__ == "__main__":
    unittest.main()
