"""Shared Python contracts for cross-service data exchange.

These Pydantic models are the canonical shapes exchanged between the
API, ingestion workers, and normalization workers. They mirror the
PostgreSQL schema but are independent of SQLAlchemy — services that
only need to pass data around use these, not ORM models.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ─────────────────────────────────────


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    PARTIAL = "partial"
    ENCRYPTED = "encrypted"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class ExtractMethod(StrEnum):
    RULE_BASED = "rule_based"
    LLM = "llm"


class TargetType(StrEnum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"
    BOTH = "both"


class RegionLevel(StrEnum):
    NATIONAL = "national"
    METROPOLITAN = "metropolitan"
    LOCAL = "local"


# ── Ingestion contracts ───────────────────────


class SourceContract(BaseModel):
    source_key: str
    name: str
    url: str
    config: dict[str, Any] = Field(default_factory=dict)


class IngestionRunContract(BaseModel):
    source_id: int
    status: ExecutionStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_items: int | None = None
    succeeded_items: int | None = None
    failed_items: int | None = None
    error_summary: str | None = None


class IngestionItemContract(BaseModel):
    run_id: int
    remote_id: str
    canonical_url: str
    status: ExecutionStatus
    error_message: str | None = None
    raw_metadata: dict[str, Any] | None = None


# ── Policy contracts ──────────────────────────


class ProgramContract(BaseModel):
    source_id: int
    remote_id: str
    canonical_url: str


class PolicyVersionContract(BaseModel):
    program_id: int
    version_number: int
    title: str
    summary: str | None = None
    body_text: str | None = None
    content_sha256: str
    target_type: TargetType
    announcement_url: str
    is_valid: bool = True


# ── Attachment contracts ──────────────────────


class AttachmentContract(BaseModel):
    policy_version_id: int
    filename: str
    mime_type: str | None = None
    byte_size: int | None = None
    file_sha256: str
    archive_tag: str | None = None
    archive_path: str | None = None
    source_url: str | None = None


# ── Document extraction contracts ─────────────


class DocumentExtractionContract(BaseModel):
    attachment_id: int
    file_sha256: str
    parser_name: str
    parser_version: str
    options_hash: str
    status: DocumentStatus
    error_code: str | None = None


class DocumentChunkContract(BaseModel):
    extraction_id: int
    policy_version_id: int | None = None
    chunk_index: int
    chunk_text: str
    section: str | None = None
    page_number: int | None = None
    table_ref: str | None = None


# ── Reference data contracts ──────────────────


class OrganizationContract(BaseModel):
    normalized_name: str
    original_name: str | None = None


class RegionContract(BaseModel):
    code: str | None = None
    name: str
    level: RegionLevel
    parent_id: int | None = None


class BenefitContract(BaseModel):
    policy_version_id: int
    benefit_type: str | None = None
    amount: int | None = None
    unit: str | None = None
    description: str | None = None


class ApplicationWindowContract(BaseModel):
    policy_version_id: int
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_always_open: bool = False
    raw_period_text: str | None = None


# ── Eligibility rule contracts ────────────────


class EligibilityRuleContract(BaseModel):
    policy_version_id: int
    field_name: str
    operator: str
    value: str | None = None
    unit: str | None = None
    evidence_ref: str | None = None
    extract_method: ExtractMethod
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    parent_rule_id: int | None = None
    logical_op: str | None = None
