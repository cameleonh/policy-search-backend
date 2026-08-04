# Archive Security Model

## Overview

The policy-search-archive system stores original policy documents (HWP,
PDF, etc.) in a **separate private GitHub repository** (`cameleonh/policy-search-archive`)
as weekly Release assets. No binary content ever enters the main
repository or PostgreSQL.

## Token and credential model

### Principle: least privilege, strict isolation

| Container | GitHub Token | Scope |
|---|---|---|
| **API** (`apps/api`) | None | No GitHub credentials |
| **Web** (`apps/web`) | None | No GitHub credentials |
| **Ingest worker** | Fine-grained PAT | `contents: write` on `cameleonh/policy-search-archive` only |
| **Normalize worker** | None | Reads from DB coordinates, not GitHub |

The archive upload token is injected exclusively into the ingest worker
container via Docker Compose secret environment variable. It is never
written to images, logs, error responses, or the main repository.

### Token rotation

1. Generate a new fine-grained PAT at GitHub Settings → Developer settings → Fine-grained tokens
2. Scope: `Contents: Read and write` on `cameleonh/policy-search-archive` only
3. Update the `ARCHIVE_GITHUB_TOKEN` secret in the deployment environment
4. Restart the ingest worker container
5. Old token is immediately invalid after expiry

### Lost asset recovery

If a Release asset is deleted or corrupted:
1. Check the `attachments` table for the `archive_tag` and `archive_asset` coordinates
2. Re-download the asset from the Release
3. Verify SHA-256 against `attachments.file_sha256`
4. If the Release itself is gone, re-run ingestion for that week — the pipeline
   will detect missing files and re-collect from source

## Archive structure

```
policy-search-archive repository
├── Release: ingest-2026-W31
│   ├── youthcenter.tar.gz          (source bundle)
│   ├── sbiz24.tar.gz
│   ├── bizinfo.tar.gz
│   └── ...
└── Release: ingest-2026-W32
    └── ...
```

Each `.tar.gz` bundle contains:
- `manifest.json` — file index with SHA-256, MIME, original filename, source URL
- `<safe_filename>` — original files with sanitized names

## Draft/Finalize lifecycle

1. Ingest worker collects files for a source during a weekly run
2. Files are compressed into a source bundle with a draft manifest
3. Bundle is uploaded as a Release asset
4. Asset is re-downloaded and SHA-256 verified
5. Only after verification does the manifest status become `finalized`
6. DB `attachments` rows are updated with archive coordinates
7. If upload or verification fails, the asset remains in draft state
   and the pipeline marks the run as `partial`

## Deduplication

Files with identical SHA-256 are not re-uploaded. The existing archive
coordinates are referenced in the DB `attachments` row instead.

## Size limits and splitting

GitHub Release assets have a 2GiB limit. If a source bundle exceeds this,
it is split into parts with deterministic names:
`<source>.part01of03.tar.gz`, `<source>.part02of03.tar.gz`, etc.
