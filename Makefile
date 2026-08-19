# CoolRx — developer and judge entry points.
#
# The one that matters is `make demo`: AC-13 requires a clean clone to run the
# full pipeline with no FORTYGUARD_API_KEY set. That works because the recorded
# fixtures in backend/data/fixtures are committed, so FIXTURE_MODE=true resolves
# every call from disk and never opens a socket to FortyGuard.
#
# Windows note: these recipes assume a POSIX shell (Git Bash, WSL). The
# underlying commands are plain docker/python/npm if you prefer to run them
# directly.

SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker-compose.yml
PY := backend/.venv/Scripts/python.exe          # Windows venv layout
ifeq (,$(wildcard backend/.venv/Scripts/python.exe))
PY := backend/.venv/bin/python                  # POSIX venv layout
endif

.DEFAULT_GOAL := help
.PHONY: help demo demo-down setup services migrate api worker web test test-fast lint fixtures fixtures-plan train check

help:  ## Show the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── The judge path ───────────────────────────────────────────────────────────

demo: ## Run the whole stack offline from committed fixtures — no API key needed
	@echo "──> CoolRx demo · fixture mode · no FortyGuard key required"
	@test -n "$$(ls backend/data/fixtures/*.json 2>/dev/null)" \
		|| { echo "ERROR: no fixtures committed. Run 'make fixtures' with a key."; exit 1; }
	@echo "──> $$(ls backend/data/fixtures/*.json | wc -l) recorded responses found"
	FIXTURE_MODE=true FIXTURE_STRICT=true $(COMPOSE) up -d --build
	@echo
	@echo "    API   http://localhost:8000/api/health"
	@echo "    Docs  http://localhost:8000/docs"
	@echo "    Web   http://localhost:3000   (run 'make web' if not containerised)"
	@echo
	@echo "    Districts available offline: phoenix"
	@echo "    lasvegas and tucson need 'make fixtures DISTRICT=<name>' with a key."

demo-down: ## Stop the demo stack and drop its volumes
	$(COMPOSE) down -v

# ── Setup ────────────────────────────────────────────────────────────────────

setup: ## Create backend/.venv and install the backend with dev extras
	python -m venv backend/.venv
	cd backend && .venv/Scripts/python.exe -m pip install -q --upgrade pip && \
		.venv/Scripts/python.exe -m pip install -e ".[dev]"
	cd frontend && npm ci

services: ## Start only Postgres and Redis (what the service-dependent tests need)
	$(COMPOSE) up -d db redis

migrate: ## Apply database migrations
	cd backend && ../$(PY) -m alembic upgrade head

api: ## Run the API locally against the compose services
	cd backend && ../$(PY) -m uvicorn main:app --reload --port 8000

worker: ## Run the RQ worker locally
	cd backend && ../$(PY) -m rq worker coolrx

web: ## Run the Next.js frontend
	cd frontend && npm run dev

# ── Verification ─────────────────────────────────────────────────────────────

test: ## Full backend suite. Never touches the network; conftest pins fixture mode
	cd backend && ../$(PY) -m pytest -q

test-fast: ## Backend suite minus the service-dependent modules
	cd backend && ../$(PY) -m pytest -q \
		--ignore=tests/test_health.py \
		--ignore=tests/test_job_progress.py \
		--ignore=tests/test_aoi_routes.py

lint: ## Ruff + mypy on the backend, tsc on the frontend
	cd backend && ../$(PY) -m ruff check . && ../$(PY) -m mypy .
	cd frontend && npx tsc --noEmit

check: test lint ## Everything CI runs

# ── Data ─────────────────────────────────────────────────────────────────────

DISTRICT ?= phoenix

fixtures-plan: ## Show what a harvest would cost, without spending anything
	cd backend && FIXTURE_MODE=false ../$(PY) -m scripts.harvest_fixtures \
		--district $(DISTRICT) --dry-run

fixtures: ## Record real responses for DISTRICT — SPENDS CREDITS, needs a key
	@echo "──> harvesting '$(DISTRICT)' — 14 live calls, one-off"
	cd backend && FIXTURE_MODE=false ../$(PY) -m scripts.harvest_fixtures \
		--district $(DISTRICT)

train: ## Train the temperature model from committed fixtures
	cd backend && ../$(PY) -m scripts.train_model
