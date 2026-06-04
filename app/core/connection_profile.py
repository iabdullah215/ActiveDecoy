"""Connection profile persistence for LDAP and hypervisor lab bridges."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.core.connection_manager import HypervisorConfig, HypervisorType, LDAPConfig


SENSITIVE_KEYS = frozenset({"ldap_password", "hypervisor_password"})


@dataclass
class ConnectionProfile:
    ldap_host: str = ""
    ldap_port: int = 389
    ldap_use_ssl: bool = False
    ldap_bind_dn: str = ""
    ldap_password: str = ""
    ldap_base_dn: str = ""
    hypervisor_type: str = HypervisorType.VMWARE.value
    hypervisor_endpoint: str = ""
    hypervisor_username: str = ""
    hypervisor_password: str = ""
    hypervisor_vm_name: str = ""
    wrapper_command: str = ""
    auto_test_on_load: bool = True
    last_tested_at: str = ""

    @classmethod
    def from_settings(cls, settings: Settings) -> ConnectionProfile:
        return cls(
            ldap_host=settings.ldap_host,
            ldap_port=settings.ldap_port,
            ldap_use_ssl=settings.ldap_use_ssl,
            ldap_bind_dn=settings.ldap_bind_dn,
            ldap_password=settings.ldap_password,
            ldap_base_dn=settings.ldap_base_dn,
            hypervisor_type=settings.hypervisor_type or HypervisorType.VMWARE.value,
            hypervisor_endpoint=settings.hypervisor_endpoint,
            hypervisor_username=settings.hypervisor_username,
            hypervisor_password=settings.hypervisor_password,
            hypervisor_vm_name=settings.hypervisor_vm_name,
            wrapper_command=settings.wrapper_command,
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> ConnectionProfile:
        if not data:
            return cls()
        return cls(
            ldap_host=str(data.get("ldap_host", "")).strip(),
            ldap_port=int(data.get("ldap_port", 389) or 389),
            ldap_use_ssl=_as_bool(data.get("ldap_use_ssl", False)),
            ldap_bind_dn=str(data.get("ldap_bind_dn", "")).strip(),
            ldap_password=str(data.get("ldap_password", "")),
            ldap_base_dn=str(data.get("ldap_base_dn", "")).strip(),
            hypervisor_type=str(data.get("hypervisor_type", HypervisorType.VMWARE.value)).strip().lower(),
            hypervisor_endpoint=str(data.get("hypervisor_endpoint", "")).strip(),
            hypervisor_username=str(data.get("hypervisor_username", "")).strip(),
            hypervisor_password=str(data.get("hypervisor_password", "")),
            hypervisor_vm_name=str(data.get("hypervisor_vm_name", "")).strip(),
            wrapper_command=str(data.get("wrapper_command", "")).strip(),
            auto_test_on_load=_as_bool(data.get("auto_test_on_load", True)),
            last_tested_at=str(data.get("last_tested_at", "")),
        )

    def merge_secrets(self, stored: ConnectionProfile | None) -> ConnectionProfile:
        """Keep stored passwords when the form submits an empty password field."""
        if stored is None:
            return self
        merged = ConnectionProfile(**asdict(self))
        if not merged.ldap_password:
            merged.ldap_password = stored.ldap_password
        if not merged.hypervisor_password:
            merged.hypervisor_password = stored.hypervisor_password
        return merged

    def to_ldap_config(self) -> LDAPConfig:
        return LDAPConfig(
            host=self.ldap_host,
            port=self.ldap_port,
            use_ssl=self.ldap_use_ssl,
            bind_dn=self.ldap_bind_dn,
            password=self.ldap_password,
            base_dn=self.ldap_base_dn,
        )

    def to_hypervisor_config(self) -> HypervisorConfig:
        hypervisor_type = parse_hypervisor_type(self.hypervisor_type)
        extra: dict[str, Any] = {}
        if self.wrapper_command:
            extra["wrapper_command"] = self.wrapper_command
        return HypervisorConfig(
            hypervisor_type=hypervisor_type,
            endpoint=self.hypervisor_endpoint,
            username=self.hypervisor_username,
            password=self.hypervisor_password,
            vm_name=self.hypervisor_vm_name,
            extra=extra,
        )

    def hypervisor_configured(self) -> bool:
        hypervisor_type = parse_hypervisor_type(self.hypervisor_type)
        if hypervisor_type == HypervisorType.UTM:
            return bool(self.wrapper_command)
        if hypervisor_type == HypervisorType.VMWARE:
            return bool(self.hypervisor_endpoint.strip())
        return True

    def ldap_configured(self) -> bool:
        return bool(self.ldap_host.strip())

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in SENSITIVE_KEYS:
            if payload.get(key):
                payload[key] = ""
            payload[f"{key}_set"] = bool(asdict(self).get(key))
        return payload

    def to_form_dict(self) -> dict[str, Any]:
        payload = self.to_public_dict()
        payload["ldap_port"] = self.ldap_port
        return payload

    def touch_tested(self) -> None:
        self.last_tested_at = datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def parse_hypervisor_type(value: str) -> HypervisorType:
    try:
        return HypervisorType(value.strip().lower())
    except ValueError:
        return HypervisorType.VMWARE


def load_session_profile(session: dict[str, Any], settings: Settings) -> ConnectionProfile:
    stored = session.get("connection_profile")
    if isinstance(stored, dict) and stored.get("ldap_host"):
        return ConnectionProfile.from_mapping(stored)
    return ConnectionProfile.from_settings(settings)


def save_session_profile(session: dict[str, Any], profile: ConnectionProfile) -> None:
    session["connection_profile"] = asdict(profile)


def redact_bridge_state(state: dict[str, Any]) -> dict[str, Any]:
    """Remove secrets from bridge state before rendering in the UI."""

    redacted = dict(state)
    ldap = redacted.get("ldap")
    if isinstance(ldap, dict):
        ldap = dict(ldap)
        if ldap.get("password"):
            ldap["password"] = ""
        ldap["password_set"] = bool(state.get("ldap", {}).get("password"))
        redacted["ldap"] = ldap

    hypervisor = redacted.get("hypervisor")
    if isinstance(hypervisor, dict):
        hypervisor = dict(hypervisor)
        if hypervisor.get("password"):
            hypervisor["password"] = ""
        hypervisor["password_set"] = bool(state.get("hypervisor", {}).get("password"))
        redacted["hypervisor"] = hypervisor

    return redacted
