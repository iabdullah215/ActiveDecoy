"""LDAP connectivity and bind-path tests with mocked ldap3."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.ad_provisioner import ADProvisioner
from app.core.connection_manager import ConnectionManager, LDAPConfig
from app.core.directory_enumerator import DirectoryEnumerator


class _Entry:
    def __init__(self, **attrs: object) -> None:
        self.entry_attributes_as_dict = attrs
        for key, value in attrs.items():
            scalar = value[0] if isinstance(value, list) and value else value
            setattr(self, key, SimpleNamespace(value=scalar, values=value if isinstance(value, list) else [scalar]))


class LDAPConnectionManagerTests(unittest.TestCase):
    def test_missing_ldap3(self) -> None:
        manager = ConnectionManager()
        with patch.object(manager, "_load_ldap3", return_value=None):
            result = manager.validate_ldap_connection(LDAPConfig(host="dc.lab"))
        self.assertFalse(result["success"])
        self.assertIn("ldap3", result["message"].lower())

    def test_successful_bind_with_base_dn(self) -> None:
        manager = ConnectionManager()
        ldap3 = MagicMock()
        ldap3.ALL = "ALL"
        ldap3.SUBTREE = "SUBTREE"
        ldap3.BASE = "BASE"
        connection = MagicMock()
        connection.entries = [_Entry(distinguishedName=["DC=lab,DC=local"])]
        ldap3.Connection.return_value = connection
        ldap3.Server.return_value = MagicMock()

        with patch.object(manager, "_load_ldap3", return_value=ldap3):
            result = manager.validate_ldap_connection(
                LDAPConfig(host="dc01.lab.local", base_dn="DC=lab,DC=local", bind_dn="CN=admin,DC=lab,DC=local")
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Connection Successful")
        connection.unbind.assert_called()

    def test_retry_eventually_succeeds(self) -> None:
        manager = ConnectionManager()
        responses = [
            {"success": False, "message": "fail", "debug": []},
            {"success": True, "message": "ok", "debug": []},
        ]

        def _fake(_config: LDAPConfig) -> dict:
            return responses.pop(0)

        with patch.object(manager, "validate_ldap_connection", side_effect=_fake):
            result = manager.validate_ldap_connection_with_retry(
                LDAPConfig(host="dc.lab"),
                retries=2,
                retry_delay=0,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["attempt"], 2)


class DirectoryEnumeratorLDAPTests(unittest.TestCase):
    def test_enumerate_builds_snapshot(self) -> None:
        enumerator = DirectoryEnumerator(page_size=50, max_objects=100)
        ldap3 = MagicMock()
        ldap3.ALL = "ALL"
        ldap3.SUBTREE = 2

        connection = MagicMock()
        connection.bound = True

        users = [
            _Entry(
                distinguishedName=["CN=Jane Doe,CN=Users,DC=lab,DC=local"],
                sAMAccountName=["jdoe"],
                displayName=["Jane Doe"],
                userAccountControl=["512"],
                memberOf=["CN=Domain Admins,CN=Users,DC=lab,DC=local"],
            )
        ]
        groups = [
            _Entry(
                distinguishedName=["CN=Domain Admins,CN=Users,DC=lab,DC=local"],
                sAMAccountName=["Domain Admins"],
                cn=["Domain Admins"],
                member=["CN=Jane Doe,CN=Users,DC=lab,DC=local"],
            )
        ]
        computers = [
            _Entry(
                distinguishedName=["CN=DC01,OU=Domain Controllers,DC=lab,DC=local"],
                sAMAccountName=["DC01$"],
                dNSHostName=["dc01.lab.local"],
                userAccountControl=["4096"],
            )
        ]
        trusts = [
            _Entry(
                distinguishedName=["CN=partner.local,CN=System,DC=lab,DC=local"],
                cn=["partner.local"],
                trustPartner=["partner.local"],
                trustDirection=["3"],
            )
        ]

        pages = {
            DirectoryEnumerator.USER_FILTER: users,
            DirectoryEnumerator.GROUP_FILTER: groups,
            DirectoryEnumerator.COMPUTER_FILTER: computers,
            DirectoryEnumerator.TRUST_FILTER: trusts,
        }

        def _search(*, search_filter: str = "", **_kwargs: object) -> bool:
            connection.entries = pages.get(search_filter, [])
            return True

        connection.search.side_effect = _search
        connection.extend = MagicMock()
        # Avoid paged search path by making extend.standard.paged_search unavailable / unused
        # Enumerate uses _paged_search — patch it to return our entries directly.
        ldap3.Connection.return_value = connection
        ldap3.Server.return_value = MagicMock()

        def _paged_side_effect(_connection, _ldap3, _base_dn, search_filter, *_args, **_kwargs):
            entries = pages.get(search_filter, [])
            return {"entries": entries, "truncated": False}

        with patch.object(enumerator, "_load_ldap3", return_value=ldap3), patch.object(
            enumerator,
            "_paged_search",
            side_effect=_paged_side_effect,
        ), patch.object(enumerator, "_discover_base_dn", return_value="DC=lab,DC=local"):
            snapshot = enumerator.enumerate(LDAPConfig(host="dc01.lab.local", base_dn="DC=lab,DC=local"))

        self.assertEqual(snapshot.domain, "lab.local")
        self.assertEqual(len(snapshot.users), 1)
        self.assertEqual(snapshot.users[0].name, "jdoe")
        self.assertEqual(len(snapshot.groups), 1)
        self.assertEqual(len(snapshot.computers), 1)
        self.assertEqual(len(snapshot.trusts), 1)
        self.assertGreaterEqual(len(snapshot.memberships), 1)


class ADProvisionerLDAPTests(unittest.TestCase):
    def test_preflight_succeeds_when_ou_exists(self) -> None:
        provisioner = ADProvisioner(honey_ou="OU=Honey,DC=lab,DC=local", name_prefix="hw_")
        connection = MagicMock()
        with patch.object(provisioner, "_load_ldap3", return_value=MagicMock()), patch.object(
            provisioner, "_connect", return_value=connection
        ), patch.object(provisioner, "_ou_exists", return_value=True):
            result = provisioner.preflight(
                LDAPConfig(host="dc01.lab.local", base_dn="DC=lab,DC=local", bind_dn="CN=a,DC=lab,DC=local")
            )
        self.assertTrue(result.ok)
        self.assertTrue(result.checks.get("honey_ou_exists"))
        self.assertTrue(result.checks.get("bind_ok"))
        connection.unbind.assert_called()

    def test_dry_run_provision_without_writes(self) -> None:
        from app.core.ad_provisioner import PreflightResult

        provisioner = ADProvisioner(honey_ou="OU=Honey,DC=lab,DC=local", name_prefix="hw_")
        fake_preflight = PreflightResult(
            ok=True,
            message="ok",
            honey_ou="OU=Honey,DC=lab,DC=local",
            base_dn="DC=lab,DC=local",
            checks={"honey_ou_exists": True, "bind_ok": True},
        )
        with patch.object(provisioner, "preflight", return_value=fake_preflight), patch.object(
            provisioner, "_load_ldap3", return_value=MagicMock()
        ):
            result = provisioner.provision_objects(
                LDAPConfig(host="dc.lab"),
                [
                    {"object_type": "HoneyUser", "name": "hw_alex.hale", "attributes": {}},
                    {"object_type": "Breadcrumb", "name": "canary-1", "attributes": {}},
                ],
                dry_run=True,
            )
        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])
        actions = {item["action"] for item in result["results"]}
        self.assertIn("would_create", actions)
        self.assertIn("skipped", actions)


if __name__ == "__main__":
    unittest.main()
