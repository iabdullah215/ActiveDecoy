"""Application configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

# Load secrets and service config from the project root .env (never commit .env).
load_dotenv(PROJECT_ROOT / ".env")

_DEFAULT_SESSION_SECRET = "active-decoy-development-secret"
_DEFAULT_ADMIN_USERNAME = "HwatSauce"
_DEFAULT_ADMIN_PASSWORD = "Active-Decoy!2026"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass(frozen=True)
class Settings:
    session_secret: str
    admin_username: str
    admin_password: str
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str
    neodash_url: str
    host: str
    port: int
    debug: bool
    ldap_host: str
    ldap_port: int
    ldap_use_ssl: bool
    ldap_bind_dn: str
    ldap_password: str
    ldap_base_dn: str
    hypervisor_type: str
    hypervisor_endpoint: str
    hypervisor_username: str
    hypervisor_password: str
    hypervisor_vm_name: str
    wrapper_command: str
    connection_retries: int
    connection_retry_delay: float

    @property
    def neo4j_configured(self) -> bool:
        return bool(self.neo4j_uri and self.neo4j_password)

    @property
    def using_default_session_secret(self) -> bool:
        return self.session_secret in {
            _DEFAULT_SESSION_SECRET,
            "active-decoy-docker-dev-secret",
            "change-me-in-production",
        }

    @property
    def using_default_admin_credentials(self) -> bool:
        return (
            self.admin_username == _DEFAULT_ADMIN_USERNAME
            and self.admin_password == _DEFAULT_ADMIN_PASSWORD
        )


def get_settings() -> Settings:
    return Settings(
        session_secret=_env("SESSION_SECRET", _DEFAULT_SESSION_SECRET),
        admin_username=_env("ADMIN_USERNAME", _DEFAULT_ADMIN_USERNAME),
        admin_password=_env("ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD),
        neo4j_uri=_env("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_username=_env("NEO4J_USERNAME", "neo4j"),
        neo4j_password=_env("NEO4J_PASSWORD", ""),
        neo4j_database=_env("NEO4J_DATABASE", "neo4j"),
        neodash_url=_env("NEODASH_URL", "https://neodash.graphapp.io"),
        host=_env("APP_HOST", "127.0.0.1"),
        port=int(_env("APP_PORT", "8000")),
        debug=_env("APP_DEBUG", "false").lower() in {"1", "true", "yes"},
        ldap_host=_env("LDAP_HOST", "dc01.lab.local"),
        ldap_port=int(_env("LDAP_PORT", "389")),
        ldap_use_ssl=_env("LDAP_USE_SSL", "false").lower() in {"1", "true", "yes"},
        ldap_bind_dn=_env("LDAP_BIND_DN", ""),
        ldap_password=_env("LDAP_PASSWORD", ""),
        ldap_base_dn=_env("LDAP_BASE_DN", ""),
        hypervisor_type=_env("HYPERVISOR_TYPE", "vmware"),
        hypervisor_endpoint=_env("HYPERVISOR_ENDPOINT", ""),
        hypervisor_username=_env("HYPERVISOR_USERNAME", ""),
        hypervisor_password=_env("HYPERVISOR_PASSWORD", ""),
        hypervisor_vm_name=_env("HYPERVISOR_VM_NAME", "Washu-DC"),
        wrapper_command=_env("HYPERVISOR_WRAPPER_COMMAND", ""),
        connection_retries=int(_env("CONNECTION_RETRIES", "3")),
        connection_retry_delay=float(_env("CONNECTION_RETRY_DELAY", "0.5")),
    )


def validate_settings(settings: Settings) -> list[str]:
    """Return non-fatal configuration warnings for operator visibility."""

    warnings: list[str] = []
    if not settings.admin_username or not settings.admin_password:
        warnings.append("ADMIN_USERNAME and ADMIN_PASSWORD must both be set.")
    if settings.using_default_admin_credentials:
        warnings.append("Using default admin credentials; change them before shared lab use.")
    if settings.using_default_session_secret:
        warnings.append("SESSION_SECRET is using a development default; set a strong value.")
    if not settings.neo4j_configured:
        warnings.append("Neo4j is not configured (NEO4J_PASSWORD empty); graph sync will stay offline.")
    if settings.connection_retries < 1:
        warnings.append("CONNECTION_RETRIES should be >= 1.")
    if settings.connection_retry_delay < 0:
        warnings.append("CONNECTION_RETRY_DELAY should be >= 0.")
    return warnings


def log_settings_summary(settings: Settings) -> None:
    """Log a redacted startup summary and any validation warnings."""

    for warning in validate_settings(settings):
        logger.warning("Config: %s", warning)

    logger.info(
        "ActiveDecoy starting host=%s:%s debug=%s neo4j=%s ldap_host=%s hypervisor=%s",
        settings.host,
        settings.port,
        settings.debug,
        "configured" if settings.neo4j_configured else "not_configured",
        settings.ldap_host or "(unset)",
        settings.hypervisor_type or "(unset)",
    )
