#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — set NEO4J_PASSWORD before syncing graph data."
fi

python -c "from app.main import app; print('ActiveDecoy imports OK')"

echo ""
echo "Bootstrap complete."
echo ""
echo "Local Python:"
echo "  source .venv/bin/activate && python main.py --reload"
echo ""
echo "Or Docker Compose (app + Neo4j):"
echo "  docker compose up --build -d"
