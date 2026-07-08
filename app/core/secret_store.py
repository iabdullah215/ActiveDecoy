"""Server-side secret store for LDAP/hypervisor credentials.

Session cookies are client-visible (signed). Passwords must never live in the
session payload — only a non-secret session id is stored there.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any


@dataclass
class StoredSecrets:
    ldap_password: str = ""
    hypervisor_password: str = ""


class SecretStore:
    """Process-local secret vault keyed by opaque session secret ids."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, StoredSecrets] = {}

    def put(
        self,
        secret_id: str,
        *,
        ldap_password: str | None = None,
        hypervisor_password: str | None = None,
    ) -> None:
        if not secret_id:
            return
        with self._lock:
            current = self._items.get(secret_id, StoredSecrets())
            if ldap_password is not None:
                current.ldap_password = ldap_password
            if hypervisor_password is not None:
                current.hypervisor_password = hypervisor_password
            self._items[secret_id] = current

    def get(self, secret_id: str) -> StoredSecrets:
        if not secret_id:
            return StoredSecrets()
        with self._lock:
            current = self._items.get(secret_id)
            if current is None:
                return StoredSecrets()
            return StoredSecrets(
                ldap_password=current.ldap_password,
                hypervisor_password=current.hypervisor_password,
            )

    def clear(self, secret_id: str) -> None:
        if not secret_id:
            return
        with self._lock:
            self._items.pop(secret_id, None)

    def apply_to_profile(self, secret_id: str, profile: Any) -> Any:
        """Fill blank profile passwords from the vault."""

        secrets = self.get(secret_id)
        if not profile.ldap_password and secrets.ldap_password:
            profile.ldap_password = secrets.ldap_password
        if not profile.hypervisor_password and secrets.hypervisor_password:
            profile.hypervisor_password = secrets.hypervisor_password
        return profile

    def capture_from_profile(self, secret_id: str, profile: Any) -> None:
        """Persist non-empty profile passwords into the vault."""

        self.put(
            secret_id,
            ldap_password=profile.ldap_password or None,
            hypervisor_password=profile.hypervisor_password or None,
        )


secret_store = SecretStore()
