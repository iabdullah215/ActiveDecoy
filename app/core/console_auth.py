"""Console authentication: env admin and optional LDAP/AD bind."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import secrets
from importlib import import_module
from typing import Any

from app.core.config import Settings
from app.core.connection_manager import LDAPConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConsoleAuthResult:
    ok: bool
    actor: str = ""
    method: str = ""
    message: str = ""


def parse_auth_modes(raw: str) -> tuple[str, ...]:
    modes = tuple(part.strip().lower() for part in (raw or "env").split(",") if part.strip())
    return modes or ("env",)


def _ldap_config_for_console(settings: Settings) -> LDAPConfig:
    return LDAPConfig(
        host=settings.ldap_host,
        port=settings.ldap_port,
        use_ssl=settings.ldap_use_ssl,
        bind_dn="",
        password="",
        base_dn=settings.ldap_base_dn,
        timeout=8,
    )


def _bind_candidates(username: str, domain: str) -> list[str]:
    user = username.strip()
    if not user:
        return []
    if "@" in user or "\\" in user:
        return [user]
    candidates = []
    if domain:
        candidates.append(f"{user}@{domain}")
    candidates.append(user)
    return candidates


def _try_ldap_bind(config: LDAPConfig, principal: str, password: str) -> bool:
    ldap3 = _load_ldap3()
    if ldap3 is None:
        return False
    try:
        server = ldap3.Server(config.host, port=config.port, use_ssl=config.use_ssl, get_info=ldap3.NONE)
        connection = ldap3.Connection(
            server,
            user=principal,
            password=password,
            auto_bind=True,
            receive_timeout=config.timeout,
        )
        bound = bool(connection.bound)
        try:
            connection.unbind()
        except Exception:
            pass
        return bound
    except Exception:
        return False


def _load_ldap3() -> Any | None:
    try:
        return import_module("ldap3")
    except Exception:
        return None


def authenticate_console(username: str, password: str, settings: Settings) -> ConsoleAuthResult:
    """Authenticate an operator against configured console auth backends."""

    modes = parse_auth_modes(settings.console_auth_mode)
    normalized_user = username.strip()

    if "env" in modes:
        if secrets.compare_digest(normalized_user, settings.admin_username) and secrets.compare_digest(
            password, settings.admin_password
        ):
            return ConsoleAuthResult(ok=True, actor=settings.admin_username, method="env")

    if "ldap" in modes:
        if not settings.ldap_host.strip():
            return ConsoleAuthResult(ok=False, message="LDAP host is not configured for console login.")
        config = _ldap_config_for_console(settings)
        for principal in _bind_candidates(normalized_user, settings.console_ldap_domain):
            if _try_ldap_bind(config, principal, password):
                actor = normalized_user.split("@")[0].split("\\")[-1]
                return ConsoleAuthResult(ok=True, actor=actor, method="ldap")
        if len(modes) == 1:
            return ConsoleAuthResult(ok=False, message="Directory authentication failed.")

    return ConsoleAuthResult(ok=False, message="Invalid credentials.")
