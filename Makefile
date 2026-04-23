SHELL := /bin/bash

.PHONY: install dev db-up db-down backend frontend

install:
	./scripts/install.sh

dev:
	./scripts/dev.sh

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

backend:
	cd backend && ./venv/bin/python -m uvicorn kilo.server.app:app --host 0.0.0.0 --port 8080 --reload

frontend:
	cd frontend && npm run dev -- --host
