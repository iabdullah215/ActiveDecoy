"""LDAP directory enumeration for authorized lab environments.

Reads users, groups, computers, memberships, and trust objects. Does not write
to Active Directory — provisioning is Chunk 4.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from app.core.connection_manager import LDAPConfig


@dataclass
class DirectoryObject:
    object_type: str
    name: str
    dn: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class DirectoryMembership:
    member_dn: str
    group_dn: str


@dataclass
class DirectoryTrust:
    name: str
    dn: str
    direction: str = ""
    partner: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class DirectorySnapshot:
    enumerated_at: str
    base_dn: str
    domain: str
    users: list[DirectoryObject] = field(default_factory=list)
    groups: list[DirectoryObject] = field(default_factory=list)
    computers: list[DirectoryObject] = field(default_factory=list)
    memberships: list[DirectoryMembership] = field(default_factory=list)
    trusts: list[DirectoryTrust] = field(default_factory=list)
    debug: list[str] = field(default_factory=list)
    truncated: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "enumerated_at": self.enumerated_at,
            "base_dn": self.base_dn,
            "domain": self.domain,
            "users": len(self.users),
            "groups": len(self.groups),
            "computers": len(self.computers),
            "memberships": len(self.memberships),
            "trusts": len(self.trusts),
            "truncated": self.truncated,
        }


def snapshot_to_dict(snapshot: DirectorySnapshot) -> dict[str, Any]:
    return {
        "enumerated_at": snapshot.enumerated_at,
        "base_dn": snapshot.base_dn,
        "domain": snapshot.domain,
        "users": [asdict(item) for item in snapshot.users],
        "groups": [asdict(item) for item in snapshot.groups],
        "computers": [asdict(item) for item in snapshot.computers],
        "memberships": [asdict(item) for item in snapshot.memberships],
        "trusts": [asdict(item) for item in snapshot.trusts],
        "debug": list(snapshot.debug),
        "truncated": snapshot.truncated,
        "summary": snapshot.summary(),
    }


def snapshot_from_dict(data: dict[str, Any] | None) -> DirectorySnapshot | None:
    if not isinstance(data, dict) or not data.get("base_dn"):
        return None
    return DirectorySnapshot(
        enumerated_at=str(data.get("enumerated_at", "")),
        base_dn=str(data.get("base_dn", "")),
        domain=str(data.get("domain", "")),
        users=[DirectoryObject(**item) for item in data.get("users", []) if isinstance(item, dict)],
        groups=[DirectoryObject(**item) for item in data.get("groups", []) if isinstance(item, dict)],
        computers=[DirectoryObject(**item) for item in data.get("computers", []) if isinstance(item, dict)],
        memberships=[
            DirectoryMembership(**item) for item in data.get("memberships", []) if isinstance(item, dict)
        ],
        trusts=[DirectoryTrust(**item) for item in data.get("trusts", []) if isinstance(item, dict)],
        debug=list(data.get("debug", [])),
        truncated=bool(data.get("truncated", False)),
    )


class DirectoryEnumerator:
    """Enumerate AD objects over LDAP for graph import."""

    USER_FILTER = "(&(objectCategory=person)(objectClass=user))"
    GROUP_FILTER = "(objectClass=group)"
    COMPUTER_FILTER = "(objectClass=computer)"
    TRUST_FILTER = "(objectClass=trustedDomain)"

    USER_ATTRS = [
        "distinguishedName",
        "sAMAccountName",
        "displayName",
        "userAccountControl",
        "memberOf",
        "mail",
        "description",
    ]
    GROUP_ATTRS = [
        "distinguishedName",
        "sAMAccountName",
        "cn",
        "description",
        "member",
        "groupType",
    ]
    COMPUTER_ATTRS = [
        "distinguishedName",
        "sAMAccountName",
        "dNSHostName",
        "operatingSystem",
        "userAccountControl",
        "description",
    ]
    TRUST_ATTRS = [
        "distinguishedName",
        "cn",
        "trustPartner",
        "trustDirection",
        "trustType",
        "trustAttributes",
    ]

    def __init__(self, *, page_size: int = 200, max_objects: int = 500) -> None:
        self.page_size = max(1, page_size)
        self.max_objects = max(1, max_objects)

    def enumerate(self, config: LDAPConfig) -> DirectorySnapshot:
        debug: list[str] = []
        ldap3 = self._load_ldap3()
        if ldap3 is None:
            raise RuntimeError("ldap3 is not installed in the active environment.")

        if not config.host.strip():
            raise ValueError("LDAP host is required for enumeration.")

        server = ldap3.Server(config.host, port=config.port, use_ssl=config.use_ssl, get_info=ldap3.ALL)
        connection = ldap3.Connection(
            server,
            user=config.bind_dn or None,
            password=config.password or None,
            auto_bind=True,
            receive_timeout=config.timeout,
            auto_range=True,
        )
        debug.append(f"Bound to {config.host}:{config.port} for enumeration.")

        try:
            base_dn = (config.base_dn or "").strip() or self._discover_base_dn(connection, ldap3, debug)
            if not base_dn:
                raise RuntimeError("Could not determine LDAP base DN. Set LDAP base DN and retry.")

            domain = self._domain_from_dn(base_dn)
            truncated = False
            users: list[DirectoryObject] = []
            groups: list[DirectoryObject] = []
            computers: list[DirectoryObject] = []
            trusts: list[DirectoryTrust] = []
            memberships: list[DirectoryMembership] = []

            user_result = self._paged_search(
                connection,
                ldap3,
                base_dn,
                self.USER_FILTER,
                self.USER_ATTRS,
                debug,
                label="users",
            )
            truncated = truncated or user_result["truncated"]
            for entry in user_result["entries"]:
                obj = self._user_from_entry(entry)
                if obj:
                    users.append(obj)
                    for group_dn in obj.attributes.get("member_of", []):
                        memberships.append(DirectoryMembership(member_dn=obj.dn, group_dn=group_dn))

            group_result = self._paged_search(
                connection,
                ldap3,
                base_dn,
                self.GROUP_FILTER,
                self.GROUP_ATTRS,
                debug,
                label="groups",
            )
            truncated = truncated or group_result["truncated"]
            for entry in group_result["entries"]:
                obj = self._group_from_entry(entry)
                if obj:
                    groups.append(obj)
                    for member_dn in obj.attributes.get("members", []):
                        memberships.append(DirectoryMembership(member_dn=member_dn, group_dn=obj.dn))

            computer_result = self._paged_search(
                connection,
                ldap3,
                base_dn,
                self.COMPUTER_FILTER,
                self.COMPUTER_ATTRS,
                debug,
                label="computers",
            )
            truncated = truncated or computer_result["truncated"]
            for entry in computer_result["entries"]:
                obj = self._computer_from_entry(entry)
                if obj:
                    computers.append(obj)

            trust_result = self._paged_search(
                connection,
                ldap3,
                base_dn,
                self.TRUST_FILTER,
                self.TRUST_ATTRS,
                debug,
                label="trusts",
            )
            truncated = truncated or trust_result["truncated"]
            for entry in trust_result["entries"]:
                trust = self._trust_from_entry(entry)
                if trust:
                    trusts.append(trust)

            memberships = self._dedupe_memberships(memberships)
            debug.append(
                "Enumeration complete: "
                f"{len(users)} users, {len(groups)} groups, {len(computers)} computers, "
                f"{len(trusts)} trusts, {len(memberships)} memberships."
            )
            if truncated:
                debug.append(f"Results truncated at max_objects={self.max_objects} per category.")

            return DirectorySnapshot(
                enumerated_at=datetime.now(timezone.utc).isoformat(),
                base_dn=base_dn,
                domain=domain,
                users=users,
                groups=groups,
                computers=computers,
                memberships=memberships,
                trusts=trusts,
                debug=debug,
                truncated=truncated,
            )
        finally:
            try:
                connection.unbind()
            except Exception:
                pass

    def _paged_search(
        self,
        connection: Any,
        ldap3: Any,
        base_dn: str,
        search_filter: str,
        attributes: list[str],
        debug: list[str],
        *,
        label: str,
    ) -> dict[str, Any]:
        entries: list[Any] = []
        truncated = False
        cookie: Any = True
        pages = 0

        while cookie and len(entries) < self.max_objects:
            remaining = self.max_objects - len(entries)
            size = min(self.page_size, remaining)
            conn_ok = connection.search(
                search_base=base_dn,
                search_filter=search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=attributes,
                paged_size=size,
                paged_cookie=None if cookie is True else cookie,
            )
            pages += 1
            if not conn_ok and not connection.entries:
                debug.append(f"{label}: search returned no entries (page {pages}).")
                break

            for entry in connection.entries:
                entries.append(entry)
                if len(entries) >= self.max_objects:
                    truncated = True
                    break

            cookie = connection.result.get("controls", {}).get(
                "1.2.840.113556.1.4.319", {}
            ).get("value", {}).get("cookie")
            if not cookie:
                break

        debug.append(f"{label}: collected {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} across {pages} page(s).")
        return {"entries": entries, "truncated": truncated}

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
            debug.append(f"Discovered base DN from root DSE: {base}")
        return base

    def _user_from_entry(self, entry: Any) -> DirectoryObject | None:
        dn = self._attr(entry, "distinguishedName")
        name = self._attr(entry, "sAMAccountName") or self._cn_from_dn(dn)
        if not dn or not name:
            return None
        uac = self._as_int(self._attr(entry, "userAccountControl"))
        return DirectoryObject(
            object_type="ADUser",
            name=name,
            dn=dn,
            attributes={
                "display_name": self._attr(entry, "displayName") or name,
                "mail": self._attr(entry, "mail"),
                "description": self._attr(entry, "description"),
                "enabled": self._account_enabled(uac),
                "user_account_control": uac,
                "member_of": self._attr_list(entry, "memberOf"),
            },
        )

    def _group_from_entry(self, entry: Any) -> DirectoryObject | None:
        dn = self._attr(entry, "distinguishedName")
        name = self._attr(entry, "sAMAccountName") or self._attr(entry, "cn") or self._cn_from_dn(dn)
        if not dn or not name:
            return None
        return DirectoryObject(
            object_type="ADGroup",
            name=name,
            dn=dn,
            attributes={
                "description": self._attr(entry, "description"),
                "group_type": self._as_int(self._attr(entry, "groupType")),
                "members": self._attr_list(entry, "member"),
            },
        )

    def _computer_from_entry(self, entry: Any) -> DirectoryObject | None:
        dn = self._attr(entry, "distinguishedName")
        name = (self._attr(entry, "sAMAccountName") or self._cn_from_dn(dn)).rstrip("$")
        if not dn or not name:
            return None
        uac = self._as_int(self._attr(entry, "userAccountControl"))
        return DirectoryObject(
            object_type="ADComputer",
            name=name,
            dn=dn,
            attributes={
                "dns_hostname": self._attr(entry, "dNSHostName"),
                "operating_system": self._attr(entry, "operatingSystem"),
                "description": self._attr(entry, "description"),
                "enabled": self._account_enabled(uac),
                "user_account_control": uac,
            },
        )

    def _trust_from_entry(self, entry: Any) -> DirectoryTrust | None:
        dn = self._attr(entry, "distinguishedName")
        name = self._attr(entry, "cn") or self._cn_from_dn(dn)
        if not dn or not name:
            return None
        direction_code = self._as_int(self._attr(entry, "trustDirection"))
        return DirectoryTrust(
            name=name,
            dn=dn,
            direction=self._trust_direction_label(direction_code),
            partner=self._attr(entry, "trustPartner") or name,
            attributes={
                "trust_type": self._as_int(self._attr(entry, "trustType")),
                "trust_attributes": self._as_int(self._attr(entry, "trustAttributes")),
                "trust_direction": direction_code,
            },
        )

    @staticmethod
    def _dedupe_memberships(items: list[DirectoryMembership]) -> list[DirectoryMembership]:
        seen: set[tuple[str, str]] = set()
        unique: list[DirectoryMembership] = []
        for item in items:
            key = (item.member_dn.lower(), item.group_dn.lower())
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    @staticmethod
    def _attr(entry: Any, name: str) -> str:
        try:
            value = entry[name].value if name in entry else ""
        except Exception:
            value = getattr(entry, name, "")
            value = getattr(value, "value", value)
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _attr_list(entry: Any, name: str) -> list[str]:
        try:
            raw = entry[name].value if name in entry else []
        except Exception:
            raw = getattr(getattr(entry, name, None), "value", [])
        if raw is None:
            return []
        if isinstance(raw, (list, tuple, set)):
            return [str(item).strip() for item in raw if str(item).strip()]
        text = str(raw).strip()
        return [text] if text else []

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _account_enabled(uac: int) -> bool:
        # ADS_UF_ACCOUNTDISABLE = 0x2
        return not bool(uac & 0x2) if uac else True

    @staticmethod
    def _trust_direction_label(code: int) -> str:
        return {
            0: "disabled",
            1: "inbound",
            2: "outbound",
            3: "bidirectional",
        }.get(code, f"unknown({code})")

    @staticmethod
    def _cn_from_dn(dn: str) -> str:
        if not dn:
            return ""
        first = dn.split(",", 1)[0]
        if "=" in first:
            return first.split("=", 1)[1].strip()
        return first.strip()

    @staticmethod
    def _domain_from_dn(base_dn: str) -> str:
        parts = []
        for chunk in base_dn.split(","):
            chunk = chunk.strip()
            if chunk.upper().startswith("DC="):
                parts.append(chunk.split("=", 1)[1])
        return ".".join(parts) if parts else base_dn

    def _load_ldap3(self) -> Any | None:
        try:
            return import_module("ldap3")
        except Exception:
            return None
