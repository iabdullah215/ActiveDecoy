"""Washu Agent service loop: heartbeat + event forward."""

from __future__ import annotations

import logging
import signal
import time
from typing import Any

from washu_agent.client import ConsoleClient
from washu_agent.collectors import build_collectors, collect_events
from washu_agent.config import AgentConfig

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.client = ConsoleClient(config)
        self.collectors = build_collectors(
            event_source=config.event_source,
            event_log_path=config.event_log_path,
            honey_targets=config.honey_targets,
            agent_id=config.agent_id,
        )
        self.events_forwarded = 0
        self._stop = False
        self._last_heartbeat = 0.0
        self._last_status = "ok"

    def request_stop(self, *_args: Any) -> None:
        self._stop = True

    def run_once(self) -> dict[str, Any]:
        """Single poll + optional heartbeat (useful for tests)."""

        events = collect_events(self.collectors)
        ingest_result: dict[str, Any] = {"accepted": 0}
        if events:
            ingest_result = self.client.ingest(events)
            accepted = int(ingest_result.get("accepted") or 0)
            self.events_forwarded += accepted
            logger.info("Forwarded %s event(s) (accepted=%s)", len(events), accepted)
        heartbeat = self.client.heartbeat(
            status=self._last_status,
            events_forwarded=self.events_forwarded,
            capability=[type(c).__name__ for c in self.collectors],
            meta={"collectors": [type(c).__name__ for c in self.collectors]},
        )
        self._last_heartbeat = time.monotonic()
        return {"ingest": ingest_result, "heartbeat": heartbeat, "events": len(events)}

    def run(self) -> int:
        if not self.config.ingest_token and not self.config.dry_run:
            logger.error("WASHU_INGEST_TOKEN / AGENT_INGEST_TOKEN is required")
            return 1

        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        logger.info(
            "Washu Agent starting id=%s console=%s source=%s collectors=%s dry_run=%s",
            self.config.agent_id,
            self.config.base_url,
            self.config.event_source,
            [type(c).__name__ for c in self.collectors],
            self.config.dry_run,
        )

        # Immediate heartbeat so the console shows healthy before first poll cycle.
        try:
            self.client.heartbeat(
                status="ok",
                events_forwarded=self.events_forwarded,
                capability=[type(c).__name__ for c in self.collectors],
            )
            self._last_heartbeat = time.monotonic()
            self._last_status = "ok"
        except Exception as exc:
            logger.warning("Initial heartbeat failed: %s", exc)
            self._last_status = "error"

        while not self._stop:
            try:
                events = collect_events(self.collectors)
                if events:
                    result = self.client.ingest(events)
                    accepted = int(result.get("accepted") or 0)
                    self.events_forwarded += accepted
                    logger.info("Forwarded %s event(s) accepted=%s", len(events), accepted)
                self._last_status = "ok"
            except Exception as exc:
                self._last_status = "error"
                logger.exception("Forward cycle failed: %s", exc)

            now = time.monotonic()
            if now - self._last_heartbeat >= self.config.heartbeat_interval:
                try:
                    self.client.heartbeat(
                        status=self._last_status,
                        events_forwarded=self.events_forwarded,
                        capability=[type(c).__name__ for c in self.collectors],
                    )
                    self._last_heartbeat = now
                except Exception as exc:
                    logger.warning("Heartbeat failed: %s", exc)
                    self._last_status = "error"

            time.sleep(self.config.poll_interval)

        logger.info("Washu Agent stopped; forwarded_total=%s", self.events_forwarded)
        return 0
