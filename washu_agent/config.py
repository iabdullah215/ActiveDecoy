"""Configuration for the Washu Agent forwarder."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_bool(key: str, default: str = "false") -> bool:
    return _env(key, default).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentConfig:
    console_url: str
    ingest_token: str
    agent_id: str
    hostname: str
    vm_name: str
    heartbeat_interval: int
    poll_interval: int
    event_source: str
    event_log_path: str
    honey_targets: tuple[str, ...]
    dry_run: bool

    @property
    def base_url(self) -> str:
        return self.console_url.rstrip("/")


def load_agent_config(env_file: Path | None = None) -> AgentConfig:
    """Load agent settings from environment (optional dotenv file)."""

    if env_file and env_file.exists():
        load_dotenv(env_file)
    else:
        # Prefer washu_agent/.env, then project root .env
        here = Path(__file__).resolve().parent
        for candidate in (here / ".env", here.parent / ".env"):
            if candidate.exists():
                load_dotenv(candidate)
                break

    honey_raw = _env("WASHU_HONEY_TARGETS", "")
    honey = tuple(part.strip() for part in honey_raw.split(",") if part.strip())

    import socket

    return AgentConfig(
        console_url=_env("WASHU_CONSOLE_URL", "http://127.0.0.1:8000"),
        ingest_token=_env("WASHU_INGEST_TOKEN") or _env("AGENT_INGEST_TOKEN", ""),
        agent_id=_env("WASHU_AGENT_ID", "washu-agent"),
        hostname=_env("WASHU_HOSTNAME") or socket.gethostname(),
        vm_name=_env("WASHU_VM_NAME") or _env("HYPERVISOR_VM_NAME", "Washu-DC"),
        heartbeat_interval=max(5, int(_env("WASHU_HEARTBEAT_INTERVAL", "30"))),
        poll_interval=max(1, int(_env("WASHU_POLL_INTERVAL", "10"))),
        event_source=_env("WASHU_EVENT_SOURCE", "auto").lower(),
        event_log_path=_env("WASHU_EVENT_LOG_PATH", ""),
        honey_targets=honey,
        dry_run=_env_bool("WASHU_DRY_RUN", "false"),
    )
