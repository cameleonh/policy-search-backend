"""Standalone ingestion script — fetch from source and insert into PostgreSQL.

Usage:
    DATABASE_URL=postgresql+psycopg://policy:policy@localhost:5432/policy_search \
      uv run python scripts/ingest.py
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from workers.ingest.youthcenter_adapter import YouthcenterAdapter


def get_engine() -> Engine:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://policy:policy@localhost:5432/policy_search",
    )
    return create_engine(url)


def ingest_youthcenter(engine: Engine) -> None:
    """Fetch from 온통청년 and insert sources, programs, policy_versions."""
    adapter = YouthcenterAdapter(open_only=False)
    print(f"[{datetime.now(UTC).isoformat()}] Fetching from {adapter.definition.display_name}...")

    records = list(adapter.list_records())
    print(f"  Received: {len(records)} records")

    with engine.begin() as conn:
        # Ensure source exists
        conn.execute(
            text("""
            INSERT INTO sources (source_key, name, url, created_at)
            VALUES (:key, :name, :url, NOW())
            ON CONFLICT (source_key) DO NOTHING
        """),
            {"key": "youthcenter", "name": "온통청년", "url": "https://www.youthcenter.go.kr"},
        )
        source_id = conn.execute(
            text("SELECT id FROM sources WHERE source_key = 'youthcenter'")
        ).scalar_one()
        print(f"  Source ID: {source_id}")

    inserted_programs = 0
    inserted_versions = 0
    skipped = 0

    for rec in records:
        content_sha = hashlib.sha256((rec.title + rec.canonical_url).encode()).hexdigest()

        with engine.begin() as conn:
            # Insert program if not exists
            result = conn.execute(
                text("""
                INSERT INTO programs (source_id, remote_id, canonical_url, created_at)
                VALUES (:sid, :rid, :url, NOW())
                ON CONFLICT (source_id, remote_id)
                DO UPDATE SET canonical_url = EXCLUDED.canonical_url
                RETURNING id
            """),
                {"sid": source_id, "rid": rec.remote_id, "url": rec.canonical_url},
            )
            program_id = result.scalar_one()

            # Check if a version with same content_sha256 already exists
            existing = conn.execute(
                text("""
                SELECT id FROM policy_versions
                WHERE program_id = :pid AND content_sha256 = :sha
            """),
                {"pid": program_id, "sha": content_sha},
            ).first()

            if existing:
                skipped += 1
                continue

            # Insert new policy version (version_number = count + 1)
            version_count = conn.execute(
                text("""
                SELECT COALESCE(MAX(version_number), 0) + 1
                FROM policy_versions WHERE program_id = :pid
            """),
                {"pid": program_id},
            ).scalar_one()

            target = "individual"  # youthcenter is always individual-targeted

            conn.execute(
                text("""
                INSERT INTO policy_versions
                    (program_id, version_number, title, summary, body_text,
                     content_sha256, target_type, announcement_url, collected_at, is_valid)
                VALUES (:pid, :vn, :title, NULL, NULL,
                        :sha, :tt, :url, NOW(), true)
            """),
                {
                    "pid": program_id,
                    "vn": version_count,
                    "title": rec.title,
                    "sha": content_sha,
                    "tt": target,
                    "url": rec.canonical_url,
                },
            )
            inserted_versions += 1
            inserted_programs += 1

    print(f"  Programs: {inserted_programs} inserted, {skipped} skipped (existing)")
    print(f"  Policy versions: {inserted_versions} inserted")

    # Verify
    with engine.connect() as conn:
        total = conn.execute(
            text(
                "SELECT COUNT(*) FROM policy_versions WHERE program_id IN (SELECT id FROM programs WHERE source_id = :sid)"
            ),
            {"sid": source_id},
        ).scalar_one()
        latest = conn.execute(text("SELECT COUNT(*) FROM latest_policy_versions")).scalar_one()
        print(f"  DB total policy_versions: {total}")
        print(f"  latest_policy_versions view: {latest} rows")


if __name__ == "__main__":
    engine = get_engine()
    print(f"Database: {engine.url}")
    ingest_youthcenter(engine)
    print("Done.")
