## Scripts

| Script | Purpose |
|--------|---------|
| `bootstrap.sh` | Create venv, install deps, copy `.env.example` → `.env` |
| `run.sh` | Start the FastAPI app via `main.py` |
| `import_sample_graph.py` | Load `data/sample_graph.cypher` into Neo4j |
| `forward_sample_events.py` | POST sample security events to `/api/monitoring/ingest` |
| `demo_walkthrough.sh` | Narrated API demo for presentations (login → deploy → simulate) |

## Washu Agent

```bash
python -m washu_agent check
python -m washu_agent heartbeat --token "$AGENT_INGEST_TOKEN"
python -m washu_agent run --source demo --token "$AGENT_INGEST_TOKEN"
```

See `washu_agent/.env.example` and SETUP.md § Washu Agent.

## Docker

From the repo root:

```bash
cp .env.example .env   # first time
docker compose up --build -d
docker compose logs -f app
docker compose down
```

Neo4j Browser: `http://127.0.0.1:7474`  
ActiveDecoy console: `http://127.0.0.1:8000`
