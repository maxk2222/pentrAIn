# pentrAIn — common dev + ops targets.
.DEFAULT_GOAL := help
COMPOSE := docker compose -f engine/docker-compose.yml
PYTEST  := backend/.venv/bin/python -m pytest

.PHONY: help dev build up down logs doctor test test-backend test-coach lint-packs sync-packs \
        frontend-dev backend-dev coach-dev clean

help: ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------- dev (local, mock engine) ----------
dev: ## run backend+coach locally with MockProvider (no Proxmox needed)
	PENTRAIN_ENGINE_MODE=mock backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend &
	PENTRAIN_BACKEND_URL=http://localhost:8000 \
	PENTRAIN_BACKEND_WS_URL=ws://localhost:8000/ws/coach \
	  coach/.venv/bin/python -m coach.main &
	cd frontend && npm run dev

frontend-dev:
	cd frontend && npm run dev

backend-dev:
	PENTRAIN_ENGINE_MODE=mock backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend

coach-dev:
	PENTRAIN_BACKEND_URL=http://localhost:8000 \
	PENTRAIN_BACKEND_WS_URL=ws://localhost:8000/ws/coach \
	  coach/.venv/bin/python -m coach.main

# ---------- docker ----------
engine/.env: ## bootstrap env file from example (generated secrets are dev values)
	@cp engine/.env.example engine/.env && \
	  echo "created engine/.env — set PENTRAIN_APP_SECRET + PENTRAIN_COACH_SERVICE_TOKEN for production"

build: engine/.env ## build all images
	$(COMPOSE) build

up: engine/.env ## start the platform
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

# ---------- checks ----------
doctor: ## full environment diagnostic
	cli/pentrain doctor

test: test-backend test-coach lint-packs ## run all tests
	@echo "all green"

test-backend:
	cd backend && .venv/bin/python -m pytest -q

test-coach:
	cd coach && .venv/bin/python -m pytest -q

lint-packs:
	backend/.venv/bin/python scripts/lint_packs.py content/packs

sync-packs: ## reload quest packs into a running backend
	curl -fsS -X POST http://localhost:8000/api/packs/sync || echo "(needs auth token — use the web UI)"

clean:
	rm -rf frontend/dist frontend/node_modules backend/.venv coach/.venv
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
