# API reference

ActiveDecoy exposes a REST API under `/api/*`. Interactive OpenAPI docs:

- **Swagger UI:** `http://127.0.0.1:8000/docs`
- **ReDoc:** `http://127.0.0.1:8000/redoc`
- **OpenAPI JSON:** `http://127.0.0.1:8000/openapi.json`

Most routes require a **session cookie** from `POST /login`. Agent routes use **`X-Agent-Token`** (or `Authorization: Bearer`) matching `AGENT_INGEST_TOKEN`.

## Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/login` | — | Form: `username`, `password` → session cookie |
| GET | `/logout` | session | Clear session |

## System

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/health` | optional | Liveness, graph + agent summary |
| GET | `/api/system-state` | session | Redacted bridge state |

## Connection (`/api/connection`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/profile` | Saved LDAP/hypervisor profile (no passwords) |
| POST | `/save` | Persist profile form fields |
| POST | `/test` | Validate LDAP + hypervisor |
| POST | `/retest` | Re-run test on saved profile |
| POST | `/disconnect` | Clear bridge session state |
| GET | `/status` | Checklist + bridge status |
| POST | `/enumerate` | LDAP directory import → optional Neo4j sync |

## Graph (`/api/graph`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/nodes` | Filtered node list (honey/AD scopes) |
| GET | `/topology` | Nodes + edges for canvas |
| GET | `/health` | Neo4j connectivity |

## Deception (`/api/deception`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/deploy` | Form: `modules[]`, `sync_to_graph`, `provision_ad`, `dry_run` |
| GET | `/history` | Deployment records |
| GET | `/preflight` | AD honey OU preflight |
| POST | `/teardown` | Remove last AD provision |

Deploy responses include `policy` posture report.

## Monitoring (`/api/monitoring`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/events` | session | Filtered event feed |
| GET | `/stats` | session | Rollup counters |
| GET | `/stream` | session | SSE live feed (`?once=1` for probe) |
| POST | `/ingest` | agent token | Bulk event ingest (max 100/request) |
| POST | `/simulate` | session | Lab honey interaction generator |
| POST | `/acknowledge` | session | Ack one event or all honey alerts |

### Ingest body (example)

```json
{
  "agent_id": "washu-agent",
  "events": [
    {
      "event_id": 4768,
      "actor": "WKS-031",
      "target": "hw_alex.hale",
      "severity": "high",
      "description": "TGT requested"
    }
  ]
}
```

Headers: `X-Agent-Token: <AGENT_INGEST_TOKEN>`

## Agents (`/api/agents`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/heartbeat` | agent token | Register/update agent health |
| GET | `/` | session | List agents + healthy counts |
| GET | `/{agent_id}` | session | Single agent record |

## Policy (`/api/policy`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Policy posture report |
| GET | `/deny-logon` | GPO artifact guidance |
| GET | `/playbooks` | Response playbooks list |
| GET | `/playbook` | Playbook for `uid` or `event_id` |
| GET | `/export` | Alerts as `json`, `stix`, or `syslog` |

Export query params: `honey_only`, `exclude_baseline`, `download=true`, `limit`.

## Event IDs (monitoring)

| ID | Meaning |
|----|---------|
| 4768 | Kerberos TGT request |
| 4769 | Kerberos service ticket |
| 4625 | Failed logon |
| 4624 | Successful logon |

## Error codes

| Code | Typical cause |
|------|----------------|
| 401 | Missing/invalid session or agent token |
| 403 | — (rare; use 401) |
| 429 | Login rate limit |
| 503 | Ingest/heartbeat disabled (empty `AGENT_INGEST_TOKEN`) |

## Version

API version tracks the app release (`app.version`, currently in `app/main.py`). Check `/openapi.json` → `info.version` on a running instance.
