#!/usr/bin/env python3
"""Capture ActiveDecoy UI screenshots (optionally after establishing connectors)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")

PAGES = [
    ("01_login", "/login", False),
    ("02_home", "/home", True),
    ("03_connection", "/connection", True),
    ("04_visualization", "/visualization", True),
    ("05_deception", "/deception", True),
    ("06_monitoring", "/monitoring", True),
    ("07_policy", "/policy", True),
    ("08_guide", "/guide", True),
    ("09_api_docs", "/docs", False),
]


def establish_connectors_in_page(page) -> None:
    """Run connector workflow in the active browser session."""

    def post_form(path: str, data: dict[str, str] | list[tuple[str, str]]) -> None:
        if isinstance(data, dict):
            pairs = list(data.items())
        else:
            pairs = data
        body = urlencode(pairs)
        # Use fetch from the logged-in page so session cookies apply.
        result = page.evaluate(
            """async ({ path, body }) => {
                const response = await fetch(path, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body,
                    credentials: 'same-origin',
                });
                return { ok: response.ok, status: response.status, body: await response.text() };
            }""",
            {"path": path, "body": body},
        )
        if not result.get("ok"):
            raise RuntimeError(f"{path} failed: {result}")

    post_form(
        "/api/connection/save",
        {
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
            "wrapper_command": os.environ.get(
                "HYPERVISOR_WRAPPER_COMMAND",
                "/app/scripts/lab_hypervisor_health.sh",
            ),
            "auto_test_on_load": "true",
        },
    )
    post_form("/api/connection/retest", {})
    post_form("/api/connection/enumerate", {"sync_to_graph": "true", "replace": "true"})
    post_form(
        "/api/deception/deploy",
        [
            ("modules", "honey_users"),
            ("modules", "honey_servers"),
            ("modules", "breadcrumbs"),
            ("sync_to_graph", "true"),
            ("provision_ad", "false"),
            ("dry_run", "false"),
        ],
    )
    post_form("/api/monitoring/simulate", {"count": "3"})
    token = os.environ.get("AGENT_INGEST_TOKEN", "")
    if token:
        page.evaluate(
            """async ({ token, vmName }) => {
                await fetch('/api/agents/heartbeat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Agent-Token': token,
                    },
                    body: JSON.stringify({
                        agent_id: 'washu-agent',
                        vm_name: vmName,
                        status: 'healthy',
                    }),
                    credentials: 'same-origin',
                });
            }""",
            {"token": token, "vmName": os.environ.get("HYPERVISOR_VM_NAME", "Washu-DC")},
        )


def establish_connectors(client: httpx.Client) -> None:
    """Run the full connector workflow so UI shows connected state."""
    client.post(
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
            "wrapper_command": os.environ.get(
                "HYPERVISOR_WRAPPER_COMMAND",
                "/app/scripts/lab_hypervisor_health.sh",
            ),
            "auto_test_on_load": "true",
        },
    ).raise_for_status()
    retest = client.post("/api/connection/retest")
    retest.raise_for_status()
    bridge = retest.json().get("checklist", {}).get("bridge", {})
    if bridge.get("status") != "connected":
        raise RuntimeError(f"Bridge not connected: {bridge}")

    client.post(
        "/api/connection/enumerate",
        data={"sync_to_graph": "true", "replace": "true"},
    ).raise_for_status()
    client.post(
        "/api/deception/deploy",
        data={
            "modules": ["honey_users", "honey_servers", "breadcrumbs"],
            "sync_to_graph": "true",
            "provision_ad": "false",
            "dry_run": "false",
        },
    ).raise_for_status()
    client.post("/api/monitoring/simulate", data={"count": "3"}).raise_for_status()

    token = os.environ.get("AGENT_INGEST_TOKEN", "")
    if token:
        client.post(
            "/api/agents/heartbeat",
            headers={"X-Agent-Token": token},
            json={
                "agent_id": "washu-agent",
                "vm_name": os.environ.get("HYPERVISOR_VM_NAME", "Washu-DC"),
                "status": "healthy",
                "source": "demo",
            },
        ).raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--connected",
        action="store_true",
        help="Establish LDAP/hypervisor/agent connectors before capture",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Screenshot output directory (default: screenshots or screenshots/connected)",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        print("ADMIN_PASSWORD not set in .env", file=sys.stderr)
        return 1

    out_dir = args.output_dir or (ROOT / "screenshots" / ("connected" if args.connected else ""))
    out_dir = out_dir if str(out_dir).endswith("connected") or not args.connected else out_dir
    if args.connected and args.output_dir is None:
        out_dir = ROOT / "screenshots" / "connected"
    elif args.output_dir is None:
        out_dir = ROOT / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.goto(f"{BASE_URL}/login", wait_until="load")
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE_URL}/home", timeout=15000)

        if args.connected:
            print("Establishing connectors in browser session...")
            establish_connectors_in_page(page)
            page.goto(f"{BASE_URL}/home", wait_until="load")
            page.wait_for_timeout(1500)

        for slug, path, needs_auth in PAGES:
            output = out_dir / f"{slug}.png"
            url = f"{BASE_URL}{path}"
            print(f"Capturing {path} -> {output}")
            if not needs_auth:
                guest = browser.new_context(viewport={"width": 1440, "height": 900})
                guest_page = guest.new_page()
                guest_page.goto(url, wait_until="load")
                guest_page.wait_for_timeout(1000)
                guest_page.screenshot(path=str(output), full_page=True)
                guest.close()
            else:
                page.goto(url, wait_until="load")
                page.wait_for_timeout(2000)
                page.screenshot(path=str(output), full_page=True)
            manifest.append({"page": path, "file": str(output.relative_to(ROOT))})

        browser.close()

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Saved {len(manifest)} screenshots to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
