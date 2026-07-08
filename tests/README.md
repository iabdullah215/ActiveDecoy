# ActiveDecoy test suite

Run locally:

```bash
. .venv/bin/activate
python -m unittest discover -s tests -v
```

## Layout

| Module | Focus |
|--------|--------|
| `test_config.py` | Settings validation / secure defaults |
| `test_connection.py` | Profiles, bridge checklist, connection API |
| `test_directory.py` | Directory snapshot + import service |
| `test_deception_engine.py` | Deception planning + Cypher generation |
| `test_provisioning.py` | AD provisioner safety, deploy service, history |
| `test_graph_store.py` | Neo4j wrapper with fake driver (no live DB) |
| `test_ldap.py` | LDAP bind/enumerate/provision paths (mocked ldap3) |
| `test_monitoring.py` | Monitoring engine + console API |
| `test_ingest.py` | Telemetry ingest, SSE, persistence |
| `test_agent.py` | Washu Agent registry + package |
| `test_policy.py` | ITDR policy, playbooks, export |
| `test_security.py` | Rate limit, secrets, audit |
| `test_visualization.py` | Graph view helpers + topology API |
| `test_e2e.py` | API workflow + concurrency |
| `test_docs.py` | Documentation files + OpenAPI metadata |

No live Neo4j, LDAP, or AD is required for CI.
