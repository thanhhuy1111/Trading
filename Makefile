.PHONY: help infra-up infra-down dev-api dev-dashboard test lint typecheck migrate seed

help:
	@echo "Multi-Agent Trading Platform Operational Commands:"
	@echo "  make infra-minimal  - Start Minimal Profile (PostgreSQL + Redis)"
	@echo "  make infra-full     - Start Full Profile (PostgreSQL + Redis + ClickHouse + Redpanda)"
	@echo "  make infra-down     - Stop infrastructure containers"
	@echo "  make dev-api        - Run FastAPI backend service"
	@echo "  make dev-dashboard  - Run React dashboard"
	@echo "  make test           - Run pytest suite"
	@echo "  make lint           - Run ruff linter"
	@echo "  make typecheck      - Run mypy type checker"
	@echo "  make migrate        - Run Alembic database migrations"

infra-minimal:
	docker-compose --profile minimal up -d postgres redis

infra-full:
	docker-compose --profile full up -d

infra-down:
	docker-compose down

dev-api:
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

dev-dashboard:
	cd apps/dashboard && npm run dev

test:
	pytest tests/ -v

lint:
	ruff check .

typecheck:
	mypy services apps packages

migrate:
	alembic upgrade head
