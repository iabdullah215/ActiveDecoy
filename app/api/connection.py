"""Connection profile and bridge validation API routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request

from app.core.audit import audit_event
from app.core.config import Settings
from app.core.connection_manager import ConnectionManager, bridge_state_to_dict
from app.core.connection_profile import (
    ConnectionProfile,
    load_session_profile,
    redact_bridge_state,
    save_session_profile,
)
from app.core.connection_service import run_connection_test
from app.core.directory_service import run_directory_import
from app.core.graph_store import GraphStore


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
    graph_store: GraphStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/connection", tags=["connection"])

    def _actor(request: Request) -> str:
        return str(request.session.get("username") or "anonymous")

    @router.get("/profile")
    def connection_profile(request: Request) -> dict[str, Any]:
        require_auth(request)
        profile = load_session_profile(request.session, settings)
        checklist = request.session.get("connection_checklist", {})
        bridge_state = request.session.get(
            "bridge_state",
            bridge_state_to_dict(manager.get_bridge_state()),
        )
        return {
            "profile": profile.to_form_dict(),
            "checklist": checklist,
            "bridge_state": redact_bridge_state(bridge_state)
            if isinstance(bridge_state, dict)
            else bridge_state,
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
        audit_event(
            "connection.save",
            actor=_actor(request),
            outcome="success",
            request=request,
            ldap_host=profile.ldap_host,
            hypervisor_type=profile.hypervisor_type,
        )
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
        # Never keep raw passwords in session-serialized bridge state.
        result["bridge_state"] = redact_bridge_state(result["bridge_state"])
        request.session["bridge_state"] = result["bridge_state"]
        request.session["connection_checklist"] = result["checklist"]
        request.session["hypervisor_type"] = profile.hypervisor_type
        request.session["neodash_url"] = settings.neodash_url
        save_session_profile(request.session, profile)
        audit_event(
            "connection.test",
            actor=_actor(request),
            outcome="success" if result["checklist"]["bridge"]["status"] in {"connected", "degraded"} else "failure",
            request=request,
            bridge_status=result["checklist"]["bridge"]["status"],
            ldap_host=profile.ldap_host,
        )
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
        directory_summary = request.session.get("directory_summary", {})
        return {
            "bridge_state": bridge_state,
            "checklist": request.session.get("connection_checklist", {}),
            "profile_configured": load_session_profile(request.session, settings).ldap_configured(),
            "directory_summary": directory_summary,
        }

    @router.post("/enumerate")
    def connection_enumerate(
        request: Request,
        sync_to_graph: Annotated[str, Form()] = "true",
        replace: Annotated[str, Form()] = "true",
    ) -> dict[str, Any]:
        require_auth(request)
        if graph_store is None:
            return {"success": False, "message": "Graph store is unavailable."}

        profile = load_session_profile(request.session, settings)
        if not profile.ldap_configured():
            return {
                "success": False,
                "message": "Save and validate an LDAP host before importing the directory.",
            }

        try:
            result = run_directory_import(
                profile.to_ldap_config(),
                settings,
                graph_store,
                sync_to_graph=_parse_bool(sync_to_graph),
                replace=_parse_bool(replace),
            )
        except Exception as exc:
            audit_event(
                "directory.enumerate",
                actor=_actor(request),
                outcome="failure",
                request=request,
                error=str(exc),
            )
            return {"success": False, "message": str(exc), "summary": {}}

        # Keep a compact summary + preview in session; full snapshot can be large.
        summary = result.get("summary") or {}
        request.session["directory_summary"] = summary
        preview_users = (result.get("snapshot") or {}).get("users", [])[:25]
        preview_groups = (result.get("snapshot") or {}).get("groups", [])[:25]
        preview_computers = (result.get("snapshot") or {}).get("computers", [])[:25]
        request.session["directory_preview"] = {
            "users": preview_users,
            "groups": preview_groups,
            "computers": preview_computers,
            "trusts": (result.get("snapshot") or {}).get("trusts", [])[:25],
        }

        audit_event(
            "directory.enumerate",
            actor=_actor(request),
            outcome="success" if result.get("success") else "failure",
            request=request,
            synced=bool(result.get("synced")),
            users=summary.get("users", 0),
            groups=summary.get("groups", 0),
            computers=summary.get("computers", 0),
            trusts=summary.get("trusts", 0),
        )

        # Do not return the full snapshot over the wire by default — keep UI payload light.
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "summary": summary,
            "synced": result.get("synced", False),
            "graph_sync": result.get("graph_sync"),
            "preview": request.session["directory_preview"],
            "debug": (result.get("snapshot") or {}).get("debug", []),
        }

    return router
