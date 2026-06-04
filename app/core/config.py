"""Application configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass(frozen=True)
class Settings:
    session_secret: str
    app_username: str
    app_password: str
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


def get_settings() -> Settings:
    return Settings(
        session_secret=_env("SESSION_SECRET", "active-decoy-development-secret"),
        app_username=_env("APP_USERNAME", "hawtsauce"),
        app_password=_env("APP_PASSWORD", "hwatsauce"),
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
