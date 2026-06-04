"""Connection management for ActiveDecoy.

This module keeps the implementation focused on authorized administration and
validation workflows: host detection, LDAP reachability, and hypervisor
session preparation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from importlib import import_module
import platform
import socket
import subprocess
import time
from typing import Any


class HypervisorType(str, Enum):
    """Supported hypervisor families."""

    VMWARE = "vmware"
    VIRTUALBOX = "virtualbox"
    UTM = "utm"


@dataclass
class HostEnvironment:
    os_name: str
    os_release: str
    hostname: str
    is_windows: bool
    is_windows_server: bool


@dataclass
class LDAPConfig:
    host: str
    port: int = 389
    use_ssl: bool = False
    bind_dn: str = ""
    password: str = ""
    base_dn: str = ""
    timeout: int = 8


@dataclass
class HypervisorConfig:
    hypervisor_type: HypervisorType
    endpoint: str = ""
    username: str = ""
    password: str = ""
    vm_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BridgeState:
    host: HostEnvironment
    hypervisor: HypervisorConfig | None = None
    ldap: LDAPConfig | None = None
    status: str = "not_connected"
    message: str = ""
    debug: list[str] = field(default_factory=list)


def detect_host_environment() -> HostEnvironment:
    """Return a concise summary of the current host."""

    os_name = platform.system()
    os_release = platform.release()
    hostname = socket.gethostname()
    is_windows = os_name.lower() == "windows"
    is_windows_server = is_windows and any(token in os_release.lower() for token in ("server", "2016", "2019", "2022"))

    return HostEnvironment(
        os_name=os_name,
        os_release=os_release,
        hostname=hostname,
        is_windows=is_windows,
        is_windows_server=is_windows_server,
    )


class ConnectionManager:
    """Coordinates host detection, LDAP validation, and hypervisor context."""

    def __init__(self) -> None:
        self.host_environment = detect_host_environment()

    def get_bridge_state(self) -> BridgeState:
        return BridgeState(host=self.host_environment)

    def validate_ldap_connection(self, config: LDAPConfig) -> dict[str, Any]:
        """Attempt a lightweight LDAP bind and root DSE query."""

        debug: list[str] = []
        ldap3 = self._load_ldap3()

        if ldap3 is None:
            return {
                "success": False,
                "message": "ldap3 is not installed in the active environment.",
                "debug": ["Install ldap3 before testing directory connectivity."],
            }

        try:
            server = ldap3.Server(config.host, port=config.port, use_ssl=config.use_ssl, get_info=ldap3.ALL)
            debug.append(f"Created LDAP server object for {config.host}:{config.port}.")

            connection = ldap3.Connection(
                server,
                user=config.bind_dn or None,
                password=config.password or None,
                auto_bind=True,
                receive_timeout=config.timeout,
            )
            debug.append("LDAP bind succeeded.")

            if config.base_dn:
                connection.search(
                    search_base=config.base_dn,
                    search_filter="(objectClass=*)",
                    search_scope=ldap3.SUBTREE,
                    attributes=["distinguishedName"],
                    size_limit=1,
                )
                entries = len(connection.entries)
                debug.append(f"Subtree query against {config.base_dn} returned {entries} entry or entries.")
            else:
                connection.search(
                    search_base="",
                    search_filter="(objectClass=*)",
                    search_scope=ldap3.BASE,
                    attributes=["defaultNamingContext", "dnsHostName", "rootDomainNamingContext"],
                )
                entries = len(connection.entries)
                debug.append("Root DSE query completed.")

            connection.unbind()
            return {
                "success": True,
                "message": "Connection Successful",
                "server": {
                    "host": config.host,
                    "port": config.port,
                    "use_ssl": config.use_ssl,
                    "base_dn": config.base_dn,
                    "entries": entries,
                },
                "debug": debug,
            }
        except Exception as exc:
            debug.append(f"LDAP validation failed: {exc}")
            return {
                "success": False,
                "message": "LDAP validation failed.",
                "debug": debug,
            }

    def validate_ldap_connection_with_retry(
        self,
        config: LDAPConfig,
        *,
        retries: int = 3,
        retry_delay: float = 0.5,
    ) -> dict[str, Any]:
        """Retry LDAP validation for transient network or directory delays."""

        attempts = max(1, retries)
        last_result: dict[str, Any] = {
            "success": False,
            "message": "LDAP validation did not run.",
            "debug": [],
        }

        for attempt in range(1, attempts + 1):
            last_result = self.validate_ldap_connection(config)
            debug = list(last_result.get("debug", []))
            debug.insert(0, f"LDAP attempt {attempt}/{attempts}.")
            last_result["debug"] = debug
            last_result["attempt"] = attempt
            last_result["attempts"] = attempts

            if last_result.get("success"):
                last_result["message"] = "Connection Successful"
                return last_result

            if attempt < attempts and retry_delay > 0:
                time.sleep(retry_delay)

        last_result["message"] = f"LDAP validation failed after {attempts} attempt(s)."
        return last_result

    def _load_ldap3(self) -> Any | None:
        try:
            return import_module("ldap3")
        except Exception:
            return None

    def detect_connection_mode(self) -> str:
        if self.host_environment.is_windows_server:
            return "windows_server_local_bridge"
        return "hypervisor_bridge"

    def connect_hypervisor(self, config: HypervisorConfig) -> dict[str, Any]:
        """Validate a hypervisor session and return a structured summary."""

        try:
            if config.hypervisor_type == HypervisorType.VMWARE:
                return self._connect_vmware(config)
            if config.hypervisor_type == HypervisorType.VIRTUALBOX:
                return self._connect_virtualbox(config)
            return self._connect_utm(config)
        except Exception as exc:
            return {
                "success": False,
                "message": f"Hypervisor connection failed: {exc}",
                "debug": [str(exc)],
            }

    def _connect_vmware(self, config: HypervisorConfig) -> dict[str, Any]:
        try:
            from pyVim.connect import Disconnect, SmartConnectNoSSL  # type: ignore
        except Exception:
            return {
                "success": False,
                "message": "pyVmomi is not installed or VMware SDK is unavailable.",
                "debug": ["Install pyvmomi and provide a valid vCenter or ESXi endpoint."],
            }

        if not config.endpoint or not config.username or not config.password:
            return {
                "success": False,
                "message": "VMware connection settings are incomplete.",
                "debug": ["Provide endpoint, username, and password."],
            }

        session = SmartConnectNoSSL(
            host=config.endpoint,
            user=config.username,
            pwd=config.password,
            port=int(config.extra.get("port", 443)),
        )
        try:
            session.RetrieveContent()
            return {
                "success": True,
                "message": "VMware session validated.",
                "debug": ["Retrieved VMware service content successfully."],
                "summary": {
                    "endpoint": config.endpoint,
                    "vm_name": config.vm_name,
                    "type": config.hypervisor_type.value,
                },
            }
        finally:
            Disconnect(session)

    def _connect_virtualbox(self, config: HypervisorConfig) -> dict[str, Any]:
        try:
            import vboxapi  # type: ignore
        except Exception:
            return {
                "success": False,
                "message": "VirtualBox SDK is unavailable.",
                "debug": ["Install the VirtualBox Python bindings that match your host."],
            }

        manager = vboxapi.VirtualBoxManager(None, None)
        virtualbox = manager.getVirtualBox()
        _ = virtualbox.version
        return {
            "success": True,
            "message": "VirtualBox SDK validated.",
            "debug": ["Loaded VirtualBox API bindings successfully."],
            "summary": {
                "endpoint": config.endpoint,
                "vm_name": config.vm_name,
                "type": config.hypervisor_type.value,
            },
        }

    def _connect_utm(self, config: HypervisorConfig) -> dict[str, Any]:
        wrapper = config.extra.get("wrapper_command")
        if not wrapper:
            return {
                "success": False,
                "message": "UTM integration requires a custom wrapper command.",
                "debug": ["Provide extra.wrapper_command with a trusted local helper."],
            }

        command = [wrapper, "--health-check"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return {
            "success": result.returncode == 0,
            "message": "UTM wrapper validated." if result.returncode == 0 else "UTM wrapper reported an error.",
            "debug": [result.stdout.strip(), result.stderr.strip()],
            "summary": {
                "endpoint": config.endpoint,
                "vm_name": config.vm_name,
                "type": config.hypervisor_type.value,
            },
        }

    def bind_bridge_state(
        self,
        hypervisor: HypervisorConfig | None = None,
        ldap: LDAPConfig | None = None,
        status: str = "connected",
        message: str = "",
        debug: list[str] | None = None,
    ) -> BridgeState:
        return BridgeState(
            host=self.host_environment,
            hypervisor=hypervisor,
            ldap=ldap,
            status=status,
            message=message,
            debug=debug or [],
        )


def bridge_state_to_dict(state: BridgeState) -> dict[str, Any]:
    """Serialize bridge state for session storage and API responses."""

    payload = asdict(state)
    ldap = payload.get("ldap")
    if isinstance(ldap, dict) and ldap.get("password"):
        ldap = dict(ldap)
        ldap["password"] = ""
        ldap["password_set"] = True
        payload["ldap"] = ldap

    hypervisor = payload.get("hypervisor")
    if isinstance(hypervisor, dict) and hypervisor.get("password"):
        hypervisor = dict(hypervisor)
        hypervisor["password"] = ""
        hypervisor["password_set"] = True
        payload["hypervisor"] = hypervisor

    return payload
