"""Tests for console authentication backends."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.console_auth import authenticate_console, parse_auth_modes
from tests.test_config import _settings


class ConsoleAuthTests(unittest.TestCase):
    def test_parse_auth_modes_defaults_to_env(self) -> None:
        self.assertEqual(parse_auth_modes(""), ("env",))
        self.assertEqual(parse_auth_modes("ldap, env"), ("ldap", "env"))

    def test_env_auth_success(self) -> None:
        result = authenticate_console(
            "lab-admin",
            "lab-strong-pass!",
            _settings(admin_username="lab-admin", admin_password="lab-strong-pass!", console_auth_mode="env"),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "env")
        self.assertEqual(result.actor, "lab-admin")

    def test_env_auth_rejects_wrong_password(self) -> None:
        result = authenticate_console(
            "lab-admin",
            "wrong",
            _settings(admin_username="lab-admin", admin_password="lab-strong-pass!", console_auth_mode="env"),
        )
        self.assertFalse(result.ok)

    @patch("app.core.console_auth._try_ldap_bind", return_value=True)
    def test_ldap_auth_success(self, _mock_bind: object) -> None:
        result = authenticate_console(
            "operator",
            "ldap-pass",
            _settings(
                console_auth_mode="ldap",
                console_ldap_domain="lab.local",
                ldap_host="dc01.lab.local",
            ),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "ldap")
        self.assertEqual(result.actor, "operator")

    def test_ldap_only_without_host(self) -> None:
        result = authenticate_console(
            "operator",
            "ldap-pass",
            _settings(console_auth_mode="ldap", ldap_host=""),
        )
        self.assertFalse(result.ok)
        self.assertIn("LDAP host", result.message)


if __name__ == "__main__":
    unittest.main()
