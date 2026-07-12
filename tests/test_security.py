"""Tests for Chunk 2 security controls."""

from __future__ import annotations

import json
import logging
import unittest

from app.core.audit import AUDIT_LOGGER_NAME, audit_event
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.secret_store import SecretStore


class RateLimiterTests(unittest.TestCase):
    def test_blocks_after_max_attempts(self) -> None:
        limiter = SlidingWindowRateLimiter(max_attempts=3, window_seconds=60)
        self.assertTrue(limiter.hit("10.0.0.1").allowed)
        self.assertTrue(limiter.hit("10.0.0.1").allowed)
        self.assertTrue(limiter.hit("10.0.0.1").allowed)
        blocked = limiter.hit("10.0.0.1")
        self.assertFalse(blocked.allowed)
        self.assertGreaterEqual(blocked.retry_after, 1)

    def test_reset_clears_bucket(self) -> None:
        limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
        self.assertTrue(limiter.hit("client-a").allowed)
        self.assertFalse(limiter.hit("client-a").allowed)
        limiter.reset("client-a")
        self.assertTrue(limiter.hit("client-a").allowed)


class SecretStoreTests(unittest.TestCase):
    def test_put_get_clear(self) -> None:
        store = SecretStore()
        store.put("sid-1", ldap_password="ldap-secret", hypervisor_password="hv-secret")
        secrets = store.get("sid-1")
        self.assertEqual(secrets.ldap_password, "ldap-secret")
        self.assertEqual(secrets.hypervisor_password, "hv-secret")
        store.clear("sid-1")
        empty = store.get("sid-1")
        self.assertEqual(empty.ldap_password, "")
        self.assertEqual(empty.hypervisor_password, "")


class AuditTests(unittest.TestCase):
    def test_audit_event_emits_json(self) -> None:
        records: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record.getMessage())

        logger = logging.getLogger(AUDIT_LOGGER_NAME)
        previous_level = logger.level
        previous_propagate = logger.propagate
        handler = _Capture()
        handler.setLevel(logging.INFO)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        try:
            audit_event("unit.test", actor="tester", outcome="success", detail="ok")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
            logger.propagate = previous_propagate

        self.assertEqual(len(records), 1)
        payload = json.loads(records[0])
        self.assertEqual(payload["action"], "unit.test")
        self.assertEqual(payload["actor"], "tester")
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["details"]["detail"], "ok")


def _httpx_available() -> bool:
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_httpx_available(), "httpx is required for API integration tests")
class SecurityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app, login_rate_limiter

        self.client = TestClient(app)
        self.limiter = login_rate_limiter
        self.limiter.reset("testclient")

    def tearDown(self) -> None:
        self.limiter.reset("testclient")

    def test_login_rate_limit(self) -> None:
        # Exhaust the bucket with intentional failures.
        for _ in range(self.limiter.max_attempts):
            response = self.client.post(
                "/login",
                data={"username": "wrong", "password": "wrong"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        blocked = self.client.post(
            "/login",
            data={"username": "wrong", "password": "wrong"},
            follow_redirects=False,
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)

    def test_session_profile_omits_passwords(self) -> None:
        login = self.client.post(
            "/login",
            data={"username": "admin", "password": "changeme-dev-only"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)

        save = self.client.post(
            "/api/connection/save",
            data={
                "ldap_host": "dc01.lab.local",
                "ldap_port": "389",
                "ldap_password": "super-secret-ldap",
                "hypervisor_type": "vmware",
                "hypervisor_password": "super-secret-hv",
                "auto_test_on_load": "false",
            },
        )
        self.assertEqual(save.status_code, 200)
        profile = save.json()["profile"]
        self.assertEqual(profile["ldap_password"], "")
        self.assertTrue(profile["ldap_password_set"])
        self.assertEqual(profile["hypervisor_password"], "")
        self.assertTrue(profile["hypervisor_password_set"])

        # Cookies / response bodies must not contain raw secrets.
        cookie_blob = " ".join(f"{k}={v}" for k, v in self.client.cookies.items())
        self.assertNotIn("super-secret-ldap", cookie_blob)
        self.assertNotIn("super-secret-hv", cookie_blob)
        self.assertNotIn("super-secret-ldap", save.text)
        self.assertNotIn("super-secret-hv", save.text)


if __name__ == "__main__":
    unittest.main()
