#!/usr/bin/env python3
"""Forward sample Windows security events to ActiveDecoy ingest API.

Usage:
  export AGENT_INGEST_TOKEN=your-token
  python scripts/forward_sample_events.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser(description="POST sample telemetry to ActiveDecoy")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("AGENT_INGEST_TOKEN", ""))
    parser.add_argument("--agent-id", default="washu-lab-forwarder")
    parser.add_argument("--honey-user", default="hw_alex.hale")
    args = parser.parse_args()

    if not args.token:
        print("Set AGENT_INGEST_TOKEN or pass --token", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "agent_id": args.agent_id,
        "events": [
            {
                "event_id": 4768,
                "severity": "info",
                "source": "Domain Controller",
                "actor": "WKS-031",
                "target": args.honey_user,
                "description": f"TGT requested for {args.honey_user}",
                "timestamp": now,
            },
            {
                "event_id": 4625,
                "severity": "medium",
                "source": "Security Log",
                "actor": "10.10.14.7",
                "target": args.honey_user,
                "description": f"Failed logon against {args.honey_user}",
                "timestamp": now,
            },
        ],
    }

    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/api/monitoring/ingest",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Agent-Token": args.token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
