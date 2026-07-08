"""Tests for configuration validation helpers."""

from __future__ import annotations

import unittest

from app.core.config import Settings, enforce_startup_guards, parse_cors_origins, validate_settings


def _settings(**overrides) -> Settings:
    base = dict(
        session_secret="active-decoy-development-secret",
        admin_username="HwatSauce",
        admin_password="Active-Decoy!2026",
        admin_email="",
        app_env="development",
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="",
        neo4j_database="neo4j",
        neodash_url="https://neodash.graphapp.io",
        host="127.0.0.1",
        port=8000,
        debug=False,
        enforce_secure_defaults=False,
        session_https_only=False,
        session_same_site="lax",
        session_max_age=604800,
        trusted_proxy_hosts=(),
        console_auth_mode="env",
        console_ldap_domain="",
        cors_origins=("http://127.0.0.1:8000", "http://localhost:8000"),
        login_rate_limit=5,
        login_rate_window_seconds=60,
        agent_ingest_token="",
        agent_stale_seconds=90,
        ldap_host="dc01.lab.local",
        ldap_port=389,
        ldap_use_ssl=False,
        ldap_bind_dn="",
        ldap_password="",
        ldap_base_dn="",
        hypervisor_type="vmware",
        hypervisor_endpoint="",
        hypervisor_username="",
        hypervisor_password="",
        hypervisor_vm_name="Washu-DC",
        wrapper_command="",
        connection_retries=3,
        connection_retry_delay=0.5,
        ldap_page_size=200,
        ldap_max_objects=500,
        ad_honey_ou="",
        ad_honey_name_prefix="hw_",
        ad_require_name_prefix=True,
        ad_provision_enabled=False,
        ad_monitored_domains="",
        ad_harden_on_provision=False,
        ad_honey_workstations_lock="NONEXISTENT-AD-LOCK",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        smtp_use_tls=True,
        smtp_dev_log=False,
        password_reset_ttl_seconds=3600,
        console_public_url="",
    )
    base.update(overrides)
    return Settings(**base)


class ConfigValidationTests(unittest.TestCase):
    def test_get_settings_uses_lab_defaults_under_unittest(self) -> None:
        from app.core.config import get_settings

        self.assertEqual(get_settings().admin_username, "HwatSauce")
        self.assertEqual(get_settings().app_env, "development")

    def test_warns_on_defaults_and_missing_neo4j(self) -> None:
        warnings = validate_settings(_settings())
        self.assertTrue(any("default admin" in item.lower() for item in warnings))
        self.assertTrue(any("session_secret" in item.lower() for item in warnings))
        self.assertTrue(any("neo4j" in item.lower() for item in warnings))

    def test_no_warnings_for_hardened_lab_config(self) -> None:
        warnings = validate_settings(
            _settings(
                session_secret="unique-lab-secret-value",
                admin_username="lab-admin",
                admin_password="lab-strong-pass!",
                admin_email="lab-admin@lab.local",
                neo4j_password="neo4j-lab-pass",
                agent_ingest_token="lab-ingest-token",
                smtp_host="smtp.lab.local",
            )
        )
        self.assertEqual(warnings, [])

    def test_parse_cors_origins(self) -> None:
        self.assertEqual(
            parse_cors_origins("http://127.0.0.1:8000, http://localhost:8000"),
            ["http://127.0.0.1:8000", "http://localhost:8000"],
        )
        self.assertEqual(parse_cors_origins(""), [])

    def test_enforce_secure_defaults_blocks_startup(self) -> None:
        with self.assertRaises(SystemExit):
            enforce_startup_guards(_settings(enforce_secure_defaults=True))

    def test_enforce_secure_defaults_allows_hardened(self) -> None:
        enforce_startup_guards(
            _settings(
                enforce_secure_defaults=True,
                session_secret="unique-lab-secret-value",
                admin_username="lab-admin",
                admin_password="lab-strong-pass!",
            )
        )


if __name__ == "__main__":
    unittest.main()
