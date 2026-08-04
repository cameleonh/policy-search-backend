"""Test append-only invariant: policy updates create new versions, never UPDATE."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from db.enums import TargetType

_SQL_INSERT_EXTRACTION = (
    "INSERT INTO document_extractions "
    "(attachment_id, file_sha256, parser_name, parser_version, "
    "options_hash, status) "
    "VALUES (:aid, :sha, :pn, :pv, :oh, :st)"
)
_SQL_LATEST_VERSION = (
    "SELECT version_number FROM policy_versions WHERE program_id = :pid ORDER BY version_number"
)


def _insert_source(conn: Connection, key: str = "youth") -> int:
    conn.execute(
        text("INSERT INTO sources (source_key, name, url) VALUES (:key, :name, :url)"),
        {"key": key, "name": "Test Source", "url": "https://example.com"},
    )
    result = conn.execute(
        text("SELECT id FROM sources WHERE source_key = :key"),
        {"key": key},
    )
    return int(result.scalar_one())


def _insert_program(conn: Connection, source_id: int, remote_id: str = "r-001") -> int:
    conn.execute(
        text(
            "INSERT INTO programs (source_id, remote_id, canonical_url) VALUES (:sid, :rid, :url)"
        ),
        {"sid": source_id, "rid": remote_id, "url": "https://example.com/p/1"},
    )
    result = conn.execute(
        text("SELECT id FROM programs WHERE source_id = :sid AND remote_id = :rid"),
        {"sid": source_id, "rid": remote_id},
    )
    return int(result.scalar_one())


def _insert_version(
    conn: Connection,
    program_id: int,
    version_number: int,
    content_sha256: str,
    title: str = "Policy",
) -> int:
    conn.execute(
        text(
            "INSERT INTO policy_versions "
            "(program_id, version_number, title, content_sha256, "
            "target_type, announcement_url) "
            "VALUES (:pid, :vn, :title, :sha, :tt, :url)"
        ),
        {
            "pid": program_id,
            "vn": version_number,
            "title": title,
            "sha": content_sha256,
            "tt": TargetType.INDIVIDUAL.value,
            "url": "https://example.com/ann/1",
        },
    )
    result = conn.execute(
        text("SELECT id FROM policy_versions WHERE program_id = :pid AND version_number = :vn"),
        {"pid": program_id, "vn": version_number},
    )
    return int(result.scalar_one())


def test_policy_update_creates_new_version(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    with engine.begin() as conn:
        source_id = _insert_source(conn)
        program_id = _insert_program(conn, source_id)

        _insert_version(conn, program_id, 1, "sha-v1-content")
        _insert_version(conn, program_id, 2, "sha-v2-content-different")

    with engine.connect() as conn:
        versions = conn.execute(text(_SQL_LATEST_VERSION), {"pid": program_id}).scalars().all()
        assert versions == [1, 2]

        latest = conn.execute(
            text("SELECT version_number FROM latest_policy_versions WHERE program_id = :pid"),
            {"pid": program_id},
        ).scalar()
        assert latest == 2

    engine.dispose()


def test_duplicate_program_source_remote_rejected(migrated_db: str) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    engine = create_engine(migrated_db)
    with engine.begin() as conn:
        source_id = _insert_source(conn, key="dup-test")
        _insert_program(conn, source_id, "dup-001")

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO programs (source_id, remote_id, canonical_url) "
                "VALUES (:sid, :rid, :url)"
            ),
            {"sid": source_id, "rid": "dup-001", "url": "https://example.com"},
        )
    engine.dispose()


def test_duplicate_extraction_rejected(migrated_db: str) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    engine = create_engine(migrated_db)
    with engine.begin() as conn:
        source_id = _insert_source(conn, key="ext-test")
        program_id = _insert_program(conn, source_id, "ext-001")
        version_id = _insert_version(conn, program_id, 1, "sha-ext-v1")

        conn.execute(
            text(
                "INSERT INTO attachments (policy_version_id, filename, file_sha256) "
                "VALUES (:vid, :fn, :sha) RETURNING id"
            ),
            {"vid": version_id, "fn": "doc.hwp", "sha": "sha-256-aaa"},
        )
        att_id = conn.scalar(text("SELECT id FROM attachments WHERE file_sha256 = 'sha-256-aaa'"))

        conn.execute(
            text(_SQL_INSERT_EXTRACTION),
            {
                "aid": att_id,
                "sha": "sha-256-aaa",
                "pn": "kordoc",
                "pv": "4.6.0",
                "oh": "opt-1",
                "st": "parsed",
            },
        )

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(_SQL_INSERT_EXTRACTION),
            {
                "aid": att_id,
                "sha": "sha-256-aaa",
                "pn": "kordoc",
                "pv": "4.6.0",
                "oh": "opt-1",
                "st": "parsed",
            },
        )
    engine.dispose()
