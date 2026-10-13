# UV Migration Independent Review

Date: 2026-10-12 (Asia/Tokyo)  
Scope: acceptance of commit `1f86b329763ea38583ec5a0ca5c268d5dd8a500a` only. TASK-101 was not started and no application, ORM, Alembic, Bootstrap, or business code was modified by this review.

## Final decision

**PASS — TASK-101 may begin.**

The locked environment was independently rebuilt rather than reusing the old pip environment. The complete test suite passed against a newly initialized, isolated MySQL Community Server 8.0.32 database. There are no P0 or P1 findings. The two P2 follow-ups below do not invalidate reproducibility or the TASK-001/TASK-002 regression gate.

## Git commit and worktree

| Check | Result |
| --- | --- |
| Branch / HEAD | `main` / `1f86b329763ea38583ec5a0ca5c268d5dd8a500a` |
| Commit subject | `build: migrate backend dependencies to uv` |
| Pre-review worktree | Clean |
| Migration diff | `.gitignore`, `Makefile`, `PROJECT_STATUS.md`, `README.md`, `UV_MIGRATION_REPORT.md`, and new `backend/uv.lock` only (1,346 additions / 10 deletions) |
| Diff integrity | `git diff --check 0af9d86 1f86b32` passed |
| Business-code boundary | `git diff 0af9d86 1f86b32 -- backend/pyproject.toml backend/app backend/alembic bootstrap` was empty |

The review report itself is the only intended new worktree artifact after this review.

## Dependency and lockfile review

- `backend/pyproject.toml` is byte-for-byte unchanged from the parent commit.
- It declares Python `>=3.12`; `backend/uv.lock` also records `requires-python = ">=3.12"`.
- `uv lock --project backend --check` passed. The lock contains the editable project, eight runtime dependencies, four `dev` extra dependencies, and their transitive closure (40 resolved package records / 39 installed distributions in the clean environment).
- The lockfile root metadata exactly mirrors all project requirements and their version bounds. No direct dependency was added or removed.
- The project intentionally uses `[project.optional-dependencies].dev`; it has no PEP 735 dependency groups. `uv sync --extra dev` is therefore the correct install form. Review commands explicitly selected this extra.

There was no pre-migration lockfile. The migration therefore selected current versions still within the unchanged declared bounds (for example FastAPI `0.135.2 -> 0.143.0`, SQLAlchemy `2.0.48 -> 2.0.54`, Pydantic `2.12.5 -> 2.14.1`, Uvicorn `0.42.0 -> 0.54.0`, and Ruff `0.15.8 -> 0.17.0` when compared with the former shared pip environment). This is a resolution effect, not a declaration change or an undeclared dependency deletion. It is covered by the clean-install and regression results below; future changes must update `uv.lock` under review.

## Clean installation and runtime checks

Two new virtual environments under the OS temporary directory were used. They were selected with `UV_PROJECT_ENVIRONMENT`; neither reused `backend/.venv` nor the former pip environment.

| Command / environment | Result |
| --- | --- |
| `uv sync --project backend --locked --extra dev` (CPython 3.13.12) | PASS; 39 distributions installed from the committed lock |
| `uv run --project backend --locked --extra dev python -c "import fastapi, uvicorn, sqlalchemy, alembic"` | PASS; FastAPI `0.143.0`, Uvicorn `0.54.0`, SQLAlchemy `2.0.54`, Alembic `1.20.0` |
| `uv run --project backend --locked --extra dev ruff check backend/app backend/tests` | PASS |
| `uv run --project backend --locked --extra dev ruff format --check backend/app backend/tests` | PASS; 29 files already formatted |
| `uv sync --project backend --locked --extra dev --python 3.12` (CPython 3.12.13) | PASS; validates the declared lower Python bound |
| Python 3.12 import + TASK-001/TASK-002 non-DB tests | PASS; 13 passed, 0 failed, 0 skipped |
| Python 3.12 Ruff check | PASS |

## Test results

| Command | PASS | FAIL | SKIP | Notes |
| --- | ---: | ---: | ---: | --- |
| `uv run --project backend --locked --extra dev pytest backend/tests -q -rs` without `MYSQL_TEST_DATABASE_URL` | 13 | 0 | 2 | Expected safety skips only; not used as the DB acceptance result |
| Same command with isolated `MYSQL_TEST_DATABASE_URL` | 15 | 0 | 0 | Includes TASK-001 and TASK-002 MySQL integration coverage |
| `cd backend; uv run --locked --extra dev python -m alembic -c alembic.ini check` with the same isolated DB | n/a | 0 | n/a | PASS: `No new upgrade operations detected` |

The real database run used a fresh MySQL Community Server **8.0.32** data directory at an ignored local temporary path, bound only to `127.0.0.1:33331`, and database `ai_coach_task002_test_uv_review`. The test itself enforces the `ai_coach_task002_test_*` name before destructive migration operations. It did not use the local shared MySQL listener, any company test database, or a production database. The temporary server was stopped after the run.

## Tooling, docs, and secret hygiene

- `README.md` and `Makefile` use `uv sync` / `uv run`; no active pip, `requirements.txt`, virtualenv, or Poetry workflow remains in the checked development commands.
- No repository CI workflow, Docker Compose file, Dockerfile, or Kubernetes deployment script currently exists to retain a legacy pip command. The deployment design document contains no executable pip workflow.
- `.gitignore` excludes `.env`, `backend/.env`, root `.venv/`, `backend/.pytest_cache/`, `backend/.ruff_cache/`, and `.tmp-task002-mysql`. `git check-ignore` confirmed these rules; Git tracks none of the checked environment files. The review-created database directory is ignored (`!! .tmp-task002-mysql/`), not staged.
- No Authorization value, API key, database password, or other secret was written to Git during this review.

## Dependency risk and findings

### P0

None.

### P1

None.

### P2

1. **Everyday commands do not enforce the lock.** `README.md` and the Makefile's install/run targets use `uv sync` / `uv run` without `--locked`; they are correct for the committed lock today, but a future metadata edit could refresh the lock during local work rather than fail immediately. Minimal follow-up: change the documented and Makefile verification commands to `uv sync --locked --extra dev` and `uv run --locked --extra dev ...`.

2. **A third-party deprecation warning is present.** Current tests emit the FastAPI/Starlette `TestClient` warning about a future `httpx2` preference. It is not a test failure or an uv migration regression. Track it when the FastAPI/TestClient dependency line is next intentionally updated; do not add `httpx2` as an unreviewed migration-side dependency.

## Completion boundary

This review stops after acceptance. No TASK-101 implementation, no source-code fix, and no unrelated refactor was performed.

