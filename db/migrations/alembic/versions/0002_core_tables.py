"""Create core tables for policy search platform.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CHECK constraint value lists (must match db.enums)
EXECUTION_STATUSES = "('pending', 'running', 'partial', 'succeeded', 'failed')"
DOCUMENT_STATUSES = "('pending', 'parsed', 'partial', 'encrypted', 'unsupported', 'failed')"
TARGET_TYPES = "('individual', 'business', 'both')"
EXTRACT_METHODS = "('rule_based', 'llm')"
REGION_LEVELS = "('national', 'metropolitan', 'local')"


def upgrade() -> None:
    # ── sources ───────────────────────────────
    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source_key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("config", postgresql.JSONB, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ── ingestion_runs ────────────────────────
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "source_id",
            sa.BigInteger,
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("total_items", sa.Integer),
        sa.Column("succeeded_items", sa.Integer),
        sa.Column("failed_items", sa.Integer),
        sa.Column("error_summary", sa.Text),
        sa.CheckConstraint(f"status IN {EXECUTION_STATUSES}", name="ck_ingestion_runs_status"),
    )
    op.create_index("ix_ingestion_runs_source_id", "ingestion_runs", ["source_id"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])

    # ── ingestion_items ───────────────────────
    op.create_table(
        "ingestion_items",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("remote_id", sa.String(500), nullable=False),
        sa.Column("canonical_url", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("raw_metadata", postgresql.JSONB),
        sa.CheckConstraint(f"status IN {EXECUTION_STATUSES}", name="ck_ingestion_items_status"),
    )
    op.create_index("ix_ingestion_items_run_id", "ingestion_items", ["run_id"])

    # ── programs ──────────────────────────────
    op.create_table(
        "programs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "source_id",
            sa.BigInteger,
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("remote_id", sa.String(500), nullable=False),
        sa.Column("canonical_url", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_id", "remote_id", name="uq_programs_source_remote"),
    )

    # ── policy_versions ───────────────────────
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "program_id",
            sa.BigInteger,
            sa.ForeignKey("programs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("body_text", sa.Text),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("raw_html", sa.Text),
        sa.Column("announcement_url", sa.Text, nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("is_valid", sa.Boolean, server_default="true", nullable=False),
        sa.Column("superseded_by", sa.BigInteger),
        sa.CheckConstraint(f"target_type IN {TARGET_TYPES}", name="ck_policy_versions_target_type"),
        sa.UniqueConstraint(
            "program_id", "version_number", name="uq_policy_versions_program_version"
        ),
    )
    op.create_index("ix_policy_versions_program_id", "policy_versions", ["program_id"])
    op.create_index("ix_policy_versions_content_sha256", "policy_versions", ["content_sha256"])

    # ── attachments ───────────────────────────
    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "policy_version_id",
            sa.BigInteger,
            sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("byte_size", sa.BigInteger),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("archive_tag", sa.String(100)),
        sa.Column("archive_path", sa.Text),
        sa.Column("source_url", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("file_sha256", name="uq_attachments_file_sha256"),
    )
    op.create_index("ix_attachments_policy_version_id", "attachments", ["policy_version_id"])

    # ── document_extractions ──────────────────
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "attachment_id",
            sa.BigInteger,
            sa.ForeignKey("attachments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("parser_name", sa.String(100), nullable=False),
        sa.Column("parser_version", sa.String(50), nullable=False),
        sa.Column("options_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("markdown_text", sa.Text),
        sa.Column("structured_blocks", postgresql.JSONB),
        sa.Column("error_code", sa.String(100)),
        sa.Column("warnings", postgresql.JSONB),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"status IN {DOCUMENT_STATUSES}", name="ck_document_extractions_status"),
        sa.UniqueConstraint(
            "file_sha256",
            "parser_name",
            "parser_version",
            "options_hash",
            name="uq_document_extractions_file_parser_options",
        ),
    )

    # ── document_chunks ───────────────────────
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "extraction_id",
            sa.BigInteger,
            sa.ForeignKey("document_extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("policy_version_id", sa.BigInteger),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("section", sa.String(500)),
        sa.Column("page_number", sa.Integer),
        sa.Column("table_ref", sa.String(200)),
        sa.Column("location_json", postgresql.JSONB),
    )
    op.create_index("ix_document_chunks_extraction_id", "document_chunks", ["extraction_id"])
    op.create_index(
        "ix_document_chunks_policy_version_id", "document_chunks", ["policy_version_id"]
    )

    # ── organizations ─────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("normalized_name", sa.String(255), nullable=False, unique=True),
        sa.Column("original_name", sa.String(255)),
    )

    # ── regions ───────────────────────────────
    op.create_table(
        "regions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("code", sa.String(20), unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("parent_id", sa.BigInteger, sa.ForeignKey("regions.id", ondelete="SET NULL")),
        sa.CheckConstraint(f"level IN {REGION_LEVELS}", name="ck_regions_level"),
    )

    # ── benefits ──────────────────────────────
    op.create_table(
        "benefits",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "policy_version_id",
            sa.BigInteger,
            sa.ForeignKey("policy_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("benefit_type", sa.String(100)),
        sa.Column("amount", sa.BigInteger),
        sa.Column("unit", sa.String(50)),
        sa.Column("description", sa.Text),
    )
    op.create_index("ix_benefits_policy_version_id", "benefits", ["policy_version_id"])

    # ── application_windows ───────────────────
    op.create_table(
        "application_windows",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "policy_version_id",
            sa.BigInteger,
            sa.ForeignKey("policy_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.DateTime(timezone=True)),
        sa.Column("end_date", sa.DateTime(timezone=True)),
        sa.Column("is_always_open", sa.Boolean, server_default="false", nullable=False),
        sa.Column("raw_period_text", sa.Text),
    )
    op.create_index(
        "ix_application_windows_policy_version_id", "application_windows", ["policy_version_id"]
    )

    # ── eligibility_rules ─────────────────────
    op.create_table(
        "eligibility_rules",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "policy_version_id",
            sa.BigInteger,
            sa.ForeignKey("policy_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("operator", sa.String(50), nullable=False),
        sa.Column("value", sa.Text),
        sa.Column("unit", sa.String(50)),
        sa.Column("evidence_ref", sa.Text),
        sa.Column("extract_method", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("parent_rule_id", sa.BigInteger),
        sa.Column("logical_op", sa.String(10)),
        sa.CheckConstraint(
            f"extract_method IN {EXTRACT_METHODS}", name="ck_eligibility_rules_extract_method"
        ),
        sa.CheckConstraint(
            "logical_op IN ('AND', 'OR', 'NOT', NULL)", name="ck_eligibility_rules_logical_op"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_eligibility_rules_confidence_range",
        ),
    )
    op.create_index(
        "ix_eligibility_rules_policy_version_id", "eligibility_rules", ["policy_version_id"]
    )


def downgrade() -> None:
    op.drop_table("eligibility_rules")
    op.drop_table("application_windows")
    op.drop_table("benefits")
    op.drop_table("regions")
    op.drop_table("organizations")
    op.drop_table("document_chunks")
    op.drop_table("document_extractions")
    op.drop_table("attachments")
    op.drop_table("policy_versions")
    op.drop_table("programs")
    op.drop_table("ingestion_items")
    op.drop_table("ingestion_runs")
    op.drop_table("sources")
