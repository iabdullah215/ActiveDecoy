"""Application configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass(frozen=True)
class Settings:
    session_secret: str
    app_username: str
    app_password: str
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str
    neodash_url: str
    host: str
    port: int
    debug: bool

    @property
    def neo4j_configured(self) -> bool:
        return bool(self.neo4j_uri and self.neo4j_password)


def get_settings() -> Settings:
    return Settings(
        session_secret=_env("SESSION_SECRET", "active-decoy-development-secret"),
        app_username=_env("APP_USERNAME", "hawtsauce"),
        app_password=_env("APP_PASSWORD", "hwatsauce"),
        neo4j_uri=_env("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_username=_env("NEO4J_USERNAME", "neo4j"),
        neo4j_password=_env("NEO4J_PASSWORD", ""),
        neo4j_database=_env("NEO4J_DATABASE", "neo4j"),
        neodash_url=_env("NEODASH_URL", "https://neodash.graphapp.io"),
        host=_env("APP_HOST", "127.0.0.1"),
        port=int(_env("APP_PORT", "8000")),
        debug=_env("APP_DEBUG", "false").lower() in {"1", "true", "yes"},
    )
