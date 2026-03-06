# Repository Guidelines

## Project Structure & Module Organization
- `backend/app/`: FastAPI backend code (`api/`, `services/`, `schemas/`, `models/`, `core/`, `db/`).
- `backend/tests/`: backend tests split into `unit/`, `integration/`, plus shared fixtures in `conftest.py`.
- `frontend/src/`: Next.js App Router UI (`app/`, `components/`, `lib/`).
- `docs/`: architecture and deployment docs (`v1_archive/` for legacy material).
- `data/` and `backend/data/`: runtime-generated storage (ignored by git).

## Build, Test, and Development Commands
- Backend dependency sync: `cd backend && uv sync --extra dev --extra local-sparse`
- Run backend locally: `cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Backend tests: `cd backend && uv run pytest`
- Backend coverage report: `cd backend && uv run pytest --cov=app --cov-report=term-missing`
- Backend lint/type-check: `cd backend && uv run ruff check . && uv run mypy app`
- Frontend install: `cd frontend && npm ci`
- Frontend dev server: `cd frontend && npm run dev`
- Frontend production check: `cd frontend && npm run build && npm run start`
- Frontend lint: `cd frontend && npm run lint`

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints on public interfaces, `snake_case` for modules/functions, `PascalCase` for classes.
- Python style is enforced with Ruff (`line-length = 100`) and MyPy (Python 3.10 settings in `pyproject.toml`).
- FastAPI handlers and service flows should remain async (`async`/`await`) to avoid blocking I/O.
- TypeScript is strict mode; prefer typed interfaces in `src/lib/api.ts`.
- Frontend component files use kebab-case (for example, `query-input.tsx`), while exported component names use `PascalCase`.

## Testing Guidelines
- Framework: `pytest` + `pytest-asyncio` (configured in `backend/pyproject.toml`).
- Naming: files `test_*.py`, test functions `test_*`.
- Put pure logic tests in `backend/tests/unit/`; API and workflow tests in `backend/tests/integration/`.
- No fixed coverage threshold is enforced; add/adjust tests for every behavior change and verify with `pytest --cov`.

## Commit & Pull Request Guidelines
- Follow commit prefixes seen in history: `feat:`, `fix:`, `refactor:`, `docs:`.
- Keep commits scoped to one logical change; avoid mixing unrelated backend/frontend edits.
- PRs should include: purpose, affected paths, test evidence (commands run), and screenshots for UI changes.
- Link related issues/tasks and call out any `.env` or deployment-impacting changes.

## Security & Configuration Tips
- Start from `backend/.env.example`; store secrets in local `.env` only.
- Never commit API keys, `.env` files, `node_modules/`, `.next/`, or runtime data directories.
