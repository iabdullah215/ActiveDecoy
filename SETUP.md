# ActiveDecoy Setup Guide

## Prerequisites

- Python 3.10 or newer (3.12 recommended).
- Docker and Docker Compose (optional, but recommended for Chunk 1 lab bootstrap).
- Neo4j Desktop **or** the Neo4j service from `docker-compose.yml`.
- LDAP access to the target directory in an authorized lab.
- VMware, VirtualBox, or UTM integration for the lab DC host (optional until Connection hardening).

## 0. Docker Compose Lab Stack (recommended)

This starts Neo4j and the ActiveDecoy console together.

1. Copy env defaults:
   ```bash
   cp .env.example .env
   ```
2. Start the stack:
   ```bash
   docker compose up --build -d
   ```
3. Open `http://127.0.0.1:8000` and sign in with the admin credentials from `.env`.
4. Neo4j Browser is available at `http://127.0.0.1:7474` (auth: `neo4j` / value of `NEO4J_PASSWORD`).
5. Optional sample graph import (from the host, with venv active):
   ```bash
   python scripts/import_sample_graph.py
   ```

Useful commands:

```bash
docker compose ps
docker compose logs -f app
docker compose down
```

Compose defaults (`NEO4J_PASSWORD=ActiveDecoyNeo4j!`, lab admin credentials) are for **local authorized labs only**. Change them before any shared use.

## 1. Python Environment (local development)

1. Create and activate a virtual environment, or run:
   ```bash
   ./scripts/bootstrap.sh
   ```
2. Install `requirements.txt`.
3. Confirm the backend imports cleanly:
   ```bash
   python -c "from app.main import app; print(app.version)"
   ```
4. Start the app:
   ```bash
   ./scripts/run.sh --reload
   # or: python main.py --reload
   ```

On startup the app validates configuration and logs warnings for default secrets, missing Neo4j password, and similar issues. Graph helpers stay offline until `NEO4J_PASSWORD` is set.

## 2. Neo4j Configuration

1. Start Neo4j via Docker Compose, Neo4j Desktop, or your server instance.
2. Create or use a database dedicated to the lab.
3. Note the bolt URI, username, and password.
4. Add the credentials to `.env`.
5. Import Cypher payloads from the Deception workflow after review, or load the sample file.

Recommended environment variables:

- `NEO4J_URI=bolt://localhost:7687` (local Python) or `bolt://neo4j:7687` (Compose app container)
- `NEO4J_USERNAME=neo4j`
- `NEO4J_PASSWORD=<strong-password>`

## 3. Hypervisor API Setup

Optional packages are commented in `requirements.txt`. Install only what your lab needs:

```bash
pip install "pyvmomi>=8.0.3"          # VMware
# VirtualBox: use the SDK bindings that match your VirtualBox version
# pywin32: Windows hosts only
# impacket: later AD tooling (Chunk 4+)
```

### VMware

1. Create an account with read and console access to the lab virtualization endpoint.
2. Record the vCenter or ESXi hostname.
3. Provide the username and password in the Connection page or environment config.
4. Verify pyVmomi connectivity before using the bridge.

### VirtualBox

1. Install the VirtualBox Extension Pack if required by your lab.
2. Confirm the Python bindings match the installed VirtualBox version.
3. Supply the target VM name for the Washu Agent or the DC host.

### UTM

1. Create a trusted local wrapper script that can report VM health.
2. Pass the wrapper path through the Connection page.
3. Keep the wrapper minimal and auditable.

## 4. Active Directory Permissions

The account used by ActiveDecoy should have only the minimum permissions required for the lab.

Required capabilities usually include:

- Read access to directory objects and attributes.
- Permission to query group, user, and computer relationships.
- Access to collect the event log sources you plan to monitor.
- Permission to create the lab honey objects you intentionally deploy.

### Directory import (Chunk 3)

After a successful LDAP validation:

1. Open **Connection** and click **Import directory**.
2. ActiveDecoy enumerates users, groups, computers, memberships, and trusts (paged; capped by `LDAP_MAX_OBJECTS`).
3. When Neo4j is configured, topology is upserted as `ADUser` / `ADGroup` / `ADComputer` / `ADTrust` / `ADDomain` nodes with `MEMBER_OF` and `IN_DOMAIN` relationships.
4. Visualization shows an interactive topology canvas (plus inventory) for honey and AD objects.

Tune limits in `.env`:

- `LDAP_PAGE_SIZE=200`
- `LDAP_MAX_OBJECTS=500`

### Visualization (Chunk 5)

- Primary view: native canvas at `/visualization` (drag nodes, zoom, click for details).
- Filters: scope (all/honey/AD), name/type, role, active-only, honey-only.
- API: `GET /api/graph/topology` returns nodes + edges (Neo4j when connected, session/preview otherwise).
- NeoDash iframe remains optional/secondary.

### Telemetry ingest (Chunk 6)

1. Set a strong `AGENT_INGEST_TOKEN` in `.env` (ingest stays disabled while empty).
2. Deploy honey objects so correlation has names/SPNs to match.
3. Forward events to `POST /api/monitoring/ingest` with header `X-Agent-Token: <token>`:

```json
{
  "agent_id": "washu-agent",
  "events": [
    {
      "event_id": 4768,
      "actor": "WKS-031",
      "target": "hw_alex.hale",
      "severity": "info",
      "source": "Domain Controller",
      "description": "TGT requested"
    }
  ]
}
```

4. Open Monitoring with **Live stream (SSE)** enabled, or poll `/api/monitoring/events`.
5. Sample forwarder:

```bash
export AGENT_INGEST_TOKEN=your-token
python scripts/forward_sample_events.py --honey-user hw_alex.hale
```

Events persist in `data/monitoring_events.json` (gitignored).

### Policy & ITDR (Chunk 8)

1. Set `AD_HONEY_OU`, keep `AD_REQUIRE_NAME_PREFIX=true`, and optionally `AD_MONITORED_DOMAINS`.
2. Open **Policy** for posture score, deny-logon GPO checklist, and response playbooks.
3. Live AD provisioning is blocked when critical checks fail (empty honey OU / bad names).
4. Export alerts: `GET /api/policy/export?format=json|stix|syslog&honey_only=true&exclude_baseline=true`.
5. On Monitoring, enable **Hide baseline noise** and click a honey row for the matching playbook.

If you are testing honey-user creation or similar workflows, ensure the account has explicit authorization to create directory objects in the chosen OU.

### AD honey provisioning (Chunk 4)

Provisioning is **off by default**. Enable only in an authorized lab:

1. Create a dedicated OU (example: `OU=Honey,OU=Lab,DC=lab,DC=local`).
2. Set in `.env`:
   - `AD_PROVISION_ENABLED=true`
   - `AD_HONEY_OU=OU=Honey,OU=Lab,DC=lab,DC=local`
   - `AD_HONEY_NAME_PREFIX=hw_` (required prefix for create/delete safety)
3. Save/validate LDAP on the Connection page (bind account needs create/delete in that OU).
4. On **Deception**:
   - Optionally run **AD preflight**
   - Prefer **Dry-run** first
   - Check **Provision in Active Directory** for honey users / bait computers
   - Use **Teardown last AD deploy** to remove provisioned objects

Safety controls:

- Objects must land under `AD_HONEY_OU`
- Names must use `AD_HONEY_NAME_PREFIX` when `AD_REQUIRE_NAME_PREFIX=true`
- Teardown refuses DNs outside the honey OU or without the prefix
- Deployment history is stored in `data/deployments.json` (gitignored)

Breadcrumbs and Honey DC remain plan/graph-only in this chunk.

## 5. Washu Agent Setup

The Washu Agent is the monitoring forwarder that runs on an isolated lab VM, ships Security events to ActiveDecoy, and posts heartbeats so the console can show agent health.

### On the console host

1. Set `AGENT_INGEST_TOKEN` (and optionally `AGENT_STALE_SECONDS=90`) in `.env`.
2. Under **Connection → Hypervisor**, set the VM name (default `Washu-DC`) so operators know which VM is expected.
3. Confirm Monitoring shows the **Washu Agent** card.

### On the monitoring VM

```bash
# From the ActiveDecoy repo (or copy the washu_agent/ package)
cp washu_agent/.env.example washu_agent/.env
# Set WASHU_CONSOLE_URL and WASHU_INGEST_TOKEN (= AGENT_INGEST_TOKEN)

# Reachability
python -m washu_agent check --console-url http://<console-host>:8000

# Single demo cycle (dry-run prints payloads without posting)
python -m washu_agent once --source demo --dry-run

# Continuous forwarder (demo source until real winlog/file is configured)
export WASHU_INGEST_TOKEN=your-token
python -m washu_agent run --source demo --console-url http://<console-host>:8000
```

**Event sources**

| Source | Use |
|--------|-----|
| `demo` | Synthetic honey events for corridor / lab demos |
| `file` | Tail NDJSON export (`WASHU_EVENT_LOG_PATH`) |
| `winlog` | Windows Security log via `pywin32` (Windows only) |
| `auto` | Prefer file/winlog when available, else demo |

APIs: `POST /api/agents/heartbeat`, `GET /api/agents` (session auth), ingest via Chunk 6.

Keep the agent on a separate admin path from the honeypot objects it observes.

## 6. Launching the App

### Docker

```bash
docker compose up --build -d
```

### Local Python

1. Start Neo4j (Compose neo4j service alone is fine: `docker compose up -d neo4j`).
2. Start the FastAPI application with Uvicorn / `python main.py`.
3. Open the login page in your browser.
4. Sign in with the development credentials for the lab build.
5. Walk through Connection, Visualization, Deception, and Monitoring in sequence.

## 7. Continuous Integration

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR:

- dependency install
- import smoke check
- `unittest discover -s tests`
- `docker compose config` syntax check

## Security Notes

- Do not commit `.env`.
- Change `SESSION_SECRET`, `ADMIN_PASSWORD`, and `NEO4J_PASSWORD` before shared lab use.
- Set `ENFORCE_SECURE_DEFAULTS=true` on shared labs so the app refuses to start with default secrets.
- Restrict `CORS_ORIGINS` to the console URLs you actually use (default: localhost only).
- Login is rate-limited (`LOGIN_RATE_LIMIT` / `LOGIN_RATE_WINDOW_SECONDS`).
- LDAP and hypervisor passwords are kept in a server-side secret store — not in the signed session cookie.
- Sensitive actions (login, logout, connection save/test, deception deploy) emit JSON audit lines on logger `activedecoy.audit`.
- OIDC/LDAP console login is not implemented yet; admin credentials remain env-based for the lab console.
