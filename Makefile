.PHONY: backend-install backend-test backend-lint backend-format frontend-install frontend-lint frontend-format frontend-build test lint format build

backend-install:
	python -m pip install -e "backend[dev]"

backend-test:
	python -m pytest backend/tests

backend-lint:
	ruff check backend/app backend/tests

backend-format:
	ruff format --check backend/app backend/tests

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

