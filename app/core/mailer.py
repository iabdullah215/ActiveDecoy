"""SMTP mail delivery for operator notifications."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Settings


logger = logging.getLogger(__name__)


def smtp_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host.strip())


def send_email(
    settings: Settings,
    *,
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> tuple[bool, str]:
    """Send an email. Returns (success, detail)."""

    recipient = to_address.strip()
    if not recipient:
        return False, "Recipient address is empty."

    if not smtp_configured(settings):
        if settings.smtp_dev_log:
            logger.info(
                "SMTP not configured (SMTP_DEV_LOG=true). Email to %s — subject: %s\n%s",
                recipient,
                subject,
                text_body,
            )
            return True, "logged"
        return False, "SMTP is not configured."

    sender = (settings.smtp_from or settings.smtp_user or settings.admin_email).strip()
    if not sender:
        return False, "SMTP_FROM is not configured."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
                client.ehlo()
                client.starttls()
                client.ehlo()
                if settings.smtp_user:
                    client.login(settings.smtp_user, settings.smtp_password)
                client.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
                if settings.smtp_user:
                    client.login(settings.smtp_user, settings.smtp_password)
                client.send_message(message)
    except Exception as exc:
        logger.warning("Failed to send email to %s: %s", recipient, exc)
        return False, str(exc)

    return True, "sent"
