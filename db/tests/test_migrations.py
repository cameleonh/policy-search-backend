"""Test that migrations apply cleanly on an empty database."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text


def test_migrations_apply_cleanly(migrated_db: str) -> None:
    """All migrations should apply without error on a fresh database."""
    engine = create_engine(migrated_db)
    insp = inspect(engine)

    expected_tables = {
        "sources",
        "ingestion_runs",
        "ingestion_items",
        "programs",
        "policy_versions",
        "attachments",
        "document_extractions",
        "document_chunks",
        "organizations",
        "regions",
        "benefits",
        "application_windows",
        "eligibility_rules",
    }
    actual_tables = set(insp.get_table_names())
    missing = expected_tables - actual_tables
    assert not missing, f"Missing tables: {missing}"


def test_migrations_are_idempotent(migrated_db: str) -> None:
    """Re-running migrations should be a no-op, not an error."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_db)
    command.upgrade(cfg, "head")  # second time — should not raise


def test_latest_policy_versions_view_exists(migrated_db: str) -> None:
    """The latest_policy_versions view should exist and be queryable."""
    engine = create_engine(migrated_db)
    with engine.connect() as conn:
        conn.execute(text("SELECT * FROM latest_policy_versions")).fetchall()
    engine.dispose()
