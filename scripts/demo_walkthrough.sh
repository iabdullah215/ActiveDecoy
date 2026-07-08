#!/usr/bin/env bash
# ActiveDecoy lab demo walkthrough — API-driven corridor script.
#
# Usage:
#   ./scripts/demo_walkthrough.sh              # full narrated demo (console must be up)
#   ./scripts/demo_walkthrough.sh --check-only # health check only
#   BASE_URL=http://host:8000 ./scripts/demo_walkthrough.sh
#
# Env: ADMIN_USERNAME, ADMIN_PASSWORD (defaults match lab .env.example)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ADMIN_USER="${ADMIN_USERNAME:-HwatSauce}"
ADMIN_PASS="${ADMIN_PASSWORD:-Active-Decoy!2026}"
CHECK_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --check-only) CHECK_ONLY=true ;;
    -h|--help)
      echo "Usage: $0 [--check-only]"
      exit 0
      ;;
  esac
done

COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

say() {
  printf '\n\033[1;36m▶ %s\033[0m\n' "$1"
}

step() {
  printf '  • %s\n' "$1"
}

require_curl() {
  command -v curl >/dev/null 2>&1 || {
    echo "curl is required" >&2
    exit 1
  }
}

api_get() {
  curl -fsS -b "$COOKIE_JAR" -c "$COOKIE_JAR" "${BASE_URL}$1"
}

api_post_form() {
  curl -fsS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST "${BASE_URL}$1" "${@:2}"
}

require_curl

say "ActiveDecoy demo — ${BASE_URL}"

say "1. Health check"
HEALTH="$(curl -fsS "${BASE_URL}/api/health")"
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
step "Console is reachable"

if [[ "$CHECK_ONLY" == true ]]; then
  say "Check-only mode — done."
  exit 0
fi

say "2. Operator login"
api_post_form /login \
  -d "username=${ADMIN_USER}" \
  -d "password=${ADMIN_PASS}" \
  -o /dev/null -w '' || {
  echo "Login failed — check ADMIN_USERNAME/ADMIN_PASSWORD and that the app is running." >&2
  exit 1
}
step "Session established"

say "3. Save lab connection profile"
api_post_form /api/connection/save \
  -d "ldap_host=dc01.lab.local" \
  -d "ldap_port=389" \
  -d "ldap_use_ssl=false" \
  -d "ldap_bind_dn=CN=admin,DC=lab,DC=local" \
  -d "ldap_password=demo" \
  -d "ldap_base_dn=DC=lab,DC=local" \
  -d "hypervisor_type=vmware" \
  -d "hypervisor_vm_name=Washu-DC" \
  -d "auto_test_on_load=false" >/dev/null
step "LDAP profile saved (password in server secret store)"

say "4. Deploy deception plan (graph/plan only)"
DEPLOY="$(api_post_form /api/deception/deploy \
  -d "modules=honey_users" \
  -d "modules=honey_servers" \
  -d "sync_to_graph=false" \
  -d "provision_ad=false" \
  -d "dry_run=false")"
OBJECT_COUNT="$(echo "$DEPLOY" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('objects',[])))")"
POLICY_SCORE="$(echo "$DEPLOY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('policy',{}).get('score','?'))")"
step "Deployed ${OBJECT_COUNT} honey objects (policy score: ${POLICY_SCORE})"

say "5. Simulate honey interaction"
SIM="$(api_post_form /api/monitoring/simulate -d "count=2")"
EVENTS="$(echo "$SIM" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('events',[])))")"
step "Generated ${EVENTS} correlated event(s)"

say "6. Policy export (honey alerts)"
EXPORT="$(api_get '/api/policy/export?format=json&honey_only=true&exclude_baseline=true&limit=10')"
COUNT="$(echo "$EXPORT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))")"
step "Export bundle contains ${COUNT} event(s)"

say "7. Presenter notes"
step "Open ${BASE_URL}/monitoring — enable Live stream + Hide baseline noise"
step "Open ${BASE_URL}/visualization — show honey topology"
step "Open ${BASE_URL}/policy — walk deny-logon checklist and playbooks"
step "Optional: python -m washu_agent run --source demo (with AGENT_INGEST_TOKEN set)"

say "Demo API path complete ✓"
echo ""
echo "Narration arc: Connect → Deploy decoys → Adversary touches honey → High-confidence alert → Playbook → Export"
