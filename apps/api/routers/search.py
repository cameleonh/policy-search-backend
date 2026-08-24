"""Search API router — POST /v1/search.

Stateless: profile is used only for the request lifecycle and never
persisted to DB, cache, or logs. Includes eligibility evaluation.
"""

from __future__ import annotations

import os
import re
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

# Ingested announcements carry region only inside the title (e.g. "[서울] ...",
# "(광양시) ..."), so a region filter must match a normalized root rather than
# the exact administrative string the user typed.
_REGION_FULL_NAMES = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "강원특별자치도": "강원",
    "충청북도": "충북",
    "충청남도": "충남",
    "전라북도": "전북",
    "전라남도": "전남",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주특별자치도": "제주",
}

_AGE_RANGE_RE = re.compile(r"만?\s*(\d{1,2})\s*[~∼\-–]\s*(\d{1,2})\s*세")
_AGE_MIN_RE = re.compile(r"만\s*(\d{1,2})\s*세\s*이상")
_AGE_MAX_RE = re.compile(r"만\s*(\d{1,2})\s*세\s*이하")


def _region_root(region: str) -> str:
    """Normalize a user-typed region to its title-match root.

    서울특별시 / 서울시 / " 서울 " all reduce to 서울; 충청북도 maps to the
    abbreviated 충북 used in titles.
    """
    r = region.replace(" ", "").strip()
    if not r:
        return ""
    if r in _REGION_FULL_NAMES:
        return _REGION_FULL_NAMES[r]
    if len(r) <= 2 or r in _REGION_FULL_NAMES.values():
        return r
    while len(r) > 2 and r[-1] in "시군구도":
        r = r[:-1]
    return r


def _age_bounds(raw: dict[str, Any]) -> tuple[int | None, int | None]:
    """First-stated age constraint: structured SPRT fields, else body text."""
    def to_int(v: Any) -> int | None:
        if v is None:
            return None
        s = str(v).strip()
        if not s or s == "0":
            return None
        try:
            n = int(s)
        except ValueError:
            return None
        # Sources use sentinel values (e.g. 99999) for "no age limit".
        return n if 1 <= n <= 150 else None

    min_age = to_int(raw.get("SPRT_TRGT_MIN_AGE"))
    max_age = to_int(raw.get("SPRT_TRGT_MAX_AGE"))
    if min_age is not None or max_age is not None:
        return min_age, max_age

    body = raw.get("body_text")
    if not body:
        return None, None
    m = _AGE_RANGE_RE.search(body)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _AGE_MIN_RE.search(body)
    if m:
        return int(m.group(1)), None
    m = _AGE_MAX_RE.search(body)
    if m:
        return None, int(m.group(1))
    return None, None


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

    # Estimate age from birth_date
    user_age: int | None = None
    if request.birth_date:
        try:
            birth = datetime.strptime(request.birth_date[:10], "%Y-%m-%d")
            user_age = (datetime.now() - birth).days // 365
        except ValueError:
            pass

    min_age, max_age = _age_bounds(raw)

    if min_age is not None:
        if user_age is not None:
            if user_age < min_age:
                return MatchStatus.POSSIBLE, [f"나이 조건 미달 (만 {min_age}세 이상 대상)"], []
            reasons.append(f"나이 조건 충족 (만 {min_age}세 이상)")
        else:
            missing.append(f"나이 (만 {min_age}세 이상 확인 필요)")

    if max_age is not None:
        if user_age is not None:
            if user_age > max_age:
                return MatchStatus.POSSIBLE, [f"나이 초과 (만 {max_age}세 이하 대상)"], []
            reasons.append(f"나이 조건 충족 (만 {max_age}세 이하)")
        else:
            missing.append(f"나이 (만 {max_age}세 이하 확인 필요)")

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

    # Titles carry the region token ([서울], (광양시), 충남형 ...), so match the
    # normalized root: 서울특별시 / 서울시 / 서울 all filter as '%서울%'.
    if request.region:
        root = _region_root(request.region)
        if root:
            conditions.append("(pv.title LIKE :region)")
            params["region"] = f"%{root}%"

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
                   pv.body_text, pv.raw
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
        pv_id, title, target_type, url, source_key, source_name, body_text, pv_raw = row

        category = PolicyCategory.INDIVIDUAL
        if target_type == "business":
            category = PolicyCategory.BUSINESS
        elif target_type == "both":
            category = PolicyCategory.BOTH

        # Eligibility evaluation — structured source fields first, body text
        # regex fallback second.
        raw_fields: dict[str, Any] = {}
        if isinstance(pv_raw, dict):
            raw_fields.update(pv_raw)
        if body_text:
            raw_fields.setdefault("body_text", body_text[:2000])
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
