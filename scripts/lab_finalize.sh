#!/usr/bin/env bash
# Bootstrap the authorized lab stack, establish connectors, self-test, and capture screenshots.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

if ! grep -q '^AGENT_INGEST_TOKEN=.\+' .env; then
  TOKEN="$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")"
  if grep -q '^AGENT_INGEST_TOKEN=' .env; then
    sed -i "s|^AGENT_INGEST_TOKEN=.*|AGENT_INGEST_TOKEN=${TOKEN}|" .env
  else
    echo "AGENT_INGEST_TOKEN=${TOKEN}" >> .env
  fi
fi

# Lab connector defaults (safe for authorized local testing only)
apply_lab_env() {
  for kv in \
    "LDAP_HOST=dc01.lab.local" \
    "LDAP_PORT=389" \
    "LDAP_BIND_DN=cn=admin,dc=lab,dc=local" \
    "LDAP_PASSWORD=change-me-ldap" \
    "LDAP_BASE_DN=dc=lab,dc=local" \
    "LDAP_LAB_MODE=true" \
    "HYPERVISOR_TYPE=utm" \
    "HYPERVISOR_VM_NAME=Washu-DC" \
    "HYPERVISOR_WRAPPER_COMMAND=/app/scripts/lab_hypervisor_health.sh" \
    "AD_HONEY_OU=OU=Honey,OU=Lab,DC=lab,DC=local" \
    "AD_MONITORED_DOMAINS=lab.local"
  do
    key="${kv%%=*}"
    val="${kv#*=}"
    if grep -q "^${key}=" .env; then
      sed -i "s|^${key}=.*|${key}=${val}|" .env
    else
      echo "${key}=${val}" >> .env
    fi
  done
}

apply_lab_env

say "Starting lab stack (Neo4j + app + lab LDAP)"
docker compose -f docker-compose.yml -f docker-compose.lab.yml up --build -d

say "Waiting for health endpoint"
for _ in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:8000/api/health | python3 -m json.tool

say "Running unit tests"
source .venv/bin/activate 2>/dev/null || ./scripts/bootstrap.sh
python -m unittest discover -s tests -q

say "Running lab self-test (connectors + full workflow)"
python scripts/lab_self_test.py

say "Capturing connected-state UI screenshots"
python scripts/capture_screenshots.py --connected

say "Lab finalize complete"
echo "Screenshots: $ROOT/screenshots/connected/"
