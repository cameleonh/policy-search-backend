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
│   └── api/                 FastAPI search and operations API
├── workers/
│   ├── ingest/              Scheduled source ingestion (Python)
│   ├── document-extract/    Kordoc document conversion (Node.js)
│   └── normalize/           Policy / eligibility normalization (Python)
├── packages/
│   ├── contracts/           Shared TypeScript types (mirror of the Python wire contracts)
│   ├── contracts-py/        Shared Python Pydantic models
│   └── matching/            Deterministic three-valued rule evaluator (Python)
├── scripts/
│   ├── ingest.py            One-shot 온통청년 ingestion
│   ├── ingest_all.py        One-shot all-source ingestion
│   └── ingest_scheduler.py  Long-running weekly scheduler (ingest container CMD)
├── db/
│   ├── base.py              SQLAlchemy declarative base
│   ├── enums.py             Shared Python enums (mirror DB CHECK constraints)
│   ├── models.py            SQLAlchemy ORM models
│   ├── migrations/          Alembic migrations (0001–0005; 0005 adds policy_versions.raw JSONB)
│   │   └── alembic/         env.py, script template, versions/
│   └── views/               PostgreSQL views (latest_policy_versions in migration)
├── docs/
│   └── deployment-runbook.md
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

## Search & eligibility evaluation

`POST /v1/search` (apps/api/routers/search.py) evaluates every candidate
against the stored source-native structured fields (`policy_versions.raw`,
JSONB) that the ingest adapters preserve from each source listing:

| Condition | Source fields | Verdict behavior |
| --------- | ------------- | ---------------- |
| Region | typed 시도 → normalized root (`서울특별시`/`서울시` → `서울`, `충청북도` → `충북`); matches titles | no match root → unfiltered |
| Age | `SPRT_TRGT_MIN_AGE` / `SPRT_TRGT_MAX_AGE`, fallback regex on `body_text` | out of range → **ineligible**; birth_date blank → missing_info |
| Employment | `EMPM_STTS_NM` (쉼표 리스트, `제한없음` = unrestricted); form values map 미취업→미취업자, 재직중→재직자, 자영업→자영업자 | mismatch → **ineligible**; blank → missing_info |
| Income | `EARN_MAX_AMT` (만원 units; `0`/`99999` sentinels = unlimited) | shows 확인 필요 / missing_info |

Additional behaviors:

- Announcements with `target_type = 'business'` are excluded unless
  `is_business_owner` is set (참여기업 모집 등 are individual-search noise).
- Results are ranked: `eligible` first, then policies explicitly targeting
  the user's employment status above status-agnostic ones.
- `GET /v1/policies/{policy_version_id}` returns the structured conditions
  (apply period, age, income, employment, region, education) for the detail
  view.
- Sentinels are normalized, never surfaced: age `99999`, income `0`/`99999`
  mean "no limit".
- The search profile is stateless — never persisted, cached, or logged.

The Python contracts in `apps/api/contracts/search.py` are the source of
truth for the wire format; `packages/contracts` (TypeScript) mirrors them
for the standalone frontend (`../policy-search-frontend`).

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
