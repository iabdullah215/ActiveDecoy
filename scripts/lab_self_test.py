#!/usr/bin/env python3
"""End-to-end self-test for the authorized lab stack (connectors established)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")


class SelfTestFailure(Exception):
    pass


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    if not ok:
        raise SelfTestFailure(f"{name}: {detail or 'failed'}")


def main() -> int:
    load_dotenv(ROOT / ".env")
    username = os.environ.get("ADMIN_USERNAME", "HwatSauce")
    password = os.environ.get("ADMIN_PASSWORD", "")
    ingest_token = os.environ.get("AGENT_INGEST_TOKEN", "")

    if not password:
        print("ADMIN_PASSWORD missing from .env", file=sys.stderr)
        return 1

    results: list[str] = []
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        health = client.get("/api/health").json()
        check("Health API", health.get("status") == "ok", json.dumps(health.get("graph", {})))
        check("Neo4j connected", health.get("graph", {}).get("connected") is True)

        login = client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )
        check("Console login", login.status_code == 303, f"status={login.status_code}")

        save = client.post(
            "/api/connection/save",
            data={
                "ldap_host": os.environ.get("LDAP_HOST", "dc01.lab.local"),
                "ldap_port": os.environ.get("LDAP_PORT", "389"),
                "ldap_use_ssl": "false",
                "ldap_bind_dn": os.environ.get("LDAP_BIND_DN", "cn=admin,dc=lab,dc=local"),
                "ldap_password": os.environ.get("LDAP_PASSWORD", ""),
                "ldap_base_dn": os.environ.get("LDAP_BASE_DN", "dc=lab,dc=local"),
                "hypervisor_type": os.environ.get("HYPERVISOR_TYPE", "utm"),
                "hypervisor_endpoint": "",
                "hypervisor_username": "",
                "hypervisor_password": "",
                "hypervisor_vm_name": os.environ.get("HYPERVISOR_VM_NAME", "Washu-DC"),
                "wrapper_command": os.environ.get("HYPERVISOR_WRAPPER_COMMAND", "/app/scripts/lab_hypervisor_health.sh"),
                "auto_test_on_load": "true",
            },
        )
        body = save.json()
        check("Save connection profile", save.status_code == 200 and body.get("success"), body.get("profile", {}).get("ldap_host", ""))

        test = client.post("/api/connection/retest")
        test_body = test.json()
        bridge = test_body.get("checklist", {}).get("bridge", {})
        ldap = test_body.get("checklist", {}).get("ldap", {})
        hypervisor = test_body.get("checklist", {}).get("hypervisor", {})
        check("LDAP connector", ldap.get("status") == "ok", ldap.get("message", ""))
        check("Hypervisor connector", hypervisor.get("status") in {"ok", "skipped"}, hypervisor.get("message", ""))
        check("Bridge connected", bridge.get("status") == "connected", bridge.get("status", ""))

        enum = client.post("/api/connection/enumerate", data={"sync_to_graph": "true", "replace": "true"})
        enum_body = enum.json()
        summary = enum_body.get("summary", {})
        check(
            "Directory import",
            enum_body.get("success") and summary.get("users", 0) >= 1,
            f"users={summary.get('users', 0)} groups={summary.get('groups', 0)} computers={summary.get('computers', 0)}",
        )

        deploy = client.post(
            "/api/deception/deploy",
            data={
                "modules": ["honey_users", "honey_servers", "breadcrumbs"],
                "sync_to_graph": "true",
                "provision_ad": "false",
                "dry_run": "false",
            },
        )
        deploy_body = deploy.json()
        check(
            "Deception deploy",
            deploy_body.get("success") and len(deploy_body.get("objects", [])) >= 5,
            f"objects={len(deploy_body.get('objects', []))}",
        )

        topology = client.get("/api/graph/topology")
        topo_body = topology.json()
        check(
            "Graph topology",
            topology.status_code == 200 and len(topo_body.get("nodes", [])) >= 3,
            f"nodes={len(topo_body.get('nodes', []))}",
        )

        simulate = client.post("/api/monitoring/simulate", data={"count": "3"})
        sim_body = simulate.json()
        check("Monitoring simulate", sim_body.get("success") and len(sim_body.get("events", [])) >= 1)

        events = client.get("/api/monitoring/events", params={"honey_only": "true", "limit": 20})
        events_body = events.json()
        check(
            "Monitoring events feed",
            events.status_code == 200 and len(events_body.get("events", [])) >= 1,
            f"events={len(events_body.get('events', []))}",
        )

        policy = client.get("/api/policy/status")
        policy_body = policy.json()
        report = policy_body.get("report", {})
        check(
            "Policy posture",
            policy.status_code == 200 and report.get("score", 0) >= 40,
            f"score={report.get('score')}",
        )

        export = client.get("/api/policy/export", params={"format": "json", "honey_only": "true", "limit": 10})
        export_body = export.json()
        check("Policy export", export.status_code == 200 and export_body.get("count", 0) >= 1)

        if ingest_token:
            ingest = client.post(
                "/api/monitoring/ingest",
                headers={"X-Agent-Token": ingest_token},
                json={
                    "agent_id": "washu-agent",
                    "events": [
                        {
                            "event_id": 4768,
                            "actor": "WKS-031",
                            "target": "hw_avery.parker",
                            "severity": "critical",
                            "source": "Domain Controller",
                            "description": "Lab self-test TGT request",
                        }
                    ],
                },
            )
            check("Agent ingest", ingest.status_code == 200 and ingest.json().get("success"), ingest.text[:120])

            heartbeat = client.post(
                "/api/agents/heartbeat",
                headers={"X-Agent-Token": ingest_token},
                json={
                    "agent_id": "washu-agent",
                    "vm_name": os.environ.get("HYPERVISOR_VM_NAME", "Washu-DC"),
                    "status": "healthy",
                    "source": "demo",
                },
            )
            check("Agent heartbeat", heartbeat.status_code == 200, heartbeat.text[:120])

            agents = client.get("/api/agents/", follow_redirects=True)
            agents_body = agents.json()
            check(
                "Agent registry",
                agents.status_code == 200 and agents_body.get("healthy", 0) >= 1,
                f"healthy={agents_body.get('healthy', 0)}/{agents_body.get('total', 0)}",
            )
        else:
            print("[SKIP] Agent ingest — AGENT_INGEST_TOKEN not set")

        pages = ["/home", "/connection", "/visualization", "/deception", "/monitoring", "/policy", "/guide"]
        for path in pages:
            page = client.get(path, follow_redirects=False)
            check(f"Page {path}", page.status_code == 200, f"status={page.status_code}")

    print("\nAll self-tests passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SelfTestFailure as exc:
        print(f"\nSelf-test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
