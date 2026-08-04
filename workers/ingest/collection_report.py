"""Collection report — summary of a single adapter run.

Produced by every adapter invocation, whether weekly or manual.
The orchestrator uses this to update `ingestion_runs` and decide
retry/failure handling.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from workers.ingest.exit_codes import ExitCode


class CollectionOutcome(StrEnum):
    """Overall outcome category for a collection run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    MANUAL = "manual"


class CollectionReport(BaseModel):
    """Summary of one adapter's collection run."""

    source: str = Field(description="Source key")
    outcome: CollectionOutcome = Field(description="Overall result category")
    exit_code: ExitCode = Field(description="Process exit code")
    started_at: datetime = Field(description="UTC start time")
    finished_at: datetime = Field(description="UTC end time")
    expected: int = Field(
        default=0,
        description="Total count reported by source (totalCount, etc.)",
    )
    received_raw: int = Field(
        default=0,
        description="Records received from source, before dedup",
    )
    received_unique: int = Field(
        default=0,
        description="Records after same-source dedup",
    )
    persisted: int = Field(
        default=0,
        description="Records written to the pipeline",
    )
    skipped: int = Field(
        default=0,
        description="Records skipped (already known, not policy, etc.)",
    )
    failed: int = Field(
        default=0,
        description="Records that errored during fetch or parse",
    )
    error_summary: str | None = Field(
        default=None,
        description="Human-readable summary of errors, if any",
    )
    checkpoint: str | None = Field(
        default=None,
        description="Opaque checkpoint value for resumable collection",
    )


def outcome_from_counts(
    expected: int, received: int, failed: int, blocked: bool = False
) -> CollectionOutcome:
    """Determine the outcome category from collection counts.

    An empty result where the source reported items > 0 is FAILED,
    not SUCCESS — a key invariant from the issue requirements.
    """
    if blocked:
        return CollectionOutcome.MANUAL
    if received == 0 and expected > 0:
        return CollectionOutcome.FAILED
    if failed > 0 or received < expected:
        return CollectionOutcome.PARTIAL
    return CollectionOutcome.SUCCESS


def exit_code_from_outcome(outcome: CollectionOutcome) -> ExitCode:
    """Map outcome to process exit code."""
    match outcome:
        case CollectionOutcome.SUCCESS:
            return ExitCode.COMPLETE
        case CollectionOutcome.PARTIAL:
            return ExitCode.PARTIAL
        case CollectionOutcome.MANUAL:
            return ExitCode.MANUAL
        case _:
            return ExitCode.FAILED
