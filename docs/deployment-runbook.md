# Deployment Runbook (Issue #22)

## Prerequisites

- AWS Lightsail instance (2+ vCPU, 4+ GB RAM recommended)
- Docker and Docker Compose installed
- `policy-search-archive` private GitHub repo created
- Fine-grained PAT with `Contents: Read and write` on archive repo only

## Initial deployment

```bash
# 1. Clone repository
git clone https://github.com/cameleonh/policy-search-backend.git
cd policy-search-backend

# 2. Configure environment
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, ARCHIVE_GITHUB_TOKEN

# 3. Start services
#    web builds from ../policy-search-frontend (contracts delivered via the
#    named build context). ingest runs the weekly scheduler by default.
docker compose up -d

# 4. Run database migrations
docker compose exec api uv run alembic upgrade head

# 5. Verify health
curl http://localhost:8000/health
curl http://localhost:3000/api/health
```

## Service architecture

```
Internet → [web:3000] → Next.js SSR
         → [api:8000] → FastAPI
[db:5432] → PostgreSQL + pgvector (internal only)
[ingest]  → Weekly ingestion worker (archive token)
```

- **web**: Next.js (standalone repo `../policy-search-frontend`), port 3000
- **api**: FastAPI, port 8000
- **db**: PostgreSQL 16 + pgvector, internal network only
- **ingest**: fixed-time scheduler (`scripts/ingest_scheduler.py`, `INGEST_TIMES`, default `11:00,19:00` local time), resource-limited (1 CPU, 1 GB RAM)

## Backup

```bash
# PostgreSQL backup (run from host)
docker compose exec db pg_dump -U policy policy_search > backup_$(date +%Y%m%d).sql

# Restore
docker compose exec -T db psql -U policy policy_search < backup_YYYYMMDD.sql
```

## Recovery

### Database failure
1. Stop services: `docker compose down`
2. Restore from backup: `psql < backup.sql`
3. Restart: `docker compose up -d`
4. Verify: `curl http://localhost:8000/health`

### Lost Release asset (archive)
1. Check `attachments` table for `archive_tag` + `archive_asset`
2. Re-download from GitHub Release
3. Verify SHA-256 against `attachments.file_sha256`
4. If Release is gone, re-run ingestion for that week

### Token rotation
1. Generate new PAT (Settings → Developer settings → Fine-grained tokens)
2. Scope: `Contents: Read and write` on `cameleonh/policy-search-archive`
3. Update `.env`: `ARCHIVE_GITHUB_TOKEN=new_token`
4. Restart ingest: `docker compose restart ingest`

## Post-deployment smoke test

```bash
# 1. Health checks
curl -s http://localhost:8000/health | jq .status  # → "ok"
curl -s http://localhost:3000/api/health | jq .status  # → "ok"

# 2. Search smoke
curl -s -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"region": "서울특별시"}' | jq .total

# 3. Detail smoke (id from the search above)
curl -s http://localhost:8000/v1/policies/1 | jq .policy_title

# 4. Manual ingestion (outside the daily schedule)
# docker compose run --rm ingest uv run python scripts/ingest_all.py

# 5. Service restart verification
docker compose restart
sleep 10
curl -s http://localhost:8000/health | jq .status  # → "ok"
```

## Resource limits

- Ingest worker concurrency: limited to prevent search exhaustion
- Kordoc worker: 512 MB memory, 60s timeout per file
- Database: persistent volume, not in container image
- No DB port exposed to internet
