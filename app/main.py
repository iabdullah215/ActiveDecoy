"""ActiveDecoy FastAPI backend."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Annotated, Any

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from app.core.connection_manager import (
    ConnectionManager,
    HypervisorConfig,
    HypervisorType,
    LDAPConfig,
    bridge_state_to_dict,
)
from app.core.deception_engine import DeceptionEngine, deployment_to_dict


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
GUIDE_PATH = PROJECT_ROOT / "data" / "user_guide.md"

TEST_USERNAME = "hawtsauce"
TEST_PASSWORD = "hwatsauce"
LOGIN_PATH = "/login"
HOME_PATH = "/home"

app = FastAPI(title="ActiveDecoy", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key="active-decoy-development-secret")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
connection_manager = ConnectionManager()
deception_engine = DeceptionEngine(seed=42)
logger = logging.getLogger(__name__)


def _navigation() -> list[dict[str, str]]:
    return [
        {"label": "Home", "path": HOME_PATH},
        {"label": "Connection", "path": "/connection"},
        {"label": "Visualization", "path": "/visualization"},
        {"label": "Deception", "path": "/deception"},
        {"label": "Monitoring", "path": "/monitoring"},
        {"label": "User Guide", "path": "/guide"},
    ]


def _current_bridge_state(request: Request) -> dict[str, Any]:
    bridge_state = request.session.get("bridge_state")
    if isinstance(bridge_state, dict):
        return bridge_state
    return bridge_state_to_dict(connection_manager.get_bridge_state())


def _authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def _require_auth(request: Request) -> None:
    if not _authenticated(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": LOGIN_PATH})


def _render(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    payload = {
        "request": request,
        "navigation": _navigation(),
        "bridge_state": _current_bridge_state(request),
        **context,
    }
    return templates.TemplateResponse(request, template_name, payload)


def _normalize_credential(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


@app.get("/", include_in_schema=False)
def index(request: Request) -> RedirectResponse:
    return RedirectResponse(url=HOME_PATH if _authenticated(request) else LOGIN_PATH, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if _authenticated(request):
        return RedirectResponse(url=HOME_PATH, status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, "login.html", title="Login", error=None)


@app.post("/login")
def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    raw_username = username
    raw_password = password
    username = _normalize_credential(username)
    password = _normalize_credential(password)
    if username == TEST_USERNAME and password == TEST_PASSWORD:
        request.session["authenticated"] = True
        request.session["username"] = username
        request.session["bridge_state"] = bridge_state_to_dict(connection_manager.get_bridge_state())
        return RedirectResponse(url=HOME_PATH, status_code=status.HTTP_303_SEE_OTHER)
    logger.warning(
        "Login rejected: username=%r password_length=%d username_length=%d",
        raw_username,
        len(raw_password),
        len(raw_username),
    )
    return _render(request, "login.html", title="Login", error="Invalid testing credentials.")


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url=LOGIN_PATH, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/home", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    _require_auth(request)
    return _render(
        request,
        "home.html",
        title="Home",
        summary={
            "host_os": connection_manager.host_environment.os_name,
            "host_release": connection_manager.host_environment.os_release,
            "mode": connection_manager.detect_connection_mode(),
            "status": request.session.get("bridge_state", {}).get("status", "not_connected"),
        },
    )


@app.get("/connection", response_class=HTMLResponse)
def connection_page(request: Request) -> HTMLResponse:
    _require_auth(request)
    return _render(
        request,
        "connection.html",
        title="Connection",
        host_environment=connection_manager.host_environment,
        hypervisor_types=[item.value for item in HypervisorType],
    )


@app.get("/visualization", response_class=HTMLResponse)
def visualization_page(request: Request) -> HTMLResponse:
    _require_auth(request)
    return _render(
        request,
        "visualization.html",
        title="Visualization",
        neodash_url=request.session.get("neodash_url", "https://neodash.graphapp.io"),
        graph_rows=deception_engine.summarize_graph_rows(deception_engine.generate_honey_users(2)),
    )


@app.get("/deception", response_class=HTMLResponse)
def deception_page(request: Request) -> HTMLResponse:
    _require_auth(request)
    return _render(
        request,
        "deception.html",
        title="Deception",
        default_modules=["honey_users", "honey_servers", "breadcrumbs"],
    )


@app.get("/monitoring", response_class=HTMLResponse)
def monitoring_page(request: Request) -> HTMLResponse:
    _require_auth(request)
    return _render(request, "monitoring.html", title="Monitoring")


@app.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request) -> HTMLResponse:
    _require_auth(request)
    guide_markdown = GUIDE_PATH.read_text(encoding="utf-8") if GUIDE_PATH.exists() else "# User Guide\n\nNo guide content has been added yet."
    return _render(request, "guide.html", title="User Guide", guide_markdown=guide_markdown)


@app.get("/api/health")
def api_health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "authenticated": _authenticated(request),
        "host": bridge_state_to_dict(connection_manager.get_bridge_state())["host"],
    }


@app.get("/api/system-state")
def api_system_state(request: Request) -> dict[str, Any]:
    _require_auth(request)
    return _current_bridge_state(request)


@app.post("/api/connection/test")
def api_connection_test(
    request: Request,
    ldap_host: Annotated[str, Form()],
    ldap_port: Annotated[int, Form()] = 389,
    ldap_use_ssl: Annotated[bool, Form()] = False,
    ldap_bind_dn: Annotated[str, Form()] = "",
    ldap_password: Annotated[str, Form()] = "",
    ldap_base_dn: Annotated[str, Form()] = "",
    hypervisor_type: Annotated[str, Form()] = "vmware",
    hypervisor_endpoint: Annotated[str, Form()] = "",
    hypervisor_username: Annotated[str, Form()] = "",
    hypervisor_password: Annotated[str, Form()] = "",
    hypervisor_vm_name: Annotated[str, Form()] = "",
    wrapper_command: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    _require_auth(request)

    hypervisor = HypervisorConfig(
        hypervisor_type=HypervisorType(hypervisor_type),
        endpoint=hypervisor_endpoint,
        username=hypervisor_username,
        password=hypervisor_password,
        vm_name=hypervisor_vm_name,
        extra={"wrapper_command": wrapper_command} if wrapper_command else {},
    )
    ldap = LDAPConfig(
        host=ldap_host,
        port=ldap_port,
        use_ssl=ldap_use_ssl,
        bind_dn=ldap_bind_dn,
        password=ldap_password,
        base_dn=ldap_base_dn,
    )

    hypervisor_result = connection_manager.connect_hypervisor(hypervisor)
    ldap_result = connection_manager.validate_ldap_connection(ldap)

    bridge_state = connection_manager.bind_bridge_state(
        hypervisor=hypervisor,
        ldap=ldap,
        status="connected" if ldap_result["success"] else "degraded",
        message=ldap_result["message"],
        debug=[*hypervisor_result.get("debug", []), *ldap_result.get("debug", [])],
    )
    request.session["bridge_state"] = bridge_state_to_dict(bridge_state)
    request.session["hypervisor_type"] = hypervisor_type
    request.session["neodash_url"] = request.session.get("neodash_url", "https://neodash.graphapp.io")

    return {
        "bridge_state": bridge_state_to_dict(bridge_state),
        "hypervisor_result": hypervisor_result,
        "ldap_result": ldap_result,
    }


@app.post("/api/deception/deploy")
def api_deception_deploy(request: Request, modules: Annotated[list[str] | None, Form()] = None) -> dict[str, Any]:
    _require_auth(request)
    deployment = deception_engine.build_deployment(modules or [])
    request.session["last_deployment"] = deployment_to_dict(deployment)
    return deployment_to_dict(deployment)


@app.get("/api/monitoring/events")
def api_monitoring_events(request: Request) -> dict[str, Any]:
    _require_auth(request)
    events = [
        {"event_id": 4768, "label": "TGT requested", "severity": "high", "source": "Domain Controller", "state": "active"},
        {"event_id": 4769, "label": "Service ticket requested", "severity": "high", "source": "Domain Controller", "state": "active"},
        {"event_id": 4625, "label": "Failed logon", "severity": "medium", "source": "Security Log", "state": "active"},
    ]
    return {"events": events}


@app.get("/api/graph/preview")
def api_graph_preview(request: Request) -> dict[str, Any]:
    _require_auth(request)
    deployment = request.session.get("last_deployment") or deployment_to_dict(deception_engine.build_deployment(["honey_users", "breadcrumbs"]))
    return {
        "nodes": deployment.get("objects", []),
        "cypher_queries": deployment.get("cypher_queries", []),
    }


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
