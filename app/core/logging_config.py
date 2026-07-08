"""Console logging setup for ActiveDecoy."""

from __future__ import annotations

import logging
import sys

from app.core.audit import AUDIT_LOGGER_NAME


def configure_logging(*, debug: bool = False) -> None:
    """Configure root logging once for the application process."""

    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        logging.getLogger(AUDIT_LOGGER_NAME).setLevel(logging.INFO)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy third-party loggers in normal lab runs.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO if debug else logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger(AUDIT_LOGGER_NAME).setLevel(logging.INFO)
