"""Operations scheduling, idempotency, and observability contracts.

Issue #20 — weekly scheduling, run locking, structured logging,
retry-with-backoff, and health check aggregation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StepType(StrEnum):
    SOURCE = "source"
    DOWNLOAD = "download"
    ARCHIVE = "archive"
    PARSE = "parse"
    NORMALIZE = "normalize"
    INDEX = "index"


class StepResult(BaseModel):
    """Result of a single pipeline step within a run."""

    step: StepType
    source: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    error_summary: str | None = None


class RunReport(BaseModel):
    """Full report for a single ingestion run."""

    run_id: str
    status: RunStatus = RunStatus.PENDING
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[StepResult] = Field(default_factory=list)

    @property
    def total_succeeded(self) -> int:
        return sum(s.succeeded for s in self.steps)

    @property
    def total_failed(self) -> int:
        return sum(s.failed for s in self.steps)


class ServiceHealth(BaseModel):
    """Health check result for a single service."""

    service: str
    healthy: bool
    detail: str = ""

    @property
    def status_text(self) -> str:
        return "healthy" if self.healthy else "unhealthy"


def aggregate_health(checks: list[ServiceHealth]) -> bool:
    """All services must be healthy for overall health."""
    return all(c.healthy for c in checks)


def make_run_lock_key(source: str, week_tag: str) -> str:
    """Deterministic lock key for preventing duplicate concurrent runs.

    Same source + same week → same key → prevents double execution.
    """
    raw = f"{source}:{week_tag}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def should_retry(
    attempt: int,
    max_retries: int = 3,
    last_error: str | None = None,
) -> bool:
    """Decide whether to retry based on attempt count and error type."""
    if attempt >= max_retries:
        return False
    return not (last_error is not None and "blocked" in last_error.lower())


def retry_delay(attempt: int, base_delay: float = 0.5) -> float:
    """Exponential backoff: base * 2^attempt."""
    delay: float = base_delay * (2**attempt)
    return delay
