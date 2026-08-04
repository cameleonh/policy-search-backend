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
│   └── matching/            Deterministic three-valued rule evaluator (Python)
├── db/
│   ├── migrations/          PostgreSQL migrations
│   └── views/               PostgreSQL views
├── tasks/
│   ├── prd-policy-search-platform.md
│   └── github-issue-plan.md
├── .github/workflows/       CI pipelines
├── pnpm-workspace.yaml      TS workspace definition
├── pyproject.toml           Python workspace + tool config (ruff, mypy, pytest)
├── package.json             Root scripts and pnpm config
└── tsconfig.base.json       Shared TypeScript compiler options
```

## Dependency direction

```
packages/contracts ──────────────── apps/web
                   └──────────────── workers/document-extract

packages/matching  ──────────────── workers/normalize
                   └──────────────── apps/api

db/                ← consumed by apps/api, workers/ingest, workers/normalize
tasks/             ← documentation only, no runtime dependency
```

- `packages/*` are leaf libraries — they must not import from `apps/` or
  `workers/`.
- `apps/` and `workers/` may depend on `packages/*` but never on each other
  directly.
- Python packages communicate with Node.js workers via the shared JSON
  contracts in `packages/contracts`.

## CI

GitHub Actions runs four parallel jobs on every PR and on `main` pushes:

1. **docs** — validates that `tasks/` markdown is present
2. **python** — `ruff check`, `mypy`, `pytest`
3. **typescript** — `eslint`, `tsc --noEmit`
4. **test** — `vitest` + `pytest` + Next.js production build smoke

## Environment

Copy `.env.example` to `.env` and fill in values. The `.env` file is
git-ignored and must never contain real secrets in the repository.
