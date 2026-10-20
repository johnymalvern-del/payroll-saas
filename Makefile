.PHONY: help up down logs build migrate migrate-control seed test lint format format-check precommit-install

help:
@echo "Targets:"
@echo "  up                Build and start all services"
@echo "  down              Stop all services"
@echo "  logs              Tail logs"
@echo "  build             Rebuild images"
@echo "  migrate           Run control DB migrations"
@echo "  migrate-control   Run control DB migrations only"
@echo "  seed              Seed control DB (ZA country profile template)"
@echo "  test              Run backend test suite"
@echo "  lint              Run ruff + mypy"
@echo "  format            Run ruff format"
@echo "  precommit-install Install git pre-commit hook"

up:
docker compose up -d --build

down:
docker compose down

logs:
docker compose logs -f --tail=200

build:
docker compose build

migrate: migrate-control

migrate-control:
docker compose run --rm api alembic -c /app/alembic.ini -n control upgrade head

seed:
docker compose run --rm api python -m app.scripts.seed

test:
docker compose run --rm api pytest -q

lint:
docker compose run --rm api ruff check app tests
docker compose run --rm api mypy app

format:
docker compose run --rm api ruff format app tests

format-check:
docker compose run --rm api ruff format --check app tests

precommit-install:
pre-commit install