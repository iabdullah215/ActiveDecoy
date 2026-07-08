"""Break-glass admin password storage with optional on-disk override."""

from __future__ import annotations

from hashlib import pbkdf2_hmac
import json
import logging
import secrets
from pathlib import Path

from app.core.config import Settings


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PASSWORD_STORE_PATH = PROJECT_ROOT / "data" / "admin_password.json"
_PBKDF2_ITERATIONS = 260_000


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def admin_email_matches(settings: Settings, email: str) -> bool:
    configured = _normalize_email(settings.admin_email)
    if not configured:
        return False
    return configured == _normalize_email(email)


def password_reset_enabled(settings: Settings) -> bool:
    return "env" in settings.console_auth_mode and bool(settings.admin_email.strip())


def _hash_password(password: str, *, salt: bytes | None = None) -> dict[str, str]:
    salt_bytes = salt or secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, _PBKDF2_ITERATIONS)
    return {
        "salt": salt_bytes.hex(),
        "hash": digest.hex(),
        "iterations": str(_PBKDF2_ITERATIONS),
    }


def _read_store() -> dict[str, str] | None:
    if not PASSWORD_STORE_PATH.exists():
        return None
    try:
        payload = json.loads(PASSWORD_STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("hash") and payload.get("salt"):
            return payload
    except Exception:
        logger.warning("Could not read admin password override at %s", PASSWORD_STORE_PATH)
    return None


def verify_env_admin_password(password: str, settings: Settings) -> bool:
    stored = _read_store()
    if stored:
        salt = bytes.fromhex(stored["salt"])
        iterations = int(stored.get("iterations") or _PBKDF2_ITERATIONS)
        expected = bytes.fromhex(stored["hash"])
        actual = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(actual, expected)
    return secrets.compare_digest(password, settings.admin_password)


def set_admin_password(password: str) -> None:
    PASSWORD_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _hash_password(password)
    PASSWORD_STORE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        PASSWORD_STORE_PATH.chmod(0o600)
    except OSError:
        pass


def validate_new_password(password: str, settings: Settings) -> str | None:
    if len(password) < 12:
        return "Password must be at least 12 characters."
    if secrets.compare_digest(password, settings.admin_password):
        return "Choose a password different from the current one."
    return None
