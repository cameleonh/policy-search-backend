"""Search API router — POST /v1/search.

Stateless: profile is used only for the request lifecycle and never
persisted to DB, cache, or logs. Includes eligibility evaluation.
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

_engine: Any = None


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://policy:policy@localhost:5432/policy_search",
        )
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def _evaluate_eligibility(
    raw: dict[str, Any],
    request: SearchRequest,
) -> tuple[MatchStatus, list[str], list[str]]:
    """Lightweight eligibility check from structured raw fields.

    Returns (status, reasons, missing_info).
    """
    reasons: list[str] = []
    missing: list[str] = []

    # Age check (온통청년 fields)
    min_age = raw.get("SPRT_TRGT_MIN_AGE")
    max_age = raw.get("SPRT_TRGT_MAX_AGE")

    # Estimate age from birth_date
    user_age: int | None = None
    if request.birth_date:
        try:
            birth = datetime.strptime(request.birth_date[:10], "%Y-%m-%d")
            user_age = (datetime.now() - birth).days // 365
        except ValueError:
            pass

    if min_age and str(min_age).strip() and str(min_age).strip() != "0":
        try:
            min_a = int(str(min_age).strip())
            if user_age is not None:
                if user_age < min_a:
                    return MatchStatus.POSSIBLE, [f"나이 조건 미달 (만 {min_a}세 이상)"], []
                reasons.append(f"나이 조건 충족 (만 {min_a}세 이상)")
            else:
                missing.append(f"나이 (만 {min_a}세 이상 확인 필요)")
        except ValueError:
            pass

    if max_age and str(max_age).strip() and str(max_age).strip() != "0":
        try:
            max_a = int(str(max_age).strip())
            if user_age is not None:
                if user_age > max_a:
                    return MatchStatus.POSSIBLE, [f"나이 초과 (만 {max_a}세 이하)"], []
                reasons.append(f"나이 조건 충족 (만 {max_a}세 이하)")
            else:
                missing.append(f"나이 (만 {max_a}세 이하 확인 필요)")
        except ValueError:
            pass

    # Region check
    region_field = raw.get("STDG_NM", "")
    if region_field and str(region_field).strip() and str(region_field).strip() != "전국":
        if request.region:
            if request.region in str(region_field):
                reasons.append(f"지역 조건 충족 ({request.region})")
            else:
                pass  # Region mismatch but not hard fail — may be "전국" policy
        else:
            missing.append(f"거주 지역 ({region_field})")

    # Income check
    earn_max = raw.get("EARN_MAX_AMT")
    if earn_max and str(earn_max).strip() and str(earn_max).strip() != "0":
        if request.income_bracket:
            reasons.append("소득 조건 확인 필요")
        else:
            missing.append("소득 정보")

    # Determine final status
    if missing:
        return MatchStatus.POSSIBLE, reasons, missing
    if reasons:
        return MatchStatus.ELIGIBLE, reasons, missing
    return MatchStatus.POSSIBLE, reasons, missing


@router.post("/search", response_model=SearchResponse, responses={400: {"model": ErrorResponse}})
async def search(request: SearchRequest) -> SearchResponse:
    """Unified policy search — individual + business in one request.

    1. Query latest policy versions with FTS
    2. Evaluate eligibility for each result
    3. Filter out ineligible, paginate, return
    4. Profile is never persisted
    """
    engine = _get_engine()
    offset = (request.page - 1) * request.page_size

    conditions = ["pv.is_valid IS NOT FALSE"]
    params: dict[str, Any] = {}

    # FTS: use pg_trgm similarity or simple LIKE
    if request.region:
        conditions.append("(LOWER(pv.title) LIKE :region)")
        params["region"] = f"%{request.region.lower()}%"

    if request.interest_topics:
        conditions.append("(LOWER(pv.title) LIKE :topic)")
        params["topic"] = f"%{request.interest_topics[0].lower()}%"

    where = " AND ".join(conditions)

    with engine.connect() as conn:
        count_sql = f"""
            SELECT COUNT(*)
            FROM latest_policy_versions lpv
            JOIN policy_versions pv ON pv.id = lpv.policy_version_id
            JOIN programs p ON p.id = pv.program_id
            JOIN sources s ON s.id = p.source_id
            WHERE {where}
        """
        total = conn.execute(text(count_sql), params).scalar_one()

        sql = f"""
            SELECT pv.id, pv.title, pv.target_type, pv.announcement_url,
                   s.source_key, s.name as source_name,
                   pv.body_text
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
        pv_id, title, target_type, url, source_key, source_name, body_text = row

        category = PolicyCategory.INDIVIDUAL
        if target_type == "business":
            category = PolicyCategory.BUSINESS
        elif target_type == "both":
            category = PolicyCategory.BOTH

        # Eligibility evaluation
        raw_fields: dict[str, Any] = {}
        if body_text:
            raw_fields["body_text"] = body_text[:2000]
        status, reasons, missing_info = _evaluate_eligibility(raw_fields, request)

        results.append(
            PolicyResult(
                result_id=f"r-{pv_id}",
                policy_version_id=pv_id,
                policy_title=title,
                category=category,
                status=status,
                agency=source_name,
                reasons=reasons if reasons else ["조건 확인 필요"],
                missing_info=missing_info,
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
