"""Orchestrates connection tests, retries, and bridge status updates."""

from __future__ import annotations

import time
from typing import Any

from app.core.connection_manager import ConnectionManager, bridge_state_to_dict
from app.core.connection_profile import ConnectionProfile


def compute_bridge_status(
    ldap_success: bool,
    hypervisor_success: bool,
    hypervisor_configured: bool,
    ldap_configured: bool,
) -> str:
    if not ldap_configured:
        return "not_connected"
    if not ldap_success:
        return "failed"
    if hypervisor_configured and not hypervisor_success:
        return "degraded"
    return "connected"


def build_checklist(
    ldap_result: dict[str, Any],
    hypervisor_result: dict[str, Any],
    profile: ConnectionProfile,
) -> dict[str, Any]:
    hypervisor_configured = profile.hypervisor_configured()
    ldap_configured = profile.ldap_configured()

    if not ldap_configured:
        ldap_status = "pending"
    elif ldap_result.get("success"):
        ldap_status = "ok"
    else:
        ldap_status = "error"

    if not hypervisor_configured:
        hypervisor_status = "skipped"
    elif hypervisor_result.get("success"):
        hypervisor_status = "ok"
    else:
        hypervisor_status = "error"

    bridge_status = compute_bridge_status(
        ldap_result.get("success", False),
        hypervisor_result.get("success", False),
        hypervisor_configured,
        ldap_configured,
    )

    return {
        "ldap": {
            "status": ldap_status,
            "message": ldap_result.get("message", ""),
            "configured": ldap_configured,
        },
        "hypervisor": {
            "status": hypervisor_status,
            "message": hypervisor_result.get("message", ""),
            "configured": hypervisor_configured,
        },
        "bridge": {
            "status": bridge_status,
            "message": ldap_result.get("message", ""),
        },
    }


def run_connection_test(
    manager: ConnectionManager,
    profile: ConnectionProfile,
    *,
    retries: int = 3,
    retry_delay: float = 0.5,
) -> dict[str, Any]:
    """Validate LDAP (with retries) and hypervisor, returning a structured report."""

    profile.touch_tested()
    ldap = profile.to_ldap_config()
    hypervisor = profile.to_hypervisor_config()

    hypervisor_result: dict[str, Any]
    if profile.hypervisor_configured():
        hypervisor_result = manager.connect_hypervisor(hypervisor)
    else:
        hypervisor_result = {
            "success": True,
            "message": "Hypervisor checks skipped (not configured).",
            "debug": ["Provide VMware endpoint or UTM wrapper to enable hypervisor validation."],
            "skipped": True,
        }

    ldap_result: dict[str, Any] = {
        "success": False,
        "message": "LDAP host is required.",
        "debug": ["Set LDAP Host before running a connection test."],
    }
    if profile.ldap_configured():
        ldap_result = manager.validate_ldap_connection_with_retry(
            ldap,
            retries=max(1, retries),
            retry_delay=retry_delay,
        )

    checklist = build_checklist(ldap_result, hypervisor_result, profile)
    bridge_status = checklist["bridge"]["status"]
    message = ldap_result.get("message") or hypervisor_result.get("message", "")

    bridge_state = manager.bind_bridge_state(
        hypervisor=hypervisor if profile.hypervisor_configured() else None,
        ldap=ldap if profile.ldap_configured() else None,
        status=bridge_status,
        message=message,
        debug=[*hypervisor_result.get("debug", []), *ldap_result.get("debug", [])],
    )

    return {
        "bridge_state": bridge_state_to_dict(bridge_state),
        "hypervisor_result": hypervisor_result,
        "ldap_result": ldap_result,
        "checklist": checklist,
        "profile": profile.to_public_dict(),
        "retries": retries,
    }
