#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] Missing required command: $1"
    exit 1
  fi
}

require_cmd python3
require_cmd npm
require_cmd docker

if ! docker compose version >/dev/null 2>&1; then
  echo "[ERROR] docker compose plugin is required (docker compose ...)"
  exit 1
fi

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "[INFO] Created backend/.env from backend/.env.example"
  echo "[INFO] Update API keys in backend/.env before using paid providers."
fi

if [ ! -f frontend/.env ]; then
  cp frontend/.env.example frontend/.env
  echo "[INFO] Created frontend/.env from frontend/.env.example"
fi

echo "[INFO] Starting PostgreSQL via Docker..."
docker compose up -d postgres

echo "[INFO] Waiting for PostgreSQL to be ready..."
for i in $(seq 1 60); do
  if docker compose exec -T postgres pg_isready -U wagi -d wagi >/dev/null 2>&1; then
    echo "[OK] PostgreSQL is ready."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "[ERROR] PostgreSQL did not become ready in time."
    exit 1
  fi
  sleep 1
done

if [ ! -d backend/venv ]; then
  echo "[INFO] Creating Python virtualenv (backend/venv)..."
  python3 -m venv backend/venv
fi

echo "[INFO] Installing backend Python dependencies..."
backend/venv/bin/python -m pip install --upgrade pip
backend/venv/bin/pip install -r backend/requirements.txt

echo "[INFO] Installing frontend npm dependencies..."
npm --prefix frontend ci

if [ -f backend/package.json ]; then
  echo "[INFO] Installing backend npm dependencies..."
  npm --prefix backend ci
fi

echo "[DONE] Setup completed successfully."
echo "[NEXT] Run: ./scripts/dev.sh"
