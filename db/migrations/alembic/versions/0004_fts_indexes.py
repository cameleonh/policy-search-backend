"""Add FTS indexes: pg_trgm GIN on title, tsvector column.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-04
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_policy_versions_title_trgm
        ON policy_versions USING gin (title gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_policy_versions_title_lower
        ON policy_versions (lower(title))
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_policy_versions_title_lower")
    op.execute("DROP INDEX IF EXISTS ix_policy_versions_title_trgm")
