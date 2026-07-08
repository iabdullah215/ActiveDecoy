# Collaborator onboarding

Welcome to ActiveDecoy. This guide gets you from clone to a working lab console in one session.

## Day 0 — Access and intent

- Confirm you have **written authorization** for the target lab AD environment.
- Read the security disclaimer in [README.md](../README.md).
- Skim [ARCHITECTURE.md](ARCHITECTURE.md) for component layout.

## Day 1 — Local setup (≈30 minutes)

### 1. Clone and bootstrap

```bash
git clone <repo-url> ActiveDecoy
cd ActiveDecoy
cp .env.example .env
./scripts/bootstrap.sh
```

Edit `.env`:

| Variable | Start with |
|----------|------------|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Your lab admin (change defaults for shared use) |
| `SESSION_SECRET` | Long random string |
| `NEO4J_PASSWORD` | Match compose default or your Neo4j install |
| `AGENT_INGEST_TOKEN` | Random token if testing ingest |
| `AD_HONEY_OU` | Your lab honey OU DN (can leave empty for plan-only) |

### 2. Start stack

```bash
docker compose up --build -d
# or: docker compose up -d neo4j && ./scripts/run.sh --reload
```

Open `http://127.0.0.1:8000` → sign in.

### 3. Smoke test

```bash
curl -s http://127.0.0.1:8000/api/health
python -m unittest discover -s tests -q
./scripts/demo_walkthrough.sh --check-only
```

### 4. UI walkthrough

Follow pages in order (matches [user guide](../data/user_guide.md)):

1. **Connection** — save LDAP profile (lab DC or mock)
2. **Visualization** — canvas + filters
3. **Deception** — deploy plan-only modules
4. **Monitoring** — simulate interaction
5. **Policy** — read playbooks and export links

## Repo tour

```
app/core/     Engines (deception, monitoring, policy, graph, LDAP)
app/api/      REST routers
washu_agent/  Monitoring forwarder CLI
tests/        124+ tests — run before every PR
docs/         Architecture, runbook, troubleshooting (you are here)
scripts/      bootstrap, demo, sample ingest
```

### Where to make changes

| Goal | Start here |
|------|------------|
| New API endpoint | `app/api/` + register in `app/main.py` |
| Deception logic | `app/core/deception_engine.py`, `deception_service.py` |
| AD writes | `app/core/ad_provisioner.py` |
| Telemetry | `app/core/monitoring_engine.py`, `washu_agent/` |
| UI | `app/templates/`, `app/static/` |
| Config | `app/core/config.py`, `.env.example` |

## Development workflow

```bash
. .venv/bin/activate
./scripts/run.sh --reload          # dev server
python -m unittest discover -s tests -v
```

Before opening a PR:

- All tests green
- Update docs if you change operator-facing behavior
- Never commit `.env` or `data/*.json` runtime files

## Optional deep dives

- **Neo4j:** `scripts/import_sample_graph.py`, `data/sample_graph.cypher`
- **Agent:** `washu_agent/.env.example`, `python -m washu_agent --help`
- **CI:** `.github/workflows/ci.yml`

## Team contacts

See [README.md](../README.md) collaborators list. For lab authorization questions, contact the lab owner — not the repo default credentials.

## Next steps

- Authorized lab: follow [RUNBOOK.md](RUNBOOK.md) end-to-end
- Stuck: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- API integration: [API.md](API.md) and `/docs` on a running instance
