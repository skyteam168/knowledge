COMPOSE := docker compose -f deploy/docker-compose.yml
INFRA := postgres redis minio qdrant opensearch keycloak mock-llm

.PHONY: install up down dev dev-infra dev-backend dev-worker dev-frontend migrate test test-backend test-acl test-frontend lint lint-backend lint-frontend format

install:
	cd backend && uv sync
	cd frontend && npm install

up:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

dev-infra:
	$(COMPOSE) up -d --build --wait $(INFRA)

dev: dev-infra migrate
	$(MAKE) -j3 dev-backend dev-worker dev-frontend

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-worker:
	cd backend && uv run dramatiq app.workers.main --processes 1 --threads 2 --watch app

dev-frontend:
	cd frontend && npm run dev

migrate:
	cd backend && uv run alembic upgrade head

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest

test-acl:
	cd backend && uv run pytest -m acl

test-frontend:
	cd frontend && npm run test

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

lint-frontend:
	cd frontend && npm run lint && npm run type-check

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run lint:fix
