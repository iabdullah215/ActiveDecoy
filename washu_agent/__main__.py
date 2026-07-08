#!/usr/bin/env python3
"""CLI entrypoint for the Washu Agent.

Examples:
  python -m washu_agent once --dry-run
  python -m washu_agent run --source demo
  python -m washu_agent heartbeat
  python -m washu_agent check
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from washu_agent.client import ConsoleClient
from washu_agent.config import load_agent_config
from washu_agent.service import AgentService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Washu Agent — ActiveDecoy lab forwarder")
    parser.add_argument("--env-file", type=Path, default=None, help="Optional dotenv path")
    parser.add_argument("--console-url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--vm-name", default=None)
    parser.add_argument("--source", choices=["auto", "winlog", "file", "demo"], default=None)
    parser.add_argument("--event-log", default=None, help="NDJSON path for file source")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Probe console reachability")
    sub.add_parser("heartbeat", help="Send a single heartbeat")
    once = sub.add_parser("once", help="One collect + ingest + heartbeat cycle")
    once.add_argument("--honey-target", action="append", default=None)
    run = sub.add_parser("run", help="Run continuous forwarder loop")
    run.add_argument("--honey-target", action="append", default=None)
    return parser


def _apply_overrides(args: argparse.Namespace) -> None:
    import os

    if args.console_url:
        os.environ["WASHU_CONSOLE_URL"] = args.console_url
    if args.token:
        os.environ["WASHU_INGEST_TOKEN"] = args.token
    if args.agent_id:
        os.environ["WASHU_AGENT_ID"] = args.agent_id
    if args.vm_name:
        os.environ["WASHU_VM_NAME"] = args.vm_name
    if args.source:
        os.environ["WASHU_EVENT_SOURCE"] = args.source
    if args.event_log:
        os.environ["WASHU_EVENT_LOG_PATH"] = args.event_log
    if args.dry_run:
        os.environ["WASHU_DRY_RUN"] = "true"
    honey = getattr(args, "honey_target", None)
    if honey:
        os.environ["WASHU_HONEY_TARGETS"] = ",".join(honey)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [washu] %(message)s",
    )
    _apply_overrides(args)
    config = load_agent_config(args.env_file)

    if args.command == "check":
        result = ConsoleClient(config).health_check()
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if args.command == "heartbeat":
        if not config.ingest_token and not config.dry_run:
            print("Set WASHU_INGEST_TOKEN or AGENT_INGEST_TOKEN", file=sys.stderr)
            return 1
        result = ConsoleClient(config).heartbeat()
        print(json.dumps(result, indent=2))
        return 0

    service = AgentService(config)
    if args.command == "once":
        if not config.ingest_token and not config.dry_run:
            print("Set WASHU_INGEST_TOKEN or AGENT_INGEST_TOKEN", file=sys.stderr)
            return 1
        result = service.run_once()
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "run":
        return service.run()

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
