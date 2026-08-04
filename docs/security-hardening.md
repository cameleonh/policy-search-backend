# Security Hardening Checklist (Issue #21)

## Overview

This document tracks the security hardening applied across the
policy-search-backend platform per Issue #21 requirements.

## Profile data isolation (FR-SRCH-002)

- [x] User profile is never written to DB, cache, or application logs
- [x] Request logs contain only request ID, processing time, result count
- [x] Error responses never include profile field values
- [x] API test `test_no_profile_raw_data_in_response` verifies this

## Network and file security

- [x] All adapters enforce allowed-hosts validation (Issue #3)
- [x] Redirect chains are pre-validated before each hop (Issue #9, #10)
- [x] File downloads validate magic bytes, not extensions (Issue #14)
- [x] Resource limits: file size, uncompressed size, CPU, memory, timeout
- [x] Temp directories are per-task and cleaned up on completion

## Secret management

- [x] No secrets in images, repository, logs, or error responses
- [x] `.gitignore` blocks `.env`, `*.pem`, `*.key`, `*.p12`
- [x] Archive write token scoped to `policy-search-archive` only (Issue #13)
- [x] API and web containers have zero GitHub credentials (Issue #13)
- [x] Token rotation procedure documented in `docs/archive-security.md`

## Database security

- [x] PostgreSQL runs inside Docker internal network only
- [x] DB port not exposed to internet
- [x] Data volume separated from container image
- [x] Binary originals never stored in DB (Issue #13)

## Ingestion pipeline safety

- [x] Only allowed source URLs are fetched (Issue #3)
- [x] robots.txt status tracked per source
- [x] Document directives treated as data, not executed (Issue #18)
- [x] Partial parse documents cannot produce confirmed eligibility (Issue #15)
- [x] RAG cannot override deterministic hard-fail rules (Issue #18)

## Remaining production hardening (Issue #22)

- [ ] TLS termination configuration
- [ ] Rate limiting on API endpoints
- [ ] CORS policy configuration
- [ ] Audit log retention policy
