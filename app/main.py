"""ActiveDecoy FastAPI backend.

Administrator credentials are loaded from .env via app.core.config (ADMIN_USERNAME, ADMIN_PASSWORD).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import re
from typing import Annotated, Any, AsyncIterator

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from app.api.connection import build_connection_router
from app.api.graph import build_graph_router
from app.api.monitoring import build_monitoring_router
from app.core.audit import audit_event, client_ip
from app.core.config import enforce_startup_guards, get_settings, log_settings_summary
from app.core.connection_manager import (
    ConnectionManager,
    HypervisorType,
    bridge_state_to_dict,
)
from app.core.connection_profile import (
    ConnectionProfile,
    clear_session_secrets,
    load_session_profile,
    redact_bridge_state,
    save_session_profile,
)
from app.core.deception_engine import DeceptionEngine, deployment_to_dict
from app.core.graph_store import GraphStore
from app.core.logging_config import configure_logging
from app.core.monitoring_engine import MonitoringEngine
from app.core.rate_limit import SlidingWindowRateLimiter


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
GUIDE_PATH = PROJECT_ROOT / "data" / "user_guide.md"
SAMPLE_GRAPH_PATH = PROJECT_ROOT / "data" / "sample_graph.cypher"

settings = get_settings()
configure_logging(debug=settings.debug)
LOGIN_PATH = "/login"
HOME_PATH = "/home"

logger = logging.getLogger(__name__)
connection_manager = ConnectionManager()
deception_engine = DeceptionEngine(seed=42)
graph_store = GraphStore(settings)
monitoring_engine = MonitoringEngine(seed=42)
login_rate_limiter = SlidingWindowRateLimiter(
    max_attempts=settings.login_rate_limit,
    window_seconds=settings.login_rate_window_seconds,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    enforce_startup_guards(settings)
    log_settings_summary(settings)
    graph_health = graph_store.health()
    if graph_health.connected:
        logger.info("Neo4j connected (%s honey nodes).", graph_health.node_count)
    elif graph_health.configured:
        logger.warning("Neo4j configured but unreachable: %s", graph_health.message)
    else:
        logger.info("Neo4j not configured; deception can still plan in preview mode.")
    yield
    graph_store.close()
    logger.info("ActiveDecoy shutdown complete.")


app = FastAPI(title="ActiveDecoy", version="0.4.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


app.include_router(build_graph_router(graph_store, deception_engine, _require_auth_api))
app.include_router(build_connection_router(connection_manager, settings, _require_auth_api))
app.include_router(build_monitoring_router(monitoring_engine, _require_auth_api))


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
    ip = client_ip(request)

    limit = login_rate_limiter.check(ip)
    if not limit.allowed:
        audit_event(
            "login",
            actor=username or "anonymous",
            outcome="rate_limited",
            request=request,
            retry_after=limit.retry_after,
        )
        response = _render(
            request,
            "login.html",
            title="Login",
            error=f"Too many login attempts. Try again in {limit.retry_after}s.",
        )
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        response.headers["Retry-After"] = str(limit.retry_after)
        return response

    login_rate_limiter.hit(ip)

    if username == settings.admin_username and password == settings.admin_password:
        login_rate_limiter.reset(ip)
        request.session["authenticated"] = True
        request.session["username"] = username
        request.session["bridge_state"] = bridge_state_to_dict(connection_manager.get_bridge_state())
        if not request.session.get("connection_profile"):
            save_session_profile(request.session, ConnectionProfile.from_settings(settings))
        audit_event("login", actor=username, outcome="success", request=request)
        return RedirectResponse(url=HOME_PATH, status_code=status.HTTP_303_SEE_OTHER)

    audit_event(
        "login",
        actor=username or "anonymous",
        outcome="failure",
        request=request,
        username_length=len(raw_username),
        password_length=len(raw_password),
    )
    logger.warning(
        "Login rejected: username=%r password_length=%d username_length=%d",
        raw_username,
        len(raw_password),
        len(raw_username),
    )
    return _render(request, "login.html", title="Login", error="Invalid credentials.")


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    actor = str(request.session.get("username") or "anonymous")
    clear_session_secrets(request.session)
    request.session.clear()
    audit_event("logout", actor=actor, outcome="success", request=request)
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
    return _render(
        request,
        "monitoring.html",
        title="Monitoring",
        monitoring_stats=monitoring_engine.stats(),
        severities=["critical", "high", "medium", "info"],
    )


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
    selected = modules or []
    deployment = deception_engine.build_deployment(selected)
    payload = deployment_to_dict(deployment)
    request.session["last_deployment"] = payload
    payload["monitored_objects"] = monitoring_engine.register_deployment(payload["objects"])

    sync_enabled = str(sync_to_graph).lower() in {"1", "true", "yes", "on"}
    if sync_enabled:
        graph_result = graph_store.execute_queries(payload.get("cypher_queries", []))
        payload["graph_sync"] = graph_result
        if graph_result["success"]:
            payload["graph_node_count"] = graph_store.health().node_count

    actor = str(request.session.get("username") or "anonymous")
    audit_event(
        "deception.deploy",
        actor=actor,
        outcome="success",
        request=request,
        modules=selected,
        object_count=len(payload.get("objects", [])),
        sync_to_graph=sync_enabled,
        graph_sync_ok=(payload.get("graph_sync") or {}).get("success") if sync_enabled else None,
    )
    return payload


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
