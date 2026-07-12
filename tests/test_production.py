"""Production startup guard tests."""

from __future__ import annotations

import unittest

from app.core.config import enforce_production_guards
from tests.test_config import _settings


def _production_settings(**overrides):
    base = dict(
        app_env="production",
        debug=False,
        session_secret="a" * 48,
        neo4j_password="neo4j-prod-pass",
        agent_ingest_token="ingest-token-32-characters",
        admin_username="prod-admin",
        admin_password="prod-admin-strong-pass!",
        console_auth_mode="env",
        ldap_host="dc01.lab.local",
        ad_provision_enabled=False,
    )
    base.update(overrides)
    return _settings(**base)


class ProductionGuardTests(unittest.TestCase):
    def test_blocks_weak_production_config(self) -> None:
        with self.assertRaises(SystemExit):
            enforce_production_guards(_production_settings(session_secret="short"))

    def test_allows_valid_production_config(self) -> None:
        enforce_production_guards(_production_settings())

    def test_blocks_default_admin_when_env_auth_enabled(self) -> None:
        with self.assertRaises(SystemExit):
            enforce_production_guards(
                _production_settings(
                    admin_username="admin",
                    admin_password="changeme-dev-only",
                    console_auth_mode="ldap,env",
                )
            )

    def test_skips_guards_in_development(self) -> None:
        enforce_production_guards(_settings(app_env="development", session_secret="short"))


if __name__ == "__main__":
    unittest.main()
