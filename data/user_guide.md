# ActiveDecoy User Guide

## Overview

ActiveDecoy provides a lab-focused ITDR workflow for authenticated testing,
directory visibility, deception planning, and monitored response.

## Workflow

1. Authenticate with the development credentials.
2. Establish the directory bridge from the Connection page (save profile, validate with retries, optional auto-test on load).
3. Click **Import directory** to enumerate AD users/groups/computers/trusts and sync them into Neo4j when configured.
4. Review graph data in the Visualization page (interactive canvas + honey/AD inventory).
   Use filters for name, role, scope, and active/honey markers.
5. Deploy honey-object plans from the Deception page. Optionally dry-run, then
   provision honey users / bait computers into the configured AD honey OU, and
   tear them down when the lab exercise ends.
6. Track telemetry in the Monitoring page: filter the event feed by severity or
   event ID, enable live SSE streaming, use "Simulate interaction" or the Washu
   Agent (`python -m washu_agent run`) / ingest API for forwarded events, and
   acknowledge honey alerts as you triage them. The Washu Agent card shows
   heartbeat health for registered monitoring VMs.
7. Use the Policy page for deny-logon GPO guidance, playbooks, and alert export
   (JSON / STIX / syslog). Hide baseline noise on Monitoring when triaging.

## Further reading (repository docs)

- [docs/ONBOARDING.md](../docs/ONBOARDING.md) — collaborator setup
- [docs/RUNBOOK.md](../docs/RUNBOOK.md) — authorized deployment phases
- [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) — architecture diagrams
- [docs/TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md) — common failures
- [docs/API.md](../docs/API.md) — REST reference (`/docs` when app is running)
- Demo script: `./scripts/demo_walkthrough.sh`

## Safety Notes

- Use only on systems you own or are explicitly authorized to test.
- Keep the management UI and directory access inside a controlled network segment.
- Review generated Cypher before applying it to Neo4j in production-like labs.
