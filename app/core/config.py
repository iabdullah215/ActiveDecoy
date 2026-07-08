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
_DEFAULT_CORS_ORIGINS = "http://127.0.0.1:8000,http://localhost:8000"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_bool(key: str, default: str = "false") -> bool:
    return _env(key, default).lower() in {"1", "true", "yes", "on"}


def parse_cors_origins(raw: str) -> list[str]:
    """Parse a comma-separated CORS allowlist. Empty means same-origin only (no CORS)."""

    return [part.strip() for part in raw.split(",") if part.strip()]


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
    enforce_secure_defaults: bool
    cors_origins: tuple[str, ...]
    login_rate_limit: int
    login_rate_window_seconds: int
    agent_ingest_token: str
    agent_stale_seconds: int
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
    ldap_page_size: int
    ldap_max_objects: int
    ad_honey_ou: str
    ad_honey_name_prefix: str
    ad_require_name_prefix: bool
    ad_provision_enabled: bool

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
        debug=_env_bool("APP_DEBUG", "false"),
        enforce_secure_defaults=_env_bool("ENFORCE_SECURE_DEFAULTS", "false"),
        cors_origins=tuple(parse_cors_origins(_env("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS))),
        login_rate_limit=int(_env("LOGIN_RATE_LIMIT", "5")),
        login_rate_window_seconds=int(_env("LOGIN_RATE_WINDOW_SECONDS", "60")),
        agent_ingest_token=_env("AGENT_INGEST_TOKEN", ""),
        agent_stale_seconds=int(_env("AGENT_STALE_SECONDS", "90")),
        ldap_host=_env("LDAP_HOST", "dc01.lab.local"),
        ldap_port=int(_env("LDAP_PORT", "389")),
        ldap_use_ssl=_env_bool("LDAP_USE_SSL", "false"),
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
        ldap_page_size=int(_env("LDAP_PAGE_SIZE", "200")),
        ldap_max_objects=int(_env("LDAP_MAX_OBJECTS", "500")),
        ad_honey_ou=_env("AD_HONEY_OU", ""),
        ad_honey_name_prefix=_env("AD_HONEY_NAME_PREFIX", "hw_"),
        ad_require_name_prefix=_env_bool("AD_REQUIRE_NAME_PREFIX", "true"),
        ad_provision_enabled=_env_bool("AD_PROVISION_ENABLED", "false"),
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
    if settings.login_rate_limit < 1:
        warnings.append("LOGIN_RATE_LIMIT should be >= 1.")
    if settings.login_rate_window_seconds < 1:
        warnings.append("LOGIN_RATE_WINDOW_SECONDS should be >= 1.")
    if settings.ldap_page_size < 1:
        warnings.append("LDAP_PAGE_SIZE should be >= 1.")
    if settings.ldap_max_objects < 1:
        warnings.append("LDAP_MAX_OBJECTS should be >= 1.")
    if settings.ad_provision_enabled and not settings.ad_honey_ou:
        warnings.append("AD_PROVISION_ENABLED is true but AD_HONEY_OU is empty.")
    if not settings.agent_ingest_token:
        warnings.append("AGENT_INGEST_TOKEN is empty; agent telemetry ingest stays disabled.")
    if settings.agent_stale_seconds < 15:
        warnings.append("AGENT_STALE_SECONDS should be >= 15.")
    if not settings.cors_origins:
        warnings.append("CORS_ORIGINS is empty; browser cross-origin API calls will be blocked.")
    return warnings


def enforce_startup_guards(settings: Settings) -> None:
    """Abort startup when shared-lab hardening is required but defaults remain."""

    if not settings.enforce_secure_defaults:
        return

    blockers: list[str] = []
    if settings.using_default_admin_credentials:
        blockers.append("default ADMIN_USERNAME/ADMIN_PASSWORD")
    if settings.using_default_session_secret:
        blockers.append("default SESSION_SECRET")
    if blockers:
        message = (
            "ENFORCE_SECURE_DEFAULTS=true but insecure defaults remain: "
            + ", ".join(blockers)
            + ". Update .env and restart."
        )
        logger.error(message)
        raise SystemExit(message)


def log_settings_summary(settings: Settings) -> None:
    """Log a redacted startup summary and any validation warnings."""

    for warning in validate_settings(settings):
        logger.warning("Config: %s", warning)

    logger.info(
        "ActiveDecoy starting host=%s:%s debug=%s neo4j=%s ldap_host=%s hypervisor=%s cors=%s rate_limit=%s/%ss",
        settings.host,
        settings.port,
        settings.debug,
        "configured" if settings.neo4j_configured else "not_configured",
        settings.ldap_host or "(unset)",
        settings.hypervisor_type or "(unset)",
        ",".join(settings.cors_origins) or "(none)",
        settings.login_rate_limit,
        settings.login_rate_window_seconds,
    )


