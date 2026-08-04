"""Full ingestion script — fetch from all live sources and insert into PostgreSQL."""

from __future__ import annotations

import hashlib
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from workers.ingest.bizinfo_adapter import BizinfoAdapter
from workers.ingest.sbiz24_adapter import Sbiz24Adapter
from workers.ingest.youthcenter_adapter import YouthcenterAdapter


def get_engine() -> Engine:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://policy:policy@localhost:5432/policy_search",
    )
    return create_engine(url)


def ensure_source(conn, key: str, name: str, url: str) -> int:
    conn.execute(
        text("""
        INSERT INTO sources (source_key, name, url, created_at)
        VALUES (:key, :name, :url, NOW())
        ON CONFLICT (source_key) DO NOTHING
    """),
        {"key": key, "name": name, "url": url},
    )
    return conn.execute(
        text("SELECT id FROM sources WHERE source_key = :key"), {"key": key}
    ).scalar_one()


def insert_records(
    conn, source_id: int, source_key: str, records: list, target_type: str = "individual"
) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for rec in records:
        content_sha = hashlib.sha256((rec.title + rec.canonical_url).encode()).hexdigest()

        result = conn.execute(
            text("""
            INSERT INTO programs (source_id, remote_id, canonical_url, created_at)
            VALUES (:sid, :rid, :url, NOW())
            ON CONFLICT (source_id, remote_id) DO UPDATE SET canonical_url = EXCLUDED.canonical_url
            RETURNING id
        """),
            {"sid": source_id, "rid": rec.remote_id, "url": rec.canonical_url},
        )
        program_id = result.scalar_one()

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

        version_count = conn.execute(
            text("""
            SELECT COALESCE(MAX(version_number), 0) + 1
            FROM policy_versions WHERE program_id = :pid
        """),
            {"pid": program_id},
        ).scalar_one()

        conn.execute(
            text("""
            INSERT INTO policy_versions
                (program_id, version_number, title, content_sha256,
                 target_type, announcement_url, collected_at, is_valid)
            VALUES (:pid, :vn, :title, :sha, :tt, :url, NOW(), true)
        """),
            {
                "pid": program_id,
                "vn": version_count,
                "title": rec.title,
                "sha": content_sha,
                "tt": target_type,
                "url": rec.canonical_url,
            },
        )
        inserted += 1
    return inserted, skipped


def main() -> None:
    engine = get_engine()
    print(f"Database: {engine.url}")

    # 1. 온통청년
    print("\n=== 온통청년 ===")
    adapter = YouthcenterAdapter(open_only=False)
    records = list(adapter.list_records())
    print(f"  Fetched: {len(records)}")
    with engine.begin() as conn:
        sid = ensure_source(conn, "youthcenter", "온통청년", "https://www.youthcenter.go.kr")
        ins, skip = insert_records(conn, sid, "youthcenter", records, "individual")
    print(f"  Inserted: {ins}, Skipped: {skip}")

    # 2. 소상공인24 (pbanc)
    print("\n=== 소상공인24 (pbanc) ===")
    adapter = Sbiz24Adapter(mode="pbanc")
    records = list(adapter.list_records())
    print(f"  Fetched: {len(records)}")
    with engine.begin() as conn:
        sid = ensure_source(conn, "sbiz24", "소상공인24", "https://www.sbiz24.kr")
        ins, skip = insert_records(conn, sid, "sbiz24", records, "business")
    print(f"  Inserted: {ins}, Skipped: {skip}")

    # 3. 소상공인24 (combine)
    print("\n=== 소상공인24 (combine) ===")
    adapter = Sbiz24Adapter(mode="combine")
    records = list(adapter.list_records(max_pages=10))
    print(f"  Fetched: {len(records)}")
    with engine.begin() as conn:
        sid = ensure_source(conn, "sbiz24_combine", "소상공인24 통합조회", "https://www.sbiz24.kr")
        ins, skip = insert_records(conn, sid, "sbiz24_combine", records, "business")
    print(f"  Inserted: {ins}, Skipped: {skip}")

    # 4. 기업마당
    print("\n=== 기업마당 ===")
    adapter = BizinfoAdapter(max_pages=10)
    records = list(adapter.list_records())
    print(f"  Fetched: {len(records)}")
    with engine.begin() as conn:
        sid = ensure_source(conn, "bizinfo", "기업마당", "https://www.bizinfo.go.kr")
        ins, skip = insert_records(conn, sid, "bizinfo", records, "business")
    print(f"  Inserted: {ins}, Skipped: {skip}")

    # Summary
    print("\n=== 요약 ===")
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM policy_versions")).scalar_one()
        latest = conn.execute(text("SELECT COUNT(*) FROM latest_policy_versions")).scalar_one()
        by_source = conn.execute(
            text("""
            SELECT s.source_key, COUNT(pv.*) as cnt
            FROM policy_versions pv
            JOIN programs p ON pv.program_id = p.id
            JOIN sources s ON p.source_id = s.id
            GROUP BY s.source_key
            ORDER BY cnt DESC
        """)
        ).fetchall()
    print(f"  Total policy_versions: {total}")
    print(f"  latest_policy_versions: {latest}")
    for key, cnt in by_source:
        print(f"    {key}: {cnt}건")


if __name__ == "__main__":
    main()
