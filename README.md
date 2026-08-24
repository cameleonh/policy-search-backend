# policy-search-backend

Unified youth and small-business policy search platform.

This repository is a monorepo with TypeScript components managed by **pnpm
workspaces** and Python components managed by **uv workspaces**. The root
provides single commands for lint, typecheck, and test that run across all
components.

## Prerequisites

- **Node.js** 22 (see `.nvmrc`)
- **pnpm** 10+ (`corepack enable`)
- **Python** 3.12+ (see `.python-version`)
- **uv** 0.5+ (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Quick start

```bash
# Install all dependencies (TypeScript + Python)
pnpm install
uv sync

# Run all quality gates
pnpm lint        # ruff (py) + eslint (ts)
pnpm typecheck   # mypy (py) + tsc (ts)
pnpm test        # pytest (py) + vitest (ts)

# Production build (TypeScript only for now)
pnpm build
```

## Repository layout

```
policy-search-backend/
├── apps/
│   ├── web/                 Next.js + TypeScript web UI
│   └── api/                 FastAPI search and operations API
├── workers/
│   ├── ingest/              Weekly source ingestion (Python)
│   ├── document-extract/    Kordoc document conversion (Node.js)
│   └── normalize/           Policy / eligibility normalization (Python)
├── packages/
│   ├── contracts/           Shared TypeScript types (cross-service contracts)
│   ├── contracts-py/        Shared Python Pydantic models
│   └── matching/            Deterministic three-valued rule evaluator (Python)
├── db/
│   ├── base.py              SQLAlchemy declarative base
│   ├── enums.py             Shared Python enums (mirror DB CHECK constraints)
│   ├── models.py            SQLAlchemy ORM models (13 tables)
│   ├── migrations/          Alembic migrations
│   │   └── alembic/         env.py, script template, versions/
│   └── views/               PostgreSQL views (latest_policy_versions in migration)
├── tasks/
│   ├── prd-policy-search-platform.md
│   └── github-issue-plan.md
├── alembic.ini              Alembic configuration
├── .github/workflows/       CI pipelines
├── pnpm-workspace.yaml      TS workspace definition
├── pyproject.toml           Python workspace + tool config (ruff, mypy, pytest)
├── package.json             Root scripts and pnpm config
└── tsconfig.base.json       Shared TypeScript compiler options
```

## Dependency direction

```
packages/contracts ───────────────── ../policy-search-frontend (standalone repo)
                   └──────────────── workers/document-extract

packages/contracts-py ───────────── apps/api
                       └──────────── workers/ingest, workers/normalize

packages/matching  ──────────────── workers/normalize
                   └──────────────── apps/api

db/ (models, enums) ← consumed by apps/api, workers/ingest, workers/normalize
tasks/               ← documentation only, no runtime dependency
```

- `packages/*` are leaf libraries — they must not import from `apps/` or
  `workers/`.
- `apps/` and `workers/` may depend on `packages/*` but never on each other
  directly.
- Python packages communicate with Node.js workers via the shared JSON
  contracts in `packages/contracts`.

## Database

The platform uses PostgreSQL 16 with `pgcrypto`, `pg_trgm`, and `pgvector`
extensions.  All policy data is append-only — updates create new
`policy_version` rows, never `UPDATE` existing ones.

```bash
# Apply migrations
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/policy_search \
  uv run alembic upgrade head
```

The `latest_policy_versions` view returns the most recent valid version per
program.

## CI

GitHub Actions runs five parallel jobs on every PR and on `main` pushes:

1. **docs** — validates that `tasks/` markdown is present
2. **python** — `ruff check`, `ruff format --check`, `mypy`, `pytest`
3. **typescript** — `eslint`, `tsc --noEmit`
4. **build** — `vitest` + Next.js production build smoke
5. **migrations** — PostgreSQL service container with `alembic upgrade head` + migration integration tests

## Environment

Copy `.env.example` to `.env` and fill in values. The `.env` file is
git-ignored and must never contain real secrets in the repository.
