.PHONY: backend-install backend-test backend-lint backend-format backend-bootstrap frontend-install frontend-lint frontend-format frontend-build test lint format build

backend-install:
	uv sync --project backend --extra dev

backend-test:
	uv run --project backend pytest backend/tests

backend-lint:
	uv run --project backend ruff check backend/app backend/tests

backend-format:
	uv run --project backend ruff format --check backend/app backend/tests

backend-bootstrap:
	cd backend && uv run python -m app.bootstrap.cli --file ../bootstrap/initial-config.v1.json

frontend-install:
	cd frontend && npm install

frontend-lint:
	cd frontend && npm run lint

frontend-format:
	cd frontend && npm run format

frontend-build:
	cd frontend && npm run build

test: backend-test

lint: backend-lint frontend-lint

format: backend-format frontend-format

build: frontend-build

