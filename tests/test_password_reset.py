"""Password reset and forgot-password flow tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.console_auth import authenticate_console
from app.core.console_credentials import set_admin_password, verify_env_admin_password
from app.core.password_reset import (
    complete_password_reset,
    create_reset_token,
    request_password_reset,
    verify_reset_token,
)
from app.main import app, forgot_password_rate_limiter
from tests.test_config import _settings


class PasswordResetUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._store_patch = patch(
            "app.core.console_credentials.PASSWORD_STORE_PATH",
            Path(self._tmpdir.name) / "admin_password.json",
        )
        self._store_patch.start()

    def tearDown(self) -> None:
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def test_token_roundtrip(self) -> None:
        settings = _settings(session_secret="unit-test-secret-key-32chars-min", admin_email="admin@lab.local")
        token = create_reset_token(settings, "admin@lab.local")
        self.assertEqual(verify_reset_token(settings, token), "admin@lab.local")

    def test_reset_updates_login_password(self) -> None:
        settings = _settings(
            session_secret="unit-test-secret-key-32chars-min",
            admin_email="admin@lab.local",
            admin_username="admin",
            admin_password="changeme-dev-only",
            console_auth_mode="env",
            smtp_dev_log=True,
        )
        token = create_reset_token(settings, "admin@lab.local")
        ok, message = complete_password_reset(settings, token=token, new_password="New-Secure-Pass!")
        self.assertTrue(ok, message)
        self.assertTrue(verify_env_admin_password("New-Secure-Pass!", settings))
        auth = authenticate_console("admin", "New-Secure-Pass!", settings)
        self.assertTrue(auth.ok)

    @patch("app.core.password_reset.send_email", return_value=(True, "sent"))
    def test_request_reset_sends_for_matching_email(self, _mock_send: object) -> None:
        settings = _settings(
            session_secret="unit-test-secret-key-32chars-min",
            admin_email="admin@lab.local",
            console_auth_mode="env",
            smtp_host="smtp.lab.local",
        )
        sent, detail = request_password_reset(
            settings,
            email="admin@lab.local",
            base_url="http://127.0.0.1:8000",
        )
        self.assertTrue(sent)
        self.assertEqual(detail, "sent")

    @patch("app.core.password_reset.send_email")
    def test_request_reset_skips_unknown_email(self, mock_send: object) -> None:
        settings = _settings(
            session_secret="unit-test-secret-key-32chars-min",
            admin_email="admin@lab.local",
            console_auth_mode="env",
            smtp_host="smtp.lab.local",
        )
        sent, _detail = request_password_reset(
            settings,
            email="other@lab.local",
            base_url="http://127.0.0.1:8000",
        )
        self.assertFalse(sent)
        mock_send.assert_not_called()


class ForgotPasswordApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        forgot_password_rate_limiter.reset("testclient")

    @patch("app.main.request_password_reset", return_value=(True, "logged"))
    def test_forgot_password_shows_generic_success(self, _mock_reset: object) -> None:
        with patch("app.main.settings", _settings(
            session_secret="unit-test-secret-key-32chars-min",
            admin_email="admin@lab.local",
            console_auth_mode="env",
            smtp_dev_log=True,
        )), patch("app.main.password_reset_enabled", return_value=True):
            response = self.client.post(
                "/forgot-password",
                data={"email": "admin@lab.local"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("If an account exists", response.text)

    def test_forgot_password_page_has_email_field_when_enabled(self) -> None:
        with patch("app.main.password_reset_enabled", return_value=True):
            response = self.client.get("/forgot-password")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="email"', response.text)

    def test_login_shows_forgot_link_when_enabled(self) -> None:
        with patch("app.main.password_reset_enabled", return_value=True):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Forgot password?", response.text)


if __name__ == "__main__":
    unittest.main()
