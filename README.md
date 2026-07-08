# ActiveDecoy: Autonomous ITDR & Deception Framework

ActiveDecoy is an automated ITDR (Identity Threat Detection and Response) framework designed to orchestrate and deploy believable Active Directory honey-objects for proactive lateral movement detection.

## Security Disclaimer

This project is intended for educational, defensive, and explicitly authorized security testing only. Do not deploy ActiveDecoy against systems or directories you do not own or manage.

## Repository Layout

```text
ActiveDecoy/
├── app/
│   ├── api/
│   ├── core/
│   ├── static/
│   └── templates/
├── washu_agent/
├── scripts/
├── data/
├── tests/
├── .github/workflows/
├── docker-compose.yml
├── Dockerfile
├── README.md
├── SETUP.md
└── requirements.txt
```

## Features

### Connection

- Host OS detection.
- LDAP validation with structured debug output.
- Hypervisor session validation for authorized lab bridges.
- Directory enumeration (users, groups, computers, trusts) with Neo4j import.

### Visualization

- Native interactive topology canvas (nodes + relationships) backed by Neo4j.
- Filters for scope (all/honey/AD), name/type, role, and active/honey markers.
- Inventory table synced with the canvas.
- Optional NeoDash embed for external dashboards.

### Deception

- Honey-user, honey-server, shadow DC, and breadcrumb planning.
- Optional **Active Directory provisioning** into a dedicated honey OU (users + bait computers).
- Cypher generation for Neo4j ingestion.
- Dry-run preflight, teardown, and on-disk deployment history.
- Real-time payload preview in the UI.

### Monitoring

- Live event feed for 4768, 4769, 4625, and 4624 signals with severity filtering.
- Honey-object interaction correlation against the last deployed deception plan.
- Agent / SIEM bulk ingest (`POST /api/monitoring/ingest`) with token auth.
- Washu Agent package (`washu_agent/`) with heartbeat health on Monitoring.
- Persistent event store and SSE live stream for the Monitoring console.
- Lab interaction simulator to exercise the detection pipeline end to end.
- Alert triage with per-event and bulk acknowledgement plus rollup stats.

## Quick Start

### Option A — Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up --build -d
```

Open `http://127.0.0.1:8000` and sign in with credentials from `.env`. Details in [SETUP.md](SETUP.md).

### Option B — Local Python

1. Run `./scripts/bootstrap.sh` (creates venv, installs deps, copies `.env`).
2. Start Neo4j (Desktop or `docker compose up -d neo4j`).
3. Launch with `./scripts/run.sh --reload` or `python main.py --reload`.
4. Sign in with the lab admin credentials from `.env`.

## Development Notes

- The project uses Jinja2 templates and a custom CSS shell for the dashboard.
- The backend keeps AD and hypervisor state in the user session during the lab workflow.
- Startup validates configuration and emits warnings for default secrets / missing Neo4j password.
- Login is rate-limited; LDAP/hypervisor passwords stay server-side (not in the session cookie).
- Optional lab connectors (`pyvmomi`, VirtualBox bindings, `pywin32`, `impacket`) are documented in `requirements.txt` and SETUP.md — install only what you need.
- The code is designed to be extended with real connectors and policy enforcement in your own environment.

## Collaborators

- Muhammad Abdullah
- Faisal
- Mahavia
- Abdullah Saif
- Abdul Ahad Abbasi
