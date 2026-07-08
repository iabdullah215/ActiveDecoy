## Scripts

| Script | Purpose |
|--------|---------|
| `bootstrap.sh` | Create venv, install deps, copy `.env.example` → `.env` |
| `run.sh` | Start the FastAPI app via `main.py` |
| `import_sample_graph.py` | Load `data/sample_graph.cypher` into Neo4j |
| `forward_sample_events.py` | POST sample security events to `/api/monitoring/ingest` |

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
