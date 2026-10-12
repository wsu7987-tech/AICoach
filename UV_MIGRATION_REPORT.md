# UV Migration Report

Date: 2026-10-12 (Asia/Tokyo)

Scope: migrate the backend dependency workflow from pip to uv while keeping the
existing backend layout, `pyproject.toml` dependency ranges, ORM, Alembic
migrations, Bootstrap, and business code unchanged.

## Baseline

- Python: 3.13.12 (`D:\software\python\python.exe`)
- pip: 25.3
- uv: 0.11.1
- The pre-migration interpreter was a shared global environment. It contained
  the editable backend package plus unrelated packages, so it was not a
  reproducible project environment.
- `backend/pyproject.toml` requires Python `>=3.12`.
- The only development dependency declaration is the existing optional extra
  `[project.optional-dependencies].dev`; there are no dependency groups.
- The seven runtime dependencies and four dev dependencies in `pyproject.toml`
  were not changed.

## Migration changes

- Generated and committed `backend/uv.lock` with 40 resolved packages.
- Created and synchronized the independent `backend/.venv` with
  `uv sync --extra dev`.
- Added `.venv/` to the root `.gitignore`.
- Updated the backend Makefile targets and README commands to use `uv sync` and
  `uv run`.
- Verified that `backend/.venv`, `.tmp-task002-mysql`, `.env`, and
  `backend/.env` are ignored and are not staged.
- No ORM, Alembic migration, Bootstrap, or business source file was changed.

## Direct dependency resolution

The lock was created from the existing version ranges, without a dependency
upgrade command or a pyproject dependency edit. Since there was no previous
lockfile, uv selected the current compatible candidates. The relevant direct
versions were:

| Package | Pre-migration shared pip env | uv.lock / backend/.venv |
|---|---:|---:|
| SQLAlchemy | 2.0.48 | 2.0.54 |
| alembic | 1.20.0 | 1.20.0 |
| asyncmy | 0.2.16 | 0.2.16 |
| greenlet | 3.3.2 | 3.5.6 |
| fastapi | 0.135.2 | 0.143.0 |
| pydantic | 2.12.5 | 2.14.1 |
| pydantic-settings | 2.13.1 | 2.15.0 |
| uvicorn | 0.42.0 | 0.54.0 |
| pytest | 8.4.2 | 8.4.2 |
| pytest-cov | 6.3.0 | 6.3.0 |
| httpx | 0.28.1 | 0.28.1 |
| ruff | 0.15.8 | 0.17.0 |

These differences are a lockfile-resolution consequence of starting without a
previous lockfile, not an intentional bulk upgrade. They remain within the
existing pyproject constraints. If exact pre-migration versions are required,
that should be handled as a separately reviewed dependency-pinning task.

## Commands executed and results

```text
uv lock
  Resolved 40 packages

cd backend
uv sync --extra dev
  Created backend/.venv and installed 39 packages

uv sync --locked --extra dev
  Passed; lockfile unchanged

$env:UV_PROJECT_ENVIRONMENT = 'D:\akae\AICoach\.tmp\uv-clean-venv'
uv sync --locked --extra dev --project backend
uv run --locked --project backend --extra dev python -c "import fastapi, uvicorn; ..."
  Passed in a fresh environment; FastAPI 0.143.0, Uvicorn 0.54.0

uv run --project backend ruff check backend/app backend/tests
  Passed
uv run --project backend ruff format --check backend/app backend/tests
  Passed (29 files formatted)
cd backend
uv run ruff check .
uv run ruff format --check .
  Passed (32 files formatted)

uv run --project backend pytest backend/tests -q -rs
  13 passed, 2 skipped because MYSQL_TEST_DATABASE_URL was intentionally unset

$env:MYSQL_TEST_DATABASE_URL =
  'mysql+asyncmy://root@127.0.0.1:33329/ai_coach_task002_test_uv'
uv run --project backend pytest backend/tests -q -rA
  15 passed, 0 skipped

$env:DATABASE_URL =
  'mysql+asyncmy://root@127.0.0.1:33329/ai_coach_task002_test_uv'
cd backend
uv run python -m alembic -c alembic.ini check
  No new upgrade operations detected

uv run --project backend uvicorn app.main:app --app-dir backend
  Process started successfully; GET /health returned HTTP 200 and {"status":"ok"}
  GET /ready returned HTTP 503 because the application DATABASE_URL was not configured;
  this is the expected readiness contract for that probe environment.
```

The MySQL run used the existing isolated MySQL Community Server 8.0.32 on
`127.0.0.1:33329` and a database named `ai_coach_task002_test_uv`. It did not
use a production database. The temporary instance and database are stopped or
removed after verification.

## Risks and follow-up

- The migration was verified on Python 3.13.12. The declared lower bound is
  Python 3.12, but this task did not add a second interpreter matrix.
- The lock records the compatible versions available at migration time. Future
  dependency changes must be made through a reviewed lock update rather than an
  ad-hoc install.
- A pre-existing Starlette warning reports that the installed TestClient path
  will prefer `httpx2` in a future compatibility change; it does not fail the
  current tests and is outside this package-manager migration.
- TASK-101 was not started.
