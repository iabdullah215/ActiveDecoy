"""Tests for directory enumeration and Neo4j AD sync helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.core.connection_manager import LDAPConfig
from app.core.directory_enumerator import (
    DirectoryEnumerator,
    DirectoryMembership,
    DirectoryObject,
    DirectorySnapshot,
    DirectoryTrust,
    snapshot_from_dict,
    snapshot_to_dict,
)
from app.core.directory_service import run_directory_import
from app.core.graph_store import GraphStore


def _sample_snapshot() -> DirectorySnapshot:
    return DirectorySnapshot(
        enumerated_at="2026-07-08T00:00:00+00:00",
        base_dn="DC=lab,DC=local",
        domain="lab.local",
        users=[
            DirectoryObject(
                object_type="ADUser",
                name="jdoe",
                dn="CN=Jane Doe,CN=Users,DC=lab,DC=local",
                attributes={
                    "display_name": "Jane Doe",
                    "enabled": True,
                    "member_of": ["CN=Domain Admins,CN=Users,DC=lab,DC=local"],
                },
            )
        ],
        groups=[
            DirectoryObject(
                object_type="ADGroup",
                name="Domain Admins",
                dn="CN=Domain Admins,CN=Users,DC=lab,DC=local",
                attributes={"members": ["CN=Jane Doe,CN=Users,DC=lab,DC=local"]},
            )
        ],
        computers=[
            DirectoryObject(
                object_type="ADComputer",
                name="DC01",
                dn="CN=DC01,OU=Domain Controllers,DC=lab,DC=local",
                attributes={"dns_hostname": "dc01.lab.local", "enabled": True},
            )
        ],
        memberships=[
            DirectoryMembership(
                member_dn="CN=Jane Doe,CN=Users,DC=lab,DC=local",
                group_dn="CN=Domain Admins,CN=Users,DC=lab,DC=local",
            )
        ],
        trusts=[
            DirectoryTrust(
                name="partner.local",
                dn="CN=partner.local,CN=System,DC=lab,DC=local",
                direction="bidirectional",
                partner="partner.local",
            )
        ],
        debug=["ok"],
        truncated=False,
    )


class SnapshotSerializationTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        original = _sample_snapshot()
        restored = snapshot_from_dict(snapshot_to_dict(original))
        assert restored is not None
        self.assertEqual(restored.domain, "lab.local")
        self.assertEqual(len(restored.users), 1)
        self.assertEqual(restored.users[0].name, "jdoe")
        self.assertEqual(len(restored.memberships), 1)
        self.assertEqual(restored.summary()["computers"], 1)


class DirectoryEnumeratorUnitTests(unittest.TestCase):
    def test_domain_from_dn(self) -> None:
        self.assertEqual(
            DirectoryEnumerator._domain_from_dn("DC=lab,DC=local"),
            "lab.local",
        )

    def test_account_enabled(self) -> None:
        self.assertTrue(DirectoryEnumerator._account_enabled(512))
        self.assertFalse(DirectoryEnumerator._account_enabled(514))

    def test_dedupe_memberships(self) -> None:
        items = [
            DirectoryMembership("CN=A,DC=lab", "CN=G,DC=lab"),
            DirectoryMembership("CN=A,DC=lab", "CN=G,DC=lab"),
            DirectoryMembership("CN=B,DC=lab", "CN=G,DC=lab"),
        ]
        unique = DirectoryEnumerator._dedupe_memberships(items)
        self.assertEqual(len(unique), 2)


class DirectoryServiceTests(unittest.TestCase):
    def test_run_directory_import_skips_graph(self) -> None:
        from app.core.config import get_settings

        enumerator = MagicMock()
        enumerator.enumerate.return_value = _sample_snapshot()
        graph = MagicMock(spec=GraphStore)

        result = run_directory_import(
            LDAPConfig(host="dc01.lab.local"),
            get_settings(),
            graph,
            sync_to_graph=False,
            enumerator=enumerator,
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["synced"])
        graph.sync_directory_snapshot.assert_not_called()
        self.assertEqual(result["summary"]["users"], 1)

    def test_run_directory_import_syncs_when_connected(self) -> None:
        from app.core.config import get_settings

        enumerator = MagicMock()
        enumerator.enumerate.return_value = _sample_snapshot()
        graph = MagicMock(spec=GraphStore)
        graph.health.return_value = MagicMock(
            configured=True,
            connected=True,
            message="Connected",
            node_count=5,
            honey_count=0,
            ad_count=5,
        )
        graph.sync_directory_snapshot.return_value = {
            "success": True,
            "counts": {"users": 1, "groups": 1, "computers": 1, "trusts": 1, "memberships": 1, "domain": 1},
            "errors": [],
            "ad_count": 5,
            "honey_count": 0,
            "node_count": 5,
        }

        result = run_directory_import(
            LDAPConfig(host="dc01.lab.local", base_dn="DC=lab,DC=local"),
            get_settings(),
            graph,
            sync_to_graph=True,
            enumerator=enumerator,
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["synced"])
        graph.sync_directory_snapshot.assert_called_once()


def _httpx_available() -> bool:
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_httpx_available(), "httpx is required for API integration tests")
class DirectoryApiTests(unittest.TestCase):
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

    def test_enumerate_requires_auth(self) -> None:
        response = self.client.post("/api/connection/enumerate")
        self.assertEqual(response.status_code, 401)

    def test_enumerate_requires_saved_profile(self) -> None:
        self._login()
        empty_profile = MagicMock()
        empty_profile.ldap_configured.return_value = False
        with patch("app.api.connection.load_session_profile", return_value=empty_profile):
            response = self.client.post(
                "/api/connection/enumerate",
                data={"sync_to_graph": "false"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])

    def test_enumerate_success_path(self) -> None:
        self._login()
        self.client.post(
            "/api/connection/save",
            data={
                "ldap_host": "dc01.lab.local",
                "ldap_port": "389",
                "ldap_base_dn": "DC=lab,DC=local",
                "hypervisor_type": "vmware",
                "auto_test_on_load": "false",
            },
        )

        with patch("app.api.connection.run_directory_import") as mocked:
            mocked.return_value = {
                "success": True,
                "message": "ok",
                "summary": {
                    "users": 1,
                    "groups": 1,
                    "computers": 1,
                    "trusts": 0,
                    "memberships": 1,
                    "domain": "lab.local",
                    "base_dn": "DC=lab,DC=local",
                },
                "synced": False,
                "graph_sync": None,
                "snapshot": snapshot_to_dict(_sample_snapshot()),
            }
            response = self.client.post(
                "/api/connection/enumerate",
                data={"sync_to_graph": "false"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["summary"]["users"], 1)
        self.assertIn("preview", payload)

    def test_graph_nodes_kind_param(self) -> None:
        self._login()
        with patch("app.api.graph.GraphStore.fetch_nodes", create=True):
            response = self.client.get("/api/graph/nodes", params={"kind": "ad"})
        # Without Neo4j this returns offline/empty, but endpoint must auth + answer.
        self.assertEqual(response.status_code, 200)
        self.assertIn("nodes", response.json())


if __name__ == "__main__":
    unittest.main()
