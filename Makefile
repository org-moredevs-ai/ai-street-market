.PHONY: setup infra-up infra-down test lint run-season run-season-fast

setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"

infra-up:
	docker compose -f infrastructure/docker-compose.yml up -d

infra-down:
	docker compose -f infrastructure/docker-compose.yml down

test:
	.venv/bin/pytest tests/ -v

lint:
	.venv/bin/ruff check .
	.venv/bin/mypy libs/streetmarket

run-season:
	.venv/bin/python scripts/run_season.py

run-season-fast:
	.venv/bin/python scripts/run_season.py --tick-override 2
