"""Connection profile and bridge validation API routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request

from app.core.config import Settings
from app.core.connection_manager import ConnectionManager, bridge_state_to_dict
from app.core.connection_profile import (
    ConnectionProfile,
    load_session_profile,
    save_session_profile,
)
from app.core.connection_service import run_connection_test


def _parse_bool(value: str | bool | None) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _profile_from_form(
    *,
    ldap_host: str,
    ldap_port: int,
    ldap_use_ssl: bool,
    ldap_bind_dn: str,
    ldap_password: str,
    ldap_base_dn: str,
    hypervisor_type: str,
    hypervisor_endpoint: str,
    hypervisor_username: str,
    hypervisor_password: str,
    hypervisor_vm_name: str,
    wrapper_command: str,
    auto_test_on_load: bool,
) -> ConnectionProfile:
    return ConnectionProfile(
        ldap_host=ldap_host.strip(),
        ldap_port=ldap_port,
        ldap_use_ssl=ldap_use_ssl,
        ldap_bind_dn=ldap_bind_dn.strip(),
        ldap_password=ldap_password,
        ldap_base_dn=ldap_base_dn.strip(),
        hypervisor_type=hypervisor_type.strip().lower(),
        hypervisor_endpoint=hypervisor_endpoint.strip(),
        hypervisor_username=hypervisor_username.strip(),
        hypervisor_password=hypervisor_password,
        hypervisor_vm_name=hypervisor_vm_name.strip(),
        wrapper_command=wrapper_command.strip(),
        auto_test_on_load=auto_test_on_load,
    )


def build_connection_router(
    manager: ConnectionManager,
    settings: Settings,
    require_auth,
) -> APIRouter:
    router = APIRouter(prefix="/api/connection", tags=["connection"])

    @router.get("/profile")
    def connection_profile(request: Request) -> dict[str, Any]:
        require_auth(request)
        profile = load_session_profile(request.session, settings)
        checklist = request.session.get("connection_checklist", {})
        return {
            "profile": profile.to_form_dict(),
            "checklist": checklist,
            "bridge_state": request.session.get("bridge_state", bridge_state_to_dict(manager.get_bridge_state())),
        }

    @router.post("/save")
    def connection_save(
        request: Request,
        ldap_host: Annotated[str, Form()] = "",
        ldap_port: Annotated[int, Form()] = 389,
        ldap_use_ssl: Annotated[str, Form()] = "false",
        ldap_bind_dn: Annotated[str, Form()] = "",
        ldap_password: Annotated[str, Form()] = "",
        ldap_base_dn: Annotated[str, Form()] = "",
        hypervisor_type: Annotated[str, Form()] = "vmware",
        hypervisor_endpoint: Annotated[str, Form()] = "",
        hypervisor_username: Annotated[str, Form()] = "",
        hypervisor_password: Annotated[str, Form()] = "",
        hypervisor_vm_name: Annotated[str, Form()] = "",
        wrapper_command: Annotated[str, Form()] = "",
        auto_test_on_load: Annotated[str, Form()] = "true",
    ) -> dict[str, Any]:
        require_auth(request)
        stored = load_session_profile(request.session, settings)
        profile = _profile_from_form(
            ldap_host=ldap_host,
            ldap_port=ldap_port,
            ldap_use_ssl=_parse_bool(ldap_use_ssl),
            ldap_bind_dn=ldap_bind_dn,
            ldap_password=ldap_password,
            ldap_base_dn=ldap_base_dn,
            hypervisor_type=hypervisor_type,
            hypervisor_endpoint=hypervisor_endpoint,
            hypervisor_username=hypervisor_username,
            hypervisor_password=hypervisor_password,
            hypervisor_vm_name=hypervisor_vm_name,
            wrapper_command=wrapper_command,
            auto_test_on_load=_parse_bool(auto_test_on_load),
        ).merge_secrets(stored)
        save_session_profile(request.session, profile)
        return {"success": True, "profile": profile.to_public_dict()}

    def _execute_test(request: Request, profile: ConnectionProfile) -> dict[str, Any]:
        stored = load_session_profile(request.session, settings)
        profile = profile.merge_secrets(stored)
        save_session_profile(request.session, profile)

        result = run_connection_test(
            manager,
            profile,
            retries=settings.connection_retries,
            retry_delay=settings.connection_retry_delay,
        )
        request.session["bridge_state"] = result["bridge_state"]
        request.session["connection_checklist"] = result["checklist"]
        request.session["hypervisor_type"] = profile.hypervisor_type
        request.session["neodash_url"] = settings.neodash_url
        save_session_profile(request.session, profile)
        return result

    @router.post("/test")
    def connection_test(
        request: Request,
        ldap_host: Annotated[str, Form()],
        ldap_port: Annotated[int, Form()] = 389,
        ldap_use_ssl: Annotated[str, Form()] = "false",
        ldap_bind_dn: Annotated[str, Form()] = "",
        ldap_password: Annotated[str, Form()] = "",
        ldap_base_dn: Annotated[str, Form()] = "",
        hypervisor_type: Annotated[str, Form()] = "vmware",
        hypervisor_endpoint: Annotated[str, Form()] = "",
        hypervisor_username: Annotated[str, Form()] = "",
        hypervisor_password: Annotated[str, Form()] = "",
        hypervisor_vm_name: Annotated[str, Form()] = "",
        wrapper_command: Annotated[str, Form()] = "",
        auto_test_on_load: Annotated[str, Form()] = "true",
    ) -> dict[str, Any]:
        require_auth(request)
        profile = _profile_from_form(
            ldap_host=ldap_host,
            ldap_port=ldap_port,
            ldap_use_ssl=_parse_bool(ldap_use_ssl),
            ldap_bind_dn=ldap_bind_dn,
            ldap_password=ldap_password,
            ldap_base_dn=ldap_base_dn,
            hypervisor_type=hypervisor_type,
            hypervisor_endpoint=hypervisor_endpoint,
            hypervisor_username=hypervisor_username,
            hypervisor_password=hypervisor_password,
            hypervisor_vm_name=hypervisor_vm_name,
            wrapper_command=wrapper_command,
            auto_test_on_load=_parse_bool(auto_test_on_load),
        )
        return _execute_test(request, profile)

    @router.post("/retest")
    def connection_retest(request: Request) -> dict[str, Any]:
        require_auth(request)
        profile = load_session_profile(request.session, settings)
        if not profile.ldap_configured():
            return {
                "success": False,
                "message": "No saved LDAP host. Save or test a profile first.",
                "checklist": request.session.get("connection_checklist", {}),
            }
        result = _execute_test(request, profile)
        result["success"] = result["checklist"]["bridge"]["status"] in {"connected", "degraded"}
        return result

    @router.post("/disconnect")
    def connection_disconnect(request: Request) -> dict[str, Any]:
        require_auth(request)
        request.session["bridge_state"] = bridge_state_to_dict(manager.get_bridge_state())
        request.session["connection_checklist"] = {}
        return {
            "success": True,
            "bridge_state": request.session["bridge_state"],
            "message": "Bridge session cleared. Saved profile retained.",
        }

    @router.get("/status")
    def connection_status(request: Request) -> dict[str, Any]:
        require_auth(request)
        bridge_state = request.session.get("bridge_state", bridge_state_to_dict(manager.get_bridge_state()))
        return {
            "bridge_state": bridge_state,
            "checklist": request.session.get("connection_checklist", {}),
            "profile_configured": load_session_profile(request.session, settings).ldap_configured(),
        }

    return router
