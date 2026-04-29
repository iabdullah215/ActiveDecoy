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

- Event feed surface for 4768, 4769, and 4625 signals.
- Session-aware status tracking.

## Quick Start

1. Install dependencies from `requirements.txt`.
2. Configure Neo4j and directory credentials in `SETUP.md`.
3. Launch the FastAPI backend with Uvicorn.
4. Sign in with the test credentials for the local lab build.

## Development Notes

- The project uses Jinja2 templates and Tailwind CDN for the dashboard shell.
- The backend keeps AD and hypervisor state in the user session during the lab workflow.
- The code is designed to be extended with real connectors and policy enforcement in your own environment.
<<<<<<< HEAD
# ActiveDecoy
An automated ITDR (Identity Threat Detection and Response) framework designed to orchestrate and deploy believable Active Directory honey-objects for proactive lateral movement detection.
=======
# ActiveDecoy: Autonomous ITDR & Deception Framework

ActiveDecoy is a lab-oriented Identity Threat Detection & Response platform for directory visibility, honey-object deployment, and graph-driven monitoring.

## Highlights

- Real-time graph visualization backed by Neo4j and NeoDash.
- Multi-hypervisor bridge support for VMware, VirtualBox, and UTM wrapper flows.
- Automated honey-object planning for users, servers, breadcrumbs, and shadow DC personas.
- Dark-mode cybersecurity dashboard with neon accents and a session-aware workflow.

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

- Event feed surface for 4768, 4769, and 4625 signals.
- Session-aware status tracking.

## Quick Start

1. Install dependencies from `requirements.txt`.
2. Configure Neo4j and directory credentials in `SETUP.md`.
3. Launch the FastAPI backend with Uvicorn.
4. Sign in with the test credentials for the local lab build.

## Development Notes

- The project uses Jinja2 templates and Tailwind CDN for the dashboard shell.
- The backend keeps AD and hypervisor state in the user session during the lab workflow.
- The code is designed to be extended with real connectors and policy enforcement in your own environment.
>>>>>>> 8e5b058 (Initial Build)
