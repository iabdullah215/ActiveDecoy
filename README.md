# ActiveDecoy: Autonomous ITDR & Deception Framework

ActiveDecoy is an automated ITDR (Identity Threat Detection and Response) framework designed to orchestrate and deploy believable Active Directory honey-objects for proactive lateral movement detection.

## Highlights

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
├── scripts/
├── data/
├── README.md
├── SETUP.md
└── requirements.txt
```

## Features

### Connection

- Host OS detection.
- LDAP validation with structured debug output.
- Hypervisor session validation for authorized lab bridges.

### Visualization

- NeoDash embedding for graph dashboards.
- Color-coded node presentation for normal and honey objects.
- Filtered graph previews for usernames, roles, and active state.

### Deception

- Honey-user, honey-server, shadow DC, and breadcrumb planning.
- Cypher generation for Neo4j ingestion.
- Real-time payload preview in the UI.

### Monitoring

- Live event feed for 4768, 4769, 4625, and 4624 signals with severity filtering.
- Honey-object interaction correlation against the last deployed deception plan.
- Lab interaction simulator to exercise the detection pipeline end to end.
- Alert triage with per-event and bulk acknowledgement plus rollup stats.

## Quick Start

1. Install dependencies from `requirements.txt`.
2. Configure Neo4j and directory credentials in `SETUP.md`.
3. Launch the FastAPI backend with Uvicorn.
4. Sign in with the test credentials for the local lab build.

## Development Notes

- The project uses Jinja2 templates and a Tailwind CDN for the dashboard shell.
- The backend keeps AD and hypervisor state in the user session during the lab workflow.
- The code is designed to be extended with real connectors and policy enforcement in your own environment.

## Collaborators:

- Muhammad Abdullah
- Faisal
- Mahavia 
- Abdullah Saif
- Abdul Ahad Abbasi
