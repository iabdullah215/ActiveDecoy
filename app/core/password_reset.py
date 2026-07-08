"""Password reset tokens and break-glass admin recovery."""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import Settings
from app.core.console_credentials import (
    admin_email_matches,
    password_reset_enabled,
    set_admin_password,
    validate_new_password,
)
from app.core.mailer import send_email, smtp_configured


logger = logging.getLogger(__name__)

_TOKEN_SALT = "activedecoy-password-reset"


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=_TOKEN_SALT)


def create_reset_token(settings: Settings, email: str) -> str:
    return _serializer(settings).dumps({"email": email.strip().lower()})


def verify_reset_token(settings: Settings, token: str) -> str | None:
    try:
        payload = _serializer(settings).loads(token, max_age=settings.password_reset_ttl_seconds)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    email = str((payload or {}).get("email") or "").strip().lower()
    return email or None


def build_reset_url(base_url: str, token: str) -> str:
    base = base_url.rstrip("/") + "/"
    return urljoin(base, f"reset-password?token={token}")


def request_password_reset(settings: Settings, *, email: str, base_url: str) -> tuple[bool, str]:
    """Queue a reset email when the address matches the configured admin email."""

    if not password_reset_enabled(settings):
        return False, "disabled"

    normalized = email.strip().lower()
    if not admin_email_matches(settings, normalized):
        return False, "no_match"

    token = create_reset_token(settings, normalized)
    reset_url = build_reset_url(base_url, token)
    subject = "ActiveDecoy console password reset"
    text_body = (
        "You requested a password reset for the ActiveDecoy console.\n\n"
        f"Open this link to choose a new password (expires in {settings.password_reset_ttl_seconds // 60} minutes):\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    html_body = (
        "<p>You requested a password reset for the ActiveDecoy console.</p>"
        f'<p><a href="{reset_url}">Choose a new password</a> '
        f"(link expires in {settings.password_reset_ttl_seconds // 60} minutes).</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
    )

    if not smtp_configured(settings) and not settings.smtp_dev_log:
        logger.warning("Password reset requested but SMTP is not configured.")
        return False, "smtp_missing"

    ok, detail = send_email(
        settings,
        to_address=normalized,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
    if ok:
        logger.info("Password reset email %s for %s", detail, normalized)
        return True, detail
    return False, detail


def complete_password_reset(settings: Settings, *, token: str, new_password: str) -> tuple[bool, str]:
    email = verify_reset_token(settings, token)
    if not email:
        return False, "This reset link is invalid or has expired."
    if not admin_email_matches(settings, email):
        return False, "This reset link is invalid or has expired."

    validation_error = validate_new_password(new_password, settings)
    if validation_error:
        return False, validation_error

    set_admin_password(new_password)
    return True, "Your password has been updated. You can sign in now."
