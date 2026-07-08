"""Active Directory honey-object provisioning for authorized labs.

Creates/deletes honey users and bait computer accounts inside a dedicated OU.
Breadcrumbs and shadow-DC modules remain plan/graph-only until later chunks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import import_module
import secrets
import string
from typing import Any

from app.core.connection_manager import LDAPConfig


# NORMAL_ACCOUNT | ACCOUNTDISABLE
UAC_DISABLED_USER = 0x0202
# WORKSTATION_TRUST_ACCOUNT | ACCOUNTDISABLE
UAC_DISABLED_COMPUTER = 0x1002


@dataclass
class ProvisionedObject:
    object_type: str
    name: str
    dn: str
    action: str
    success: bool
    message: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightResult:
    ok: bool
    message: str
    honey_ou: str = ""
    base_dn: str = ""
    debug: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)


class ADProvisioner:
    """LDAP write path for honey users and bait computers."""

    PROVISIONABLE = frozenset({"HoneyUser", "HoneyServer"})

    def __init__(
        self,
        *,
        honey_ou: str,
        name_prefix: str = "hw_",
        require_prefix: bool = True,
        description_tag: str = "ActiveDecoy honey object — authorized lab only",
        harden_users: bool = False,
        workstations_lock: str = "NONEXISTENT-AD-LOCK",
    ) -> None:
        self.honey_ou = honey_ou.strip()
        self.name_prefix = (name_prefix or "").strip()
        self.require_prefix = require_prefix
        self.description_tag = description_tag
        self.harden_users = harden_users
        self.workstations_lock = (workstations_lock or "NONEXISTENT-AD-LOCK").strip()

    def preflight(self, config: LDAPConfig) -> PreflightResult:
        debug: list[str] = []
        checks: dict[str, Any] = {
            "ldap_host": bool(config.host.strip()),
            "honey_ou_configured": bool(self.honey_ou),
            "honey_ou_exists": False,
            "under_base_dn": False,
            "bind_ok": False,
        }

        if not config.host.strip():
            return PreflightResult(False, "LDAP host is required.", debug=debug, checks=checks)
        if not self.honey_ou:
            return PreflightResult(
                False,
                "AD_HONEY_OU is not configured. Set a dedicated OU before provisioning.",
                debug=["Example: OU=Honey,OU=Lab,DC=lab,DC=local"],
                checks=checks,
            )

        ldap3 = self._load_ldap3()
        if ldap3 is None:
            return PreflightResult(False, "ldap3 is not installed.", debug=debug, checks=checks)

        try:
            connection = self._connect(config, ldap3)
            checks["bind_ok"] = True
            debug.append("LDAP bind succeeded for preflight.")

            base_dn = (config.base_dn or "").strip() or self._discover_base_dn(connection, ldap3, debug)
            checks["under_base_dn"] = (
                not base_dn or self.honey_ou.lower().endswith(base_dn.lower()) or base_dn.lower() in self.honey_ou.lower()
            )
            if base_dn and not checks["under_base_dn"]:
                connection.unbind()
                return PreflightResult(
                    False,
                    f"Honey OU must be under the directory base DN ({base_dn}).",
                    honey_ou=self.honey_ou,
                    base_dn=base_dn,
                    debug=debug,
                    checks=checks,
                )

            exists = self._ou_exists(connection, ldap3, self.honey_ou)
            checks["honey_ou_exists"] = exists
            if not exists:
                connection.unbind()
                return PreflightResult(
                    False,
                    f"Honey OU does not exist: {self.honey_ou}. Create it in AD before deploying.",
                    honey_ou=self.honey_ou,
                    base_dn=base_dn,
                    debug=debug,
                    checks=checks,
                )

            connection.unbind()
            return PreflightResult(
                True,
                "Provisioning preflight passed.",
                honey_ou=self.honey_ou,
                base_dn=base_dn,
                debug=debug,
                checks=checks,
            )
        except Exception as exc:
            debug.append(str(exc))
            return PreflightResult(False, f"Preflight failed: {exc}", honey_ou=self.honey_ou, debug=debug, checks=checks)

    def provision_objects(
        self,
        config: LDAPConfig,
        objects: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        preflight = self.preflight(config)
        if not preflight.ok:
            return {
                "success": False,
                "dry_run": dry_run,
                "message": preflight.message,
                "preflight": asdict(preflight),
                "results": [],
                "created": [],
            }

        results: list[ProvisionedObject] = []
        created: list[dict[str, Any]] = []
        ldap3 = self._load_ldap3()
        assert ldap3 is not None

        connection = None
        try:
            if not dry_run:
                connection = self._connect(config, ldap3)

            for item in objects:
                object_type = str(item.get("object_type", ""))
                if object_type not in self.PROVISIONABLE:
                    results.append(
                        ProvisionedObject(
                            object_type=object_type or "Unknown",
                            name=str(item.get("name", "")),
                            dn="",
                            action="skipped",
                            success=True,
                            message="Not provisioned in AD (plan/graph only).",
                        )
                    )
                    continue

                safe_name = self._ensure_prefix(str(item.get("name", "")))
                if object_type == "HoneyUser":
                    result = self._provision_user(connection, ldap3, item, safe_name, dry_run=dry_run)
                else:
                    result = self._provision_computer(connection, ldap3, item, safe_name, dry_run=dry_run)
                results.append(result)
                if result.success and result.action in {"created", "updated", "would_create"}:
                    created.append(asdict(result))

            attempted = [item for item in results if item.action not in {"skipped"}]
            success = all(item.success for item in attempted) if attempted else True

            return {
                "success": success,
                "dry_run": dry_run,
                "message": self._summarize(results, dry_run=dry_run),
                "preflight": asdict(preflight),
                "results": [asdict(item) for item in results],
                "created": created,
            }
        except Exception as exc:
            return {
                "success": False,
                "dry_run": dry_run,
                "message": f"Provisioning failed: {exc}",
                "preflight": asdict(preflight),
                "results": [asdict(item) for item in results],
                "created": created,
                "errors": [str(exc)],
            }
        finally:
            if connection is not None:
                try:
                    connection.unbind()
                except Exception:
                    pass

    def teardown_objects(
        self,
        config: LDAPConfig,
        provisioned: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        preflight = self.preflight(config)
        if not preflight.ok:
            return {
                "success": False,
                "dry_run": dry_run,
                "message": preflight.message,
                "results": [],
            }

        ldap3 = self._load_ldap3()
        assert ldap3 is not None
        results: list[ProvisionedObject] = []
        connection = None

        try:
            if not dry_run:
                connection = self._connect(config, ldap3)

            for item in provisioned:
                dn = str(item.get("dn") or "")
                name = str(item.get("name") or "")
                object_type = str(item.get("object_type") or "")
                if not dn:
                    results.append(
                        ProvisionedObject(
                            object_type=object_type,
                            name=name,
                            dn="",
                            action="skipped",
                            success=True,
                            message="No DN recorded; nothing to delete.",
                        )
                    )
                    continue
                if not self._is_safe_dn(dn):
                    results.append(
                        ProvisionedObject(
                            object_type=object_type,
                            name=name,
                            dn=dn,
                            action="blocked",
                            success=False,
                            message="Refusing to delete object outside honey OU or without required prefix.",
                        )
                    )
                    continue

                if dry_run:
                    results.append(
                        ProvisionedObject(
                            object_type=object_type,
                            name=name,
                            dn=dn,
                            action="would_delete",
                            success=True,
                            message="Dry-run: object would be deleted.",
                        )
                    )
                    continue

                assert connection is not None
                ok = connection.delete(dn)
                if ok:
                    results.append(
                        ProvisionedObject(
                            object_type=object_type,
                            name=name,
                            dn=dn,
                            action="deleted",
                            success=True,
                            message="Deleted from Active Directory.",
                        )
                    )
                else:
                    results.append(
                        ProvisionedObject(
                            object_type=object_type,
                            name=name,
                            dn=dn,
                            action="delete_failed",
                            success=False,
                            message=str(connection.result),
                        )
                    )

            attempted = [item for item in results if item.action not in {"skipped"}]
            success = all(item.success for item in attempted) if attempted else True
            return {
                "success": success,
                "dry_run": dry_run,
                "message": self._summarize_teardown(results, dry_run=dry_run),
                "results": [asdict(item) for item in results],
            }
        except Exception as exc:
            return {
                "success": False,
                "dry_run": dry_run,
                "message": f"Teardown failed: {exc}",
                "results": [asdict(item) for item in results],
                "errors": [str(exc)],
            }
        finally:
            if connection is not None:
                try:
                    connection.unbind()
                except Exception:
                    pass

    def _provision_user(
        self,
        connection: Any,
        ldap3: Any,
        item: dict[str, Any],
        name: str,
        *,
        dry_run: bool,
    ) -> ProvisionedObject:
        dn = f"CN={self._escape_cn(name)},{self.honey_ou}"
        display = str((item.get("attributes") or {}).get("display_name") or name)
        password = self._generate_password()
        attrs = {
            "objectClass": ["top", "person", "organizationalPerson", "user"],
            "cn": name,
            "sAMAccountName": name,
            "userPrincipalName": f"{name}@{self._upn_suffix()}",
            "displayName": display,
            "description": self.description_tag,
            "userAccountControl": UAC_DISABLED_USER,
        }
        if self.harden_users:
            attrs["userWorkstations"] = self.workstations_lock

        if dry_run:
            return ProvisionedObject(
                object_type="HoneyUser",
                name=name,
                dn=dn,
                action="would_create",
                success=True,
                message="Dry-run: honey user would be created (disabled + workstation lock).",
                attributes={
                    "userAccountControl": UAC_DISABLED_USER,
                    "userWorkstations": self.workstations_lock if self.harden_users else "",
                },
            )

        assert connection is not None
        if self._object_exists(connection, ldap3, dn):
            mods: dict[str, Any] = {
                "description": [(ldap3.MODIFY_REPLACE, [self.description_tag])],
                "userAccountControl": [(ldap3.MODIFY_REPLACE, [UAC_DISABLED_USER])],
            }
            if self.harden_users:
                mods["userWorkstations"] = [(ldap3.MODIFY_REPLACE, [self.workstations_lock])]
            connection.modify(dn, mods)
            return ProvisionedObject(
                object_type="HoneyUser",
                name=name,
                dn=dn,
                action="updated",
                success=True,
                message="Honey user already existed; refreshed disable/hardening attributes.",
                attributes={
                    "userAccountControl": UAC_DISABLED_USER,
                    "userWorkstations": self.workstations_lock if self.harden_users else "",
                },
            )

        ok = connection.add(dn, attributes=attrs)
        if not ok:
            return ProvisionedObject(
                object_type="HoneyUser",
                name=name,
                dn=dn,
                action="create_failed",
                success=False,
                message=str(connection.result),
            )

        # Best-effort password set; disabled bait accounts do not need interactive logon.
        try:
            connection.extend.microsoft.modify_password(dn, password)
        except Exception:
            pass

        return ProvisionedObject(
            object_type="HoneyUser",
            name=name,
            dn=dn,
            action="created",
            success=True,
            message="Honey user created, disabled, and hardened.",
            attributes={
                "userAccountControl": UAC_DISABLED_USER,
                "display_name": display,
                "userWorkstations": self.workstations_lock if self.harden_users else "",
            },
        )

    def _provision_computer(
        self,
        connection: Any,
        ldap3: Any,
        item: dict[str, Any],
        name: str,
        *,
        dry_run: bool,
    ) -> ProvisionedObject:
        sam = name if name.endswith("$") else f"{name}$"
        cn = name.rstrip("$")
        dn = f"CN={self._escape_cn(cn)},{self.honey_ou}"
        spns = list((item.get("attributes") or {}).get("spns") or [])
        attrs: dict[str, Any] = {
            "objectClass": ["top", "person", "organizationalPerson", "user", "computer"],
            "cn": cn,
            "sAMAccountName": sam,
            "userAccountControl": UAC_DISABLED_COMPUTER,
            "description": self.description_tag,
        }
        if spns:
            attrs["servicePrincipalName"] = spns

        if dry_run:
            return ProvisionedObject(
                object_type="HoneyServer",
                name=cn,
                dn=dn,
                action="would_create",
                success=True,
                message="Dry-run: bait computer would be created (disabled) with SPNs.",
                attributes={"spns": spns, "userAccountControl": UAC_DISABLED_COMPUTER},
            )

        assert connection is not None
        if self._object_exists(connection, ldap3, dn):
            modifications = {
                "description": [(ldap3.MODIFY_REPLACE, [self.description_tag])],
                "userAccountControl": [(ldap3.MODIFY_REPLACE, [UAC_DISABLED_COMPUTER])],
            }
            if spns:
                modifications["servicePrincipalName"] = [(ldap3.MODIFY_REPLACE, spns)]
            connection.modify(dn, modifications)
            return ProvisionedObject(
                object_type="HoneyServer",
                name=cn,
                dn=dn,
                action="updated",
                success=True,
                message="Bait computer already existed; refreshed SPNs/description.",
                attributes={"spns": spns},
            )

        ok = connection.add(dn, attributes=attrs)
        if not ok:
            return ProvisionedObject(
                object_type="HoneyServer",
                name=cn,
                dn=dn,
                action="create_failed",
                success=False,
                message=str(connection.result),
            )
        return ProvisionedObject(
            object_type="HoneyServer",
            name=cn,
            dn=dn,
            action="created",
            success=True,
            message="Bait computer created (disabled) with monitored SPNs.",
            attributes={"spns": spns, "sam_account_name": sam},
        )

    def _ensure_prefix(self, name: str) -> str:
        cleaned = "".join(ch for ch in name.strip() if ch.isalnum() or ch in ".-_")
        if not cleaned:
            cleaned = "decoy"
        if self.require_prefix and self.name_prefix and not cleaned.lower().startswith(self.name_prefix.lower()):
            return f"{self.name_prefix}{cleaned}"
        return cleaned

    def _is_safe_dn(self, dn: str) -> bool:
        if not dn.lower().endswith(self.honey_ou.lower()):
            return False
        if not self.require_prefix or not self.name_prefix:
            return True
        cn = dn.split(",", 1)[0]
        value = cn.split("=", 1)[1] if "=" in cn else cn
        return value.lower().startswith(self.name_prefix.lower())

    def _upn_suffix(self) -> str:
        parts = []
        for chunk in self.honey_ou.split(","):
            chunk = chunk.strip()
            if chunk.upper().startswith("DC="):
                parts.append(chunk.split("=", 1)[1])
        return ".".join(parts) if parts else "lab.local"

    @staticmethod
    def _escape_cn(value: str) -> str:
        # Escape LDAP DN special characters in CN.
        out = value
        for ch in ("\\", ",", "+", '"', "<", ">", ";", "="):
            out = out.replace(ch, f"\\{ch}")
        return out

    @staticmethod
    def _generate_password(length: int = 24) -> str:
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def _summarize(results: list[ProvisionedObject], *, dry_run: bool) -> str:
        created = sum(1 for item in results if item.action in {"created", "would_create"})
        updated = sum(1 for item in results if item.action == "updated")
        skipped = sum(1 for item in results if item.action == "skipped")
        failed = sum(1 for item in results if not item.success)
        verb = "Would provision" if dry_run else "Provisioned"
        return f"{verb}: {created} new, {updated} updated, {skipped} skipped, {failed} failed."

    @staticmethod
    def _summarize_teardown(results: list[ProvisionedObject], *, dry_run: bool) -> str:
        deleted = sum(1 for item in results if item.action in {"deleted", "would_delete"})
        blocked = sum(1 for item in results if item.action == "blocked")
        failed = sum(1 for item in results if not item.success)
        verb = "Would remove" if dry_run else "Removed"
        return f"{verb}: {deleted} object(s); blocked={blocked}; failed={failed}."

    def _connect(self, config: LDAPConfig, ldap3: Any) -> Any:
        server = ldap3.Server(config.host, port=config.port, use_ssl=config.use_ssl, get_info=ldap3.NONE)
        connection = ldap3.Connection(
            server,
            user=config.bind_dn or None,
            password=config.password or None,
            auto_bind=True,
            receive_timeout=config.timeout,
            authentication=ldap3.SIMPLE,
        )
        return connection

    def _ou_exists(self, connection: Any, ldap3: Any, dn: str) -> bool:
        return connection.search(
            search_base=dn,
            search_filter="(objectClass=*)",
            search_scope=ldap3.BASE,
            attributes=["distinguishedName"],
        ) and bool(connection.entries)

    def _object_exists(self, connection: Any, ldap3: Any, dn: str) -> bool:
        return self._ou_exists(connection, ldap3, dn)

    def _discover_base_dn(self, connection: Any, ldap3: Any, debug: list[str]) -> str:
        connection.search(
            search_base="",
            search_filter="(objectClass=*)",
            search_scope=ldap3.BASE,
            attributes=["defaultNamingContext", "rootDomainNamingContext"],
        )
        if not connection.entries:
            return ""
        entry = connection.entries[0]
        base = str(getattr(entry, "defaultNamingContext", "") or getattr(entry, "rootDomainNamingContext", "") or "")
        if base:
            debug.append(f"Discovered base DN: {base}")
        return base

    def _load_ldap3(self) -> Any | None:
        try:
            return import_module("ldap3")
        except Exception:
            return None


def stamp_provision_names(objects: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Return a copy of deployment objects with safety prefix applied to provisionable names."""

    provisioner = ADProvisioner(honey_ou="OU=Honey", name_prefix=prefix, require_prefix=True)
    stamped: list[dict[str, Any]] = []
    for item in objects:
        copy = dict(item)
        attrs = dict(copy.get("attributes") or {})
        if copy.get("object_type") in ADProvisioner.PROVISIONABLE:
            original = str(copy.get("name", ""))
            safe = provisioner._ensure_prefix(original)
            copy["name"] = safe
            attrs["original_name"] = original
            attrs["provisioned_name"] = safe
        copy["attributes"] = attrs
        stamped.append(copy)
    return stamped


def new_deployment_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"dep-{ts}-{secrets.token_hex(3)}"
