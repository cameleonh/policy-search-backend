"""Search API router — POST /v1/search.

Stateless: profile is used only for the request lifecycle and never
persisted to DB, cache, or logs.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import create_engine, text

from apps.api.contracts.search import (
    ErrorResponse,
    EvidenceRef,
    MatchStatus,
    PolicyCategory,
    PolicyResult,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/v1", tags=["search"])


def _get_engine() -> Any:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://policy:policy@localhost:5432/policy_search",
    )
    return create_engine(url)


@router.post("/search", response_model=SearchResponse, responses={400: {"model": ErrorResponse}})
async def search(request: SearchRequest) -> SearchResponse:
    """Unified policy search — individual + business in one request.

    1. Query latest policy versions from DB (ILIKE title/region filter)
    2. Paginate and return results
    3. Profile is never persisted
    """
    engine = _get_engine()

    offset = (request.page - 1) * request.page_size

    conditions = ["pv.is_valid = true"]
    params: dict[str, Any] = {}

    if request.region:
        conditions.append("(LOWER(pv.title) LIKE :region OR LOWER(lpv.canonical_url) LIKE :region)")
        params["region"] = f"%{request.region.lower()}%"

    if request.interest_topics:
        conditions.append("(LOWER(pv.title) LIKE :topic)")
        params["topic"] = f"%{request.interest_topics[0].lower()}%"

    where = " AND ".join(conditions)

    with engine.connect() as conn:
        # Get total count
        count_sql = f"""
            SELECT COUNT(*)
            FROM latest_policy_versions lpv
            JOIN policy_versions pv ON pv.id = lpv.policy_version_id
            JOIN programs p ON p.id = pv.program_id
            JOIN sources s ON s.id = p.source_id
            WHERE {where}
        """
        total = conn.execute(text(count_sql), params).scalar_one()

        # Get results
        sql = f"""
            SELECT pv.id, pv.title, pv.target_type, pv.announcement_url,
                   s.source_key, s.name as source_name
            FROM latest_policy_versions lpv
            JOIN policy_versions pv ON pv.id = lpv.policy_version_id
            JOIN programs p ON p.id = pv.program_id
            JOIN sources s ON s.id = p.source_id
            WHERE {where}
            ORDER BY pv.collected_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = request.page_size
        params["offset"] = offset
        rows = conn.execute(text(sql), params).fetchall()

    results: list[PolicyResult] = []
    for row in rows:
        pv_id, title, target_type, url, source_key, source_name = row

        category = PolicyCategory.INDIVIDUAL
        if target_type == "business":
            category = PolicyCategory.BUSINESS
        elif target_type == "both":
            category = PolicyCategory.BOTH

        results.append(
            PolicyResult(
                result_id=f"r-{pv_id}",
                policy_version_id=pv_id,
                policy_title=title,
                category=category,
                status=MatchStatus.POSSIBLE,
                agency=source_name,
                reasons=["데이터 적재 완료 — 자격 판정 대기"],
                missing_info=["상세 자격 규칙 추출 전"],
                announcement_url=url,
                evidence=[
                    EvidenceRef(
                        evidence_id=f"src-{source_key}",
                        text_snippet=f"출처: {source_name}",
                    )
                ],
            )
        )

    return SearchResponse(
        data_version=f"live-{datetime.now(UTC).strftime('%Y-%m-%d')}",
        results=results,
        total=total,
        page=request.page,
        page_size=request.page_size,
        rag_enabled=False,
    )
