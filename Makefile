.PHONY: setup infra-up infra-down test lint proof-of-life governor banker world farmer chef lumberjack

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

proof-of-life:
	.venv/bin/python scripts/proof_of_life.py

governor:
	.venv/bin/python -m services.governor

banker:
	.venv/bin/python -m services.banker

world:
	.venv/bin/python -m services.world

farmer:
	.venv/bin/python -m agents.farmer

chef:
	.venv/bin/python -m agents.chef

lumberjack:
	cd agents/lumberjack && npx tsx src/index.ts
