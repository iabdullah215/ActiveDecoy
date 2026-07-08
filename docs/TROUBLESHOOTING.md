# Troubleshooting guide

Symptoms → likely cause → fix for the ActiveDecoy lab stack.

## Console / app

### App won't start — `ENFORCE_SECURE_DEFAULTS`

**Symptom:** Process exits on startup with message about default secrets.

**Fix:** Set unique `SESSION_SECRET`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD` in `.env`, or set `ENFORCE_SECURE_DEFAULTS=false` for solo local dev only.

### Login returns 429 / rate limited

**Symptom:** "Too many attempts" after failed logins.

**Fix:** Wait `LOGIN_RATE_WINDOW_SECONDS` (default 60s) or restart the app to clear in-memory buckets. Use correct credentials from `.env`.

### Session lost after restart

**Symptom:** Redirected to login; bridge profile empty.

**Expected:** Session cookies are in-memory per process. Re-login and re-save connection profile. LDAP passwords remain in server secret store if `connection_secret_id` persisted.

---

## LDAP / Active Directory

### Connection test fails — ldap3 missing

**Symptom:** `ldap3 is not installed in the active environment`.

**Fix:**

```bash
pip install ldap3
```

### Connection test fails — bind error

**Symptom:** Debug shows `LDAP validation failed` / invalid credentials.

**Fix:**

- Confirm `LDAP_HOST`, port (`389` / `636` + `LDAP_USE_SSL=true`)
- Use a bind account with read (and write if provisioning) rights
- Verify `LDAP_BASE_DN` or leave empty for root DSE discovery
- Check firewall from console host to DC

### Import directory returns 400 / profile not saved

**Symptom:** Enumerate requires saved profile.

**Fix:** Connection → **Save** before **Import directory**.

### AD provision blocked by policy

**Symptom:** Deploy succeeds in plan-only mode but AD writes blocked.

**Fix:** Set `AD_HONEY_OU`; ensure object names use `AD_HONEY_NAME_PREFIX` (`hw_`). Review Policy page checks.

### Preflight — honey OU does not exist

**Symptom:** `Honey OU does not exist: OU=Honey,...`

**Fix:** Create the OU in AD before provisioning. Do not point at `CN=Users` or production OUs.

### Provision disabled

**Symptom:** Checkbox greyed out or API says provisioning disabled.

**Fix:** Set `AD_PROVISION_ENABLED=true`, configure `AD_HONEY_OU`, save valid LDAP profile.

---

## Neo4j / graph

### Graph shows "Not configured"

**Symptom:** Home health → Graph not configured.

**Fix:** Set `NEO4J_PASSWORD` (and `NEO4J_URI` if non-default) in `.env`.

### Graph shows "Unavailable" / connection refused

**Symptom:** `Neo4j configured but unreachable` in logs.

**Fix:**

```bash
docker compose up -d neo4j
docker compose logs neo4j
```

Confirm `bolt://localhost:7687` from host matches compose port mapping. In Docker app service, use `bolt://neo4j:7687`.

### Visualization empty after deploy

**Symptom:** Canvas shows preview nodes only.

**Fix:** Enable **Sync to Neo4j** on deploy, or run `python scripts/import_sample_graph.py`. Check `GET /api/graph/topology` for `source: neo4j` vs `preview`.

### Cypher sync errors

**Symptom:** `graph_sync.errors` in deploy response.

**Fix:** Open Neo4j Browser; run failing Cypher manually. Check label conflicts and property types.

---

## Monitoring / telemetry

### Ingest returns 503 — agent disabled

**Symptom:** `Agent ingest is disabled. Set AGENT_INGEST_TOKEN`.

**Fix:** Set a non-empty `AGENT_INGEST_TOKEN` in `.env` and restart the app.

### Ingest returns 401

**Symptom:** Invalid agent token.

**Fix:** Match `X-Agent-Token` header to `AGENT_INGEST_TOKEN` exactly. Washu Agent: `WASHU_INGEST_TOKEN` same value.

### Simulate says no honey objects registered

**Symptom:** `ValueError` / message about registration.

**Fix:** Deploy a deception plan first (Deception page). Session stores `last_deployment` for correlation.

### SSE stream hangs in browser

**Symptom:** Feed stuck on "Reconnecting".

**Fix:** Ensure logged in (SSE requires session). Disable ad-block for localhost. For tests/API probes use `?once=1`.

### No honey correlation on ingest

**Symptom:** Events appear but `honey_object` empty.

**Fix:** Deploy plan so target names match (`hw_` prefix). Ingest `target` field must match registered honey user/SPN.

---

## Washu Agent

### Agent unhealthy / stale on Monitoring card

**Symptom:** `stale` or `No agents`.

**Fix:**

- Agent running: `python -m washu_agent run ...`
- Token matches console
- Console reachable from agent VM (`python -m washu_agent check`)
- Increase `AGENT_STALE_SECONDS` if heartbeat interval is long

### Agent can't reach console

**Symptom:** `Cannot reach console` / check fails.

**Fix:** Use host IP not `127.0.0.1` from another VM. Open firewall port `8000`. Set `WASHU_CONSOLE_URL`.

### Demo mode floods events

**Symptom:** Too many demo events.

**Fix:** Use `--source file` or `winlog` in production-like labs; demo throttles but still emits periodically.

---

## Docker Compose

### App healthcheck failing

**Symptom:** `activedecoy-app` unhealthy.

**Fix:**

```bash
docker compose logs app
curl -s http://127.0.0.1:8000/api/health
```

Ensure app finished startup; check `.env` mount and port conflicts.

### Neo4j auth errors

**Symptom:** `Unauthorized` in graph health.

**Fix:** Align `NEO4J_PASSWORD` in `.env` with `NEO4J_AUTH` in compose (`neo4j/${NEO4J_PASSWORD}`).

---

## Tests / CI

### unittest failures locally

**Fix:**

```bash
. .venv/bin/activate
python -m unittest discover -s tests -v
```

No live Neo4j/LDAP required. See `tests/README.md`.

---

## Getting help

1. Check audit log output (`activedecoy.audit`) for action/outcome JSON.
2. `GET /api/health` and authenticated `GET /api/system-state`.
3. Review [RUNBOOK.md](RUNBOOK.md) phase that failed.
4. Open an issue with redacted `.env` (never paste secrets).
