"""Create latest_policy_versions view.

Returns only the latest valid version per program.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW latest_policy_versions AS
        SELECT DISTINCT ON (p.id)
            p.id           AS program_id,
            p.source_id,
            p.remote_id,
            p.canonical_url,
            pv.id           AS policy_version_id,
            pv.version_number,
            pv.title,
            pv.summary,
            pv.content_sha256,
            pv.target_type,
            pv.announcement_url,
            pv.collected_at,
            pv.is_valid
        FROM programs p
        JOIN policy_versions pv ON pv.program_id = p.id
        WHERE pv.is_valid = true
        ORDER BY p.id, pv.version_number DESC
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS latest_policy_versions")
