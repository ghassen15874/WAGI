# WAGI Platform

WAGI is an AI website/app builder with:
- React + Vite frontend (`frontend`)
- FastAPI backend (`backend`)
- PostgreSQL database

This repo is prepared for:
- local development
- cloning and running on another PC
- clean GitHub push (without local logs, sandbox files, or secrets)

## 1) Prerequisites (new PC)
Install these first:
- `git`
- `docker` + `docker compose`
- `python3` (3.10+ recommended)
- `node` (18+ recommended)
- `npm`

## 2) Clone And Install (new PC)
```bash
git clone <YOUR_REPO_URL>
cd <repo-folder>
./scripts/install.sh
```

What `./scripts/install.sh` does:
- starts PostgreSQL via Docker
- creates `backend/.env` from `backend/.env.example` (if missing)
- creates `frontend/.env` from `frontend/.env.example` (if missing)
- creates backend virtualenv (`backend/venv`)
- installs backend Python dependencies
- installs frontend dependencies
- installs backend npm dependencies (playwright package)

## 3) Run Dev Stack
```bash
./scripts/dev.sh
```

App URLs:
- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8080`
- API docs: `http://localhost:8080/docs`

## 4) Database Notes
- PostgreSQL runs from `docker-compose.yml` as service `postgres`.
- Default DB URL is:
  - `postgresql://wagi:wagi123@localhost:5433/wagi`
- Backend auto-creates/migrates required tables on startup.

## 5) Environment Setup
Before production use, edit:
- `backend/.env`

At minimum set:
- provider keys (`GROQ_API_KEY`, `OPENAI_API_KEY`, etc.)
- auth secrets (`JWT_SECRET`, `SESSION_SECRET`)
- GitHub OAuth keys (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`) if using GitHub login

## 6) Helpful Commands
```bash
# Setup (same as install script)
make install

# Run full dev stack
make dev

# DB only
make db-up
make db-down
```

## 7) Push To GitHub
This repo includes a `.gitignore` that excludes:
- `backend/.env`
- local logs
- `backend/sandbox`
- `node_modules`
- build artifacts

Push steps:
```bash
git add .
git commit -m "Prepare WAGI for cross-PC setup and deployment"
git push origin main
```

## 8) First-Time GitHub Deploy Checklist
- Ensure no secrets in commit history.
- Keep `.env` out of git (already ignored).
- Verify app starts using only `./scripts/install.sh` + `./scripts/dev.sh` on a fresh machine.
