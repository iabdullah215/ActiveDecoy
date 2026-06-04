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

from app.api.connection import build_connection_router
from app.api.graph import build_graph_router
from app.core.config import get_settings
from app.core.connection_manager import (
    ConnectionManager,
    HypervisorType,
    bridge_state_to_dict,
)
from app.core.connection_profile import (
    ConnectionProfile,
    load_session_profile,
    redact_bridge_state,
    save_session_profile,
)
from app.core.deception_engine import DeceptionEngine, deployment_to_dict
from app.core.graph_store import GraphStore


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
GUIDE_PATH = PROJECT_ROOT / "data" / "user_guide.md"
SAMPLE_GRAPH_PATH = PROJECT_ROOT / "data" / "sample_graph.cypher"

settings = get_settings()
LOGIN_PATH = "/login"
HOME_PATH = "/home"

app = FastAPI(title="ActiveDecoy", version="0.3.0")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
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
graph_store = GraphStore(settings)
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
        return redact_bridge_state(bridge_state)
    return bridge_state_to_dict(connection_manager.get_bridge_state())


def _directory_ready(request: Request) -> bool:
    checklist = request.session.get("connection_checklist", {})
    if isinstance(checklist, dict):
        ldap = checklist.get("ldap", {})
        if isinstance(ldap, dict) and ldap.get("status") == "ok":
            return True
    bridge_status = request.session.get("bridge_state", {}).get("status", "not_connected")
    return bridge_status in {"connected", "degraded"}


def _authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def _require_auth_page(request: Request) -> None:
    if not _authenticated(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": LOGIN_PATH})


def _require_auth_api(request: Request) -> None:
    if not _authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )


def _render(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    payload = {
        "request": request,
        "navigation": _navigation(),
        "bridge_state": _current_bridge_state(request),
        "active_path": request.url.path,
        "connection_checklist": request.session.get("connection_checklist", {}),
        **context,
    }
    return templates.TemplateResponse(request, template_name, payload)


def _normalize_credential(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _health_label(ready: bool, configured: bool = True) -> str:
    if not configured:
        return "Not configured"
    return "Ready" if ready else "Unavailable"


def _graph_rows_for_visualization() -> list[dict[str, Any]]:
    health = graph_store.health()
    if health.connected:
        try:
            nodes = graph_store.fetch_honey_nodes()
            if nodes:
                return nodes
        except Exception:
            pass
    return deception_engine.summarize_graph_rows(deception_engine.generate_honey_users(2))


@app.on_event("shutdown")
def shutdown_graph_store() -> None:
    graph_store.close()


app.include_router(build_graph_router(graph_store, deception_engine, _require_auth_api))
app.include_router(build_connection_router(connection_manager, settings, _require_auth_api))


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
    if username == settings.app_username and password == settings.app_password:
        request.session["authenticated"] = True
        request.session["username"] = username
        request.session["bridge_state"] = bridge_state_to_dict(connection_manager.get_bridge_state())
        if not request.session.get("connection_profile"):
            save_session_profile(request.session, ConnectionProfile.from_settings(settings))
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
    _require_auth_page(request)
    graph_health = graph_store.health()
    bridge_status = request.session.get("bridge_state", {}).get("status", "not_connected")
    profile = load_session_profile(request.session, settings)
    return _render(
        request,
        "home.html",
        title="Home",
        summary={
            "host_os": connection_manager.host_environment.os_name,
            "host_release": connection_manager.host_environment.os_release,
            "mode": connection_manager.detect_connection_mode(),
            "status": bridge_status,
            "ldap_host": profile.ldap_host or "Not set",
        },
        health={
            "directory": _health_label(_directory_ready(request), bool(profile.ldap_host)),
            "graph": _health_label(graph_health.connected, graph_health.configured),
            "deception": "Ready",
            "graph_nodes": graph_health.node_count,
        },
    )


@app.get("/connection", response_class=HTMLResponse)
def connection_page(request: Request) -> HTMLResponse:
    _require_auth_page(request)
    profile = load_session_profile(request.session, settings)
    return _render(
        request,
        "connection.html",
        title="Connection",
        host_environment=connection_manager.host_environment,
        hypervisor_types=[item.value for item in HypervisorType],
        connection_profile=profile.to_form_dict(),
        connection_retries=settings.connection_retries,
    )


@app.get("/visualization", response_class=HTMLResponse)
def visualization_page(request: Request) -> HTMLResponse:
    _require_auth_page(request)
    graph_health = graph_store.health()
    return _render(
        request,
        "visualization.html",
        title="Visualization",
        neodash_url=request.session.get("neodash_url", settings.neodash_url),
        graph_rows=_graph_rows_for_visualization(),
        graph_source="neo4j" if graph_health.connected else "preview",
    )


@app.get("/deception", response_class=HTMLResponse)
def deception_page(request: Request) -> HTMLResponse:
    _require_auth_page(request)
    graph_health = graph_store.health()
    return _render(
        request,
        "deception.html",
        title="Deception",
        default_modules=["honey_users", "honey_servers", "breadcrumbs"],
        graph_connected=graph_health.connected,
    )


@app.get("/monitoring", response_class=HTMLResponse)
def monitoring_page(request: Request) -> HTMLResponse:
    _require_auth_page(request)
    return _render(request, "monitoring.html", title="Monitoring")


@app.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request) -> HTMLResponse:
    _require_auth_page(request)
    guide_markdown = GUIDE_PATH.read_text(encoding="utf-8") if GUIDE_PATH.exists() else "# User Guide\n\nNo guide content has been added yet."
    return _render(request, "guide.html", title="User Guide", guide_markdown=guide_markdown)


@app.get("/api/health")
def api_health(request: Request) -> dict[str, Any]:
    graph_health = graph_store.health()
    return {
        "status": "ok",
        "authenticated": _authenticated(request),
        "host": bridge_state_to_dict(connection_manager.get_bridge_state())["host"],
        "graph": {
            "configured": graph_health.configured,
            "connected": graph_health.connected,
            "node_count": graph_health.node_count,
        },
    }


@app.get("/api/system-state")
def api_system_state(request: Request) -> dict[str, Any]:
    _require_auth_api(request)
    return _current_bridge_state(request)


@app.post("/api/deception/deploy")
def api_deception_deploy(
    request: Request,
    modules: Annotated[list[str] | None, Form()] = None,
    sync_to_graph: Annotated[str, Form()] = "false",
) -> dict[str, Any]:
    _require_auth_api(request)
    deployment = deception_engine.build_deployment(modules or [])
    payload = deployment_to_dict(deployment)
    request.session["last_deployment"] = payload

    if str(sync_to_graph).lower() in {"1", "true", "yes", "on"}:
        graph_result = graph_store.execute_queries(payload.get("cypher_queries", []))
        payload["graph_sync"] = graph_result
        if graph_result["success"]:
            payload["graph_node_count"] = graph_store.health().node_count

    return payload


@app.get("/api/monitoring/events")
def api_monitoring_events(request: Request) -> dict[str, Any]:
    _require_auth_api(request)
    events = [
        {"event_id": 4768, "label": "TGT requested", "severity": "high", "source": "Domain Controller", "state": "active"},
        {"event_id": 4769, "label": "Service ticket requested", "severity": "high", "source": "Domain Controller", "state": "active"},
        {"event_id": 4625, "label": "Failed logon", "severity": "medium", "source": "Security Log", "state": "active"},
    ]
    return {"events": events}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
