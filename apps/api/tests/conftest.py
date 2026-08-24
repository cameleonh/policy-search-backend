"""Shared API test fixtures — in-memory SQLite client for the search app."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from apps.api.main import app


@pytest.fixture
def db_client() -> Generator[TestClient, None, None]:
    """Create a test client with an in-memory SQLite database."""
    engine = create_engine(
        "sqlite://", echo=False, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS sources ("
                "id INTEGER PRIMARY KEY, source_key TEXT UNIQUE, name TEXT, url TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS programs ("
                "id INTEGER PRIMARY KEY, source_id INTEGER, remote_id TEXT, "
                "canonical_url TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS policy_versions ("
                "id INTEGER PRIMARY KEY, program_id INTEGER, version_number INTEGER, "
                "title TEXT, content_sha256 TEXT, target_type TEXT, "
                "announcement_url TEXT, body_text TEXT, raw TEXT, "
                "collected_at TEXT DEFAULT CURRENT_TIMESTAMP, is_valid BOOLEAN DEFAULT 1)"
            )
        )

        conn.execute(
            text(
                "INSERT INTO sources (id, source_key, name, url) "
                "VALUES (1, 'youthcenter', '온통청년', 'https://youthcenter.go.kr')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO programs (id, source_id, remote_id, canonical_url) "
                "VALUES (1, 1, 'P001', 'https://example.com/1')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO policy_versions "
                "(id, program_id, version_number, title, content_sha256, target_type, "
                "announcement_url, is_valid) "
                "VALUES (1, 1, 1, '청년 창업 지원', 'abc', 'individual', "
                "'https://example.com/1', 1)"
            )
        )
        # Create latest view after data is inserted
        conn.execute(text("DROP TABLE IF EXISTS latest_policy_versions"))
        conn.execute(
            text("""
            CREATE TABLE latest_policy_versions AS
            SELECT p.id AS program_id, p.source_id, p.remote_id, p.canonical_url,
                   pv.id AS policy_version_id, pv.version_number, pv.title,
                   pv.content_sha256, pv.target_type, pv.announcement_url,
                   pv.collected_at, pv.is_valid
            FROM programs p
            JOIN policy_versions pv ON pv.program_id = p.id
            WHERE pv.is_valid = 1
        """)
        )

    import apps.api.routers.search as search_router

    original_get_engine = search_router._get_engine
    original_engine = search_router._engine
    search_router._engine = engine  # Set global cache to our test engine

    yield TestClient(app)

    search_router._get_engine = original_get_engine
    search_router._engine = original_engine
