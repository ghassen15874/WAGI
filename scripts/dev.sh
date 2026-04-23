#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -x backend/venv/bin/python ]; then
  echo "[ERROR] Backend virtualenv is missing. Run ./scripts/install.sh first."
  exit 1
fi

port_in_use() {
  local port="$1"
  ss -ltn "( sport = :$port )" 2>/dev/null | tail -n +2 | grep -q .
}

if port_in_use 8080; then
  echo "[ERROR] Port 8080 is already in use. Stop the existing backend first."
  echo "        Tip: lsof -i :8080"
  exit 1
fi

if port_in_use 5173; then
  echo "[ERROR] Port 5173 is already in use. Stop the existing frontend first."
  echo "        Tip: lsof -i :5173"
  exit 1
fi

echo "[INFO] Ensuring PostgreSQL is running..."
docker compose up -d postgres >/dev/null

cleanup() {
  echo
  echo "[INFO] Stopping dev processes..."
  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

echo "[INFO] Starting backend on http://localhost:8080 ..."
(
  cd backend
  ./venv/bin/python -m uvicorn kilo.server.app:app --host 0.0.0.0 --port 8080 --reload
) &
BACKEND_PID=$!

echo "[INFO] Starting frontend on http://localhost:5173 ..."
(
  cd frontend
  npm run dev -- --host
) &
FRONTEND_PID=$!

echo "[OK] Dev stack started. Press Ctrl+C to stop both."
wait -n "$BACKEND_PID" "$FRONTEND_PID"
