"""SQLAlchemy ORM models for the policy search platform.

All tables are append-only for policy data — updates create new
`policy_version` rows rather than mutating existing ones.  Binary
originals are never stored; only archive coordinates and SHA-256 hashes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.enums import (
    DocumentStatus,
    ExecutionStatus,
    ExtractMethod,
    RegionLevel,
    TargetType,
)

# ── Sources & ingestion ───────────────────────


class Source(Base):
    """A registered ingestion source (e.g. 온통청년, 소상공인24)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IngestionRun(Base):
    """A single weekly or manual ingestion execution."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_items: Mapped[int | None] = mapped_column(Integer)
    succeeded_items: Mapped[int | None] = mapped_column(Integer)
    failed_items: Mapped[int | None] = mapped_column(Integer)
    error_summary: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{ExecutionStatus.PENDING}', '{ExecutionStatus.RUNNING}', "
            f"'{ExecutionStatus.PARTIAL}', '{ExecutionStatus.SUCCEEDED}', "
            f"'{ExecutionStatus.FAILED}')",
            name="ck_ingestion_runs_status",
        ),
        Index("ix_ingestion_runs_source_id", "source_id"),
        Index("ix_ingestion_runs_status", "status"),
    )


class IngestionItem(Base):
    """Per-item result within an ingestion run."""

    __tablename__ = "ingestion_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    remote_id: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{ExecutionStatus.PENDING}', '{ExecutionStatus.RUNNING}', "
            f"'{ExecutionStatus.PARTIAL}', '{ExecutionStatus.SUCCEEDED}', "
            f"'{ExecutionStatus.FAILED}')",
            name="ck_ingestion_items_status",
        ),
        Index("ix_ingestion_items_run_id", "run_id"),
    )


# ── Policies & versions ───────────────────────


class Program(Base):
    """A logical policy identifier grouping multiple versions.

    Unique per (source_id, remote_id) — the same policy from the same
    source cannot have two Program rows.
    """

    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    remote_id: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("source_id", "remote_id", name="uq_programs_source_remote"),)


class PolicyVersion(Base):
    """An immutable snapshot of a policy announcement.

    Updates always INSERT a new version — existing rows are never
    UPDATEd.  The `content_sha256` distinguishes content changes.
    """

    __tablename__ = "policy_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    program_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("programs.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_html: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    announcement_url: Mapped[str] = mapped_column(Text, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_valid: Mapped[bool] = mapped_column(default=True, nullable=False)
    superseded_by: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("program_id", "version_number", name="uq_policy_versions_program_version"),
        CheckConstraint(
            f"target_type IN ('{TargetType.INDIVIDUAL}', '{TargetType.BUSINESS}', "
            f"'{TargetType.BOTH}')",
            name="ck_policy_versions_target_type",
        ),
        Index("ix_policy_versions_program_id", "program_id"),
        Index("ix_policy_versions_content_sha256", "content_sha256"),
    )


# ── Attachments ───────────────────────────────


class Attachment(Base):
    """Metadata for an original file stored in the GitHub archive.

    The binary itself lives in a GitHub Release — only coordinates,
    SHA-256, and MIME info are stored here.
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_tag: Mapped[str | None] = mapped_column(String(100))
    archive_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("file_sha256", name="uq_attachments_file_sha256"),
        Index("ix_attachments_policy_version_id", "policy_version_id"),
    )


# ── Document extraction & chunks ──────────────


class DocumentExtraction(Base):
    """Result of running Kordoc (or future parsers) on an attachment.

    Unique on (file_sha256, parser_name, parser_version, options_hash)
    so re-parsing the same file with the same configuration is a no-op.
    """

    __tablename__ = "document_extractions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attachment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attachments.id", ondelete="RESTRICT"), nullable=False
    )
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    options_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    markdown_text: Mapped[str | None] = mapped_column(Text)
    structured_blocks: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    warnings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "file_sha256",
            "parser_name",
            "parser_version",
            "options_hash",
            name="uq_document_extractions_file_parser_options",
        ),
        CheckConstraint(
            f"status IN ('{DocumentStatus.PENDING}', '{DocumentStatus.PARSED}', "
            f"'{DocumentStatus.PARTIAL}', '{DocumentStatus.ENCRYPTED}', "
            f"'{DocumentStatus.UNSUPPORTED}', '{DocumentStatus.FAILED}')",
            name="ck_document_extractions_status",
        ),
    )


class DocumentChunk(Base):
    """A searchable text chunk with provenance back to the source document."""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("document_extractions.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_version_id: Mapped[int | None] = mapped_column(BigInteger)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(String(500))
    page_number: Mapped[int | None] = mapped_column(Integer)
    table_ref: Mapped[str | None] = mapped_column(String(200))
    location_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_document_chunks_extraction_id", "extraction_id"),
        Index("ix_document_chunks_policy_version_id", "policy_version_id"),
    )


# ── Reference data ────────────────────────────


class Organization(Base):
    """A government body or implementing agency."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255))


class Region(Base):
    """A geographic region in the Korean administrative hierarchy."""

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("regions.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            f"level IN ('{RegionLevel.NATIONAL}', '{RegionLevel.METROPOLITAN}', "
            f"'{RegionLevel.LOCAL}')",
            name="ck_regions_level",
        ),
    )


class Benefit(Base):
    """Support type and scale for a policy version."""

    __tablename__ = "benefits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("policy_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    benefit_type: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[int | None] = mapped_column(BigInteger)
    unit: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_benefits_policy_version_id", "policy_version_id"),)


class ApplicationWindow(Base):
    """Application period for a policy version."""

    __tablename__ = "application_windows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("policy_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_always_open: Mapped[bool] = mapped_column(default=False, nullable=False)
    raw_period_text: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_application_windows_policy_version_id", "policy_version_id"),)


class EligibilityRule(Base):
    """A versioned eligibility rule tree node.

    Each node references a field, operator, value, evidence location,
    extraction method, and confidence.  Rules are immutable per policy
    version — new versions get new rule rows.
    """

    __tablename__ = "eligibility_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("policy_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(50))
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    extract_method: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column()
    parent_rule_id: Mapped[int | None] = mapped_column(BigInteger)
    logical_op: Mapped[str | None] = mapped_column(String(10))

    __table_args__ = (
        CheckConstraint(
            f"extract_method IN ('{ExtractMethod.RULE_BASED}', '{ExtractMethod.LLM}')",
            name="ck_eligibility_rules_extract_method",
        ),
        CheckConstraint(
            "logical_op IN ('AND', 'OR', 'NOT', NULL)",
            name="ck_eligibility_rules_logical_op",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_eligibility_rules_confidence_range",
        ),
        Index("ix_eligibility_rules_policy_version_id", "policy_version_id"),
    )
