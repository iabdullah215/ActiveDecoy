# Authorized deployment runbook

Use this runbook only on **systems and directories you own or are explicitly authorized to test**.

## Pre-flight checklist

- [ ] Written authorization for the lab scope (AD OU, VLAN, test window)
- [ ] `.env` copied from `.env.example`; default passwords rotated for shared labs
- [ ] `ENFORCE_SECURE_DEFAULTS=true` on any non-solo environment
- [ ] Dedicated **honey OU** created in AD (example: `OU=Honey,OU=Lab,DC=lab,DC=local`)
- [ ] `AD_HONEY_OU` set; `AD_REQUIRE_NAME_PREFIX=true`; prefix `hw_` (default)
- [ ] Neo4j reachable (`NEO4J_URI`, `NEO4J_PASSWORD`)
- [ ] `AGENT_INGEST_TOKEN` set if using Washu Agent or SIEM ingest
- [ ] Hypervisor VM name recorded (`HYPERVISOR_VM_NAME`, default `Washu-DC`)

## Phase 1 — Bootstrap console

```bash
cp .env.example .env
# Edit secrets, AD_HONEY_OU, tokens

docker compose up --build -d
# or: ./scripts/bootstrap.sh && ./scripts/run.sh --reload
```

Verify:

```bash
curl -s http://127.0.0.1:8000/api/health | python -m json.tool
```

Sign in at `http://127.0.0.1:8000` with `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

## Phase 2 — Directory bridge

1. **Connection** → enter LDAP host, bind DN, base DN, credentials.
2. **Save profile** → **Test connection** (retries configured via `CONNECTION_RETRIES`).
3. **Import directory** → confirm user/group/computer counts on Home.
4. Optional: `python scripts/import_sample_graph.py` if Neo4j is empty and you want sample honey nodes.

## Phase 3 — Policy review

1. Open **Policy** — confirm honey OU and naming checks pass.
2. Review **Deny-logon GPO** checklist; link GPO to honey OU only (never DC OUs).
3. Note monitored domains (`AD_MONITORED_DOMAINS` if multi-domain).

## Phase 4 — Deploy deception

1. **Deception** → select modules (`honey_users`, `honey_servers`, etc.).
2. First run: **Dry-run** + **AD preflight** to validate OU and LDAP writes.
3. Enable **Provision in Active Directory** only when `AD_PROVISION_ENABLED=true`.
4. Optional **Sync to Neo4j** when graph is connected.
5. Confirm deployment history and `policy` score in the API response.

Blocked provision? Check Policy page — empty `AD_HONEY_OU` or bad object names block live writes.

## Phase 5 — Telemetry

**Option A — Lab simulator (no agent)**

- Monitoring → **Simulate interaction** (requires prior deploy).

**Option B — Washu Agent**

```bash
export WASHU_INGEST_TOKEN="$AGENT_INGEST_TOKEN"
python -m washu_agent run --source demo --console-url http://127.0.0.1:8000
```

Confirm Monitoring → **Washu Agent** card shows `healthy`.

**Option C — Scripted demo**

```bash
./scripts/demo_walkthrough.sh
```

## Phase 6 — Exercise and triage

1. Monitoring → enable **Live stream (SSE)**; optionally **Hide baseline noise**.
2. Trigger honey events (simulate, agent, or authorized red-team touch).
3. Click honey rows for playbooks; **Acknowledge** after containment notes.
4. Export evidence: Policy → JSON / STIX / syslog.

## Teardown

1. **Deception** → **Teardown last AD deploy** (removes provisioned honey objects).
2. Verify objects gone in AD and deployment history status `torn_down`.
3. Stop agent: `pkill -f "washu_agent run"` or stop the monitoring VM.
4. `docker compose down` (add `-v` only if you intend to wipe Neo4j data).

## Post-exercise

- Archive exports and audit logs (`activedecoy.audit` logger output).
- Reset lab passwords if exercise credentials were exposed.
- Document findings against playbooks on the Policy page.

## Rollback triggers

| Symptom | Action |
|---------|--------|
| Honey objects outside OU | Teardown immediately; fix `AD_HONEY_OU` |
| Production account touched | Stop exercise; rotate creds; review GPO scope |
| Agent token leaked | Rotate `AGENT_INGEST_TOKEN`; restart app + agents |
| Neo4j corrupt / wrong graph | `docker compose down`; clear volume or re-import |
