# ActiveDecoy: Autonomous ITDR & Deception Framework

ActiveDecoy is an automated ITDR (Identity Threat Detection and Response) framework designed to orchestrate and deploy believable Active Directory honey-objects for proactive lateral movement detection.

## Security Disclaimer

This project is intended for educational, defensive, and explicitly authorized security testing only. Do not deploy ActiveDecoy against systems or directories you do not own or manage.

## Screenshots

|  |  |
|:---:|:---:|
| ![](docs/images/login.jpg) | ![](docs/images/dashboard-overview.jpg) |
| ![](docs/images/connection-ldap-directory.jpg) | ![](docs/images/connection-diagnostic-log.jpg) |
| ![](docs/images/visualization-graph-filters.jpg) | ![](docs/images/visualization-topology.jpg) |
| ![](docs/images/visualization-graph-canvas.jpg) | ![](docs/images/visualization-inventory-servers.jpg) |
| ![](docs/images/visualization-inventory-users.jpg) | ![](docs/images/visualization-neodash.jpg) |
| ![](docs/images/deception-console.jpg) | ![](docs/images/deception-deployment-modules.jpg) |
| ![](docs/images/monitoring-console.jpg) | ![](docs/images/monitoring-event-stream.jpg) |
| ![](docs/images/monitoring-event-feed.jpg) | ![](docs/images/monitoring-alert-triage.jpg) |
| ![](docs/images/policy-overview.jpg) | ![](docs/images/policy-playbooks.jpg) |
| ![](docs/images/policy-response-playbooks.jpg) | ![](docs/images/user-guide.jpg) |
| ![](docs/images/user-guide-safety-notes.jpg) | ![](docs/images/api-docs-connection.jpg) |
| ![](docs/images/api-docs-graph-monitoring.jpg) | ![](docs/images/api-docs-policy-deception.jpg) |
| ![](docs/images/api-docs-page-routes.jpg) | ![](docs/images/api-docs-schemas.jpg) |
| ![](docs/images/api-docs-schema-models.jpg) |  |

## Repository Layout

```text
ActiveDecoy/
├── app/
├── washu_agent/
├── docs/
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
- Baseline noise suppression and alert export (JSON / STIX / syslog).

### Policy & ITDR

- Honey OU + naming prefix enforcement with provision gating.
- Deny-logon GPO artifacts and operator checklist.
- Response playbooks per Event ID.
- Multi-domain tracking via OU / `AD_MONITORED_DOMAINS`.

## Documentation

| Guide | Description |
|-------|-------------|
| [SETUP.md](SETUP.md) | Bootstrap, Docker, env vars |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | New collaborator first-day guide |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Authorized deploy → exercise → teardown |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram and module map |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | LDAP, Neo4j, agent fixes |
| [docs/API.md](docs/API.md) | REST reference + `/docs` OpenAPI UI |
| [data/user_guide.md](data/user_guide.md) | In-console workflow (User Guide page) |

**Corridor demo:** `./scripts/demo_walkthrough.sh` (console must be running).

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
- **124+ unit/API tests** cover engines, mocked LDAP/Neo4j, E2E console flows, and concurrency — see `tests/README.md`.
- The code is designed to be extended with real connectors and policy enforcement in your own environment.

## Collaborators

- Muhammad Abdullah
- Muhammad Faisal Farooq
- Mahavia
- Abdullah Saif
- Abdul Ahad Abbasi
