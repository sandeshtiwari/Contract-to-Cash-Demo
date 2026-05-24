#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi

cleanup() {
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

cd "$ROOT/backend"
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8017 &
BACKEND_PID=$!

cd "$ROOT/frontend"
npm run dev
