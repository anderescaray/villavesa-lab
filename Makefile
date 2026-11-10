.PHONY: setup data test lint typecheck api web up

setup:        ## install python + web dependencies
	uv sync --all-groups
	cd web && npm ci

data:         ## download raw data and rebuild data/processed (reproducible)
	uv run --group data python scripts/build_data.py

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy

api:          ## run the API on :8000
	uv run uvicorn vlab_api.main:app --reload --port 8000

web:          ## run the web dev server on :3000
	cd web && npm run dev

up:
	docker compose up --build
