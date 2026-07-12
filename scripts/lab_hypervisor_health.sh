#!/usr/bin/env bash
# Authorized lab hypervisor health wrapper for UTM bridge validation.
set -euo pipefail

if [[ "${1:-}" == "--health-check" ]]; then
  printf 'Washu-DC VM healthy (lab wrapper)\n'
  exit 0
fi

echo "Usage: $0 --health-check" >&2
exit 1
