"""Add raw JSONB column to policy_versions for structured eligibility fields.

The ingest adapters already preserve the source-native structured fields
(age, income, region, employment — e.g. 온통청년's 79-field listing record)
on SourceRecord.raw, but the ingest writers discarded them. Storing the raw
JSON per version lets the search eligibility evaluator read SPRT_TRGT_*,
STDG_NM, and EARN_* directly.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE policy_versions ADD COLUMN IF NOT EXISTS raw JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE policy_versions DROP COLUMN IF EXISTS raw")
