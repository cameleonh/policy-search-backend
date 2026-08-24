"""Search API router — POST /v1/search.

Stateless: profile is used only for the request lifecycle and never
persisted to DB, cache, or logs. Includes eligibility evaluation.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text

from apps.api.contracts.search import (
    ErrorResponse,
    EvidenceRef,
    MatchStatus,
    PolicyCategory,
    PolicyDetail,
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

# Form options → source-native employment tokens (온통청년 EMPM_STTS_NM).
_EMPLOYMENT_TOKEN = {
    "미취업": "미취업자",
    "재직중": "재직자",
    "자영업": "자영업자",
}


def _employment_allowed(raw: dict[str, Any]) -> list[str]:
    """Employment statuses the policy admits; empty = unrestricted/unknown."""
    value = raw.get("EMPM_STTS_NM")
    if not value:
        return []
    s = str(value).strip()
    if not s or s == "제한없음":
        return []
    return [tok.strip() for tok in s.split(",") if tok.strip()]


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


# Title-keyword topic classifier — sources carry no benefit category
# (PLCY_KND_NM is empty; SPCL_FLD_NM is a special-group field), so the
# display topic is derived deterministically from the title.
_TOPIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("금융·자금", re.compile(r"대출|융자|이자|보증|금융|자금|대부|출자")),
    ("주거", re.compile(r"주거|주택|임대|하우스|월세|전세|기숙사|거주|숙소")),
    ("일자리", re.compile(r"일자리|취업|고용|인턴|채용|직무|근로|잡")),
    ("창업", re.compile(r"창업|스타트업|벤처")),
    ("교육·역량", re.compile(r"교육|훈련|연수|학습|강의|자격증|멘토|캠프|아카데미|클래스|학교")),
    ("농업·농촌", re.compile(r"농업|영농|농촌|귀농")),
    ("생활·문화", re.compile(r"의료|건강|돌봄|문화|예술|여행|체험|상담|바우처|패스|장학")),
    ("행사·모집", re.compile(r"모집|행사|페스타|페스티벌|네트워크|동아리|크루|클럽")),
]


def _topic_from_title(title: str) -> str:
    for topic, pattern in _TOPIC_RULES:
        if pattern.search(title):
            return topic
    return "기타"


# Form options → 연소득 만원 upper bound, matched against EARN_MAX_AMT.
# Bounds follow the measured source distribution (1,200–10,000만원 caps).
_INCOME_BRACKET_WON = {
    "3000만원 이하": 3000,
    "5000만원 이하": 5000,
    "7000만원 이하": 7000,
    "8000만원 이상": 8000,
}

_STUDENT_TITLE_RE = re.compile(r"장학|학자금|등록금")

# QLFC_ACBG_NM enumerates education tokens; the vocabulary observed in the
# dataset is: {고졸 예정, 고교 졸업, 고교 재학, 고졸 미만, 대학 재학, 대졸 예정,
# 대학 졸업, 석·박사, 기타}. 석·박사 is how the data says "대학원".
_UNDERGRAD_TOKENS = {"대학 재학", "대졸 예정"}
_GRAD_TOKENS = {"석·박사"}


def _required_edu_tokens(raw: dict[str, Any]) -> set[str] | None:
    """Education tokens the policy demands, or None when unrestricted.

    Titles matching 장학/학자금/등록금 with no structured condition target
    undergrad-level students (source lists only '자세히보기 참고').
    """
    edu = str(raw.get("QLFC_ACBG_NM", "") or "").strip()
    if edu and edu != "제한없음":
        return {t.strip() for t in edu.split(",") if t.strip()}
    if _STUDENT_TITLE_RE.search(raw.get("title", "")):
        return set(_UNDERGRAD_TOKENS)
    return None


def _evaluate_student(
    request: SearchRequest, raw: dict[str, Any]
) -> tuple[bool, list[str], list[str]]:
    """(blocked, reasons, blockers) for the education requirement.

    - 비재학(None) + 재학/석박사 요구 → blocked
    - undergrad → 대학 재학/대졸 예정 충족; 석·박사-only 정책은 blocked
    - grad → 석·박사 충족 + 학부 과정 조건도 충족(석사 이상은 학사 완료자)
    """
    tokens = _required_edu_tokens(raw)
    if not tokens:
        return False, [], []
    level = request.student_level
    if level is None:
        if tokens & (_UNDERGRAD_TOKENS | _GRAD_TOKENS):
            wanted = ", ".join(sorted(tokens))
            return True, [], [f"재학생 대상 (요구 학적: {wanted}) — 재학생이 아니면 신청 불가"]
        return False, [], []

    if level == "grad":
        hit = sorted(tokens & (_GRAD_TOKENS | _UNDERGRAD_TOKENS))
        if hit:
            return False, [f"학적 조건 충족 ({', '.join(hit)})"], []
    else:
        hit = sorted(tokens & _UNDERGRAD_TOKENS)
        if hit:
            return False, [f"학적 조건 충족 ({', '.join(hit)})"], []
    wanted = ", ".join(sorted(tokens))
    return True, [], [f"학적 조건 불일치 (대상: {wanted})"]


def _summarize_region(stdg: str) -> str | None:
    """Collapse a comma-joined district list into a human summary.

    STDG_NM enumerates every covered 시·군·구; a policy spanning all of them
    is effectively 전국 and must not be rendered as 250 entries.
    """
    entries = [e.strip() for e in stdg.split(",") if e.strip()]
    if not entries:
        return None

    def root_of(entry: str) -> str:
        for name in _REGION_FULL_NAMES:
            if entry.startswith(name):
                return name
        first = entry.split(" ")[0]
        return first if first.endswith(("시", "도")) else entry

    if len(entries) >= 100:
        return "전국"

    roots: dict[str, list[str]] = {}
    for entry in entries:
        roots.setdefault(root_of(entry), []).append(entry)

    if len(roots) > 1:
        parts = [f"{root} {len(items)}곳" for root, items in roots.items()]
        return " · ".join(parts)

    root, items = next(iter(roots.items()))
    if len(items) <= 5:
        return " · ".join(i.replace(root + " ", "") for i in items)
    first = items[0].replace(root + " ", "")
    return f"{root} {first} 외 {len(items) - 1}곳"


def _as_dict(value: Any) -> dict[str, Any]:
    """JSONB arrives as dict on psycopg; SQLite test rows arrive as str."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _norm_yyyymmdd(value: Any) -> str | None:
    s = str(value or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s or None


def _clean_income(value: Any) -> str | None:
    """Normalize EARN_MAX_AMT; sources use 0/99999 sentinels for unlimited."""
    s = str(value or "").strip()
    if not s or s in ("0", "99999", "9999999999999"):
        return None
    return s


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

    # Service-level age guard: this platform targets 청년/소상공인. Profiles
    # outside 만 15–64 cannot be eligible for *any* policy here — even ones
    # with no explicit age condition — preventing e.g. an 11-year-old getting
    # "지원 가능" on scholarships with no stated age limit.
    if user_age is not None and not (15 <= user_age <= 64):
        return MatchStatus.INELIGIBLE, [
            f"서비스 대상 연령 아님 (만 15~64세 대상, 입력 만 {user_age}세)"
        ], []

    min_age, max_age = _age_bounds(raw)

    if min_age is not None:
        if user_age is not None:
            if user_age < min_age:
                return MatchStatus.INELIGIBLE, [f"나이 조건 미달 (만 {min_age}세 이상 대상)"], []
            reasons.append(f"나이 조건 충족 (만 {min_age}세 이상)")
        else:
            missing.append(f"나이 (만 {min_age}세 이상 확인 필요)")

    if max_age is not None:
        if user_age is not None:
            if user_age > max_age:
                return MatchStatus.INELIGIBLE, [f"나이 초과 (만 {max_age}세 이하 대상)"], []
            reasons.append(f"나이 조건 충족 (만 {max_age}세 이하)")
        else:
            missing.append(f"나이 (만 {max_age}세 이하 확인 필요)")

    # Region check
    region_field = raw.get("STDG_NM", "")
    if region_field and str(region_field).strip() and str(region_field).strip() != "전국":
        summary = _summarize_region(str(region_field))
        if request.region:
            if request.region in str(region_field):
                reasons.append(f"지역 조건 충족 ({request.region})")
            else:
                pass  # Region mismatch but not hard fail — may be "전국" policy
        else:
            missing.append(f"거주 지역 ({summary})")

    # Employment check — policy lists allowed statuses (comma-joined).
    allowed_employment = _employment_allowed(raw)
    if allowed_employment:
        token = _EMPLOYMENT_TOKEN.get(request.employment_status or "", "")
        if token:
            if token in allowed_employment:
                reasons.append(f"고용 상태 충족 ({token})")
            else:
                return (
                    MatchStatus.INELIGIBLE,
                    [f"고용 상태 불일치 (대상: {', '.join(allowed_employment)})"],
                    [],
                )
        else:
            missing.append(f"고용 상태 ({', '.join(allowed_employment)})")

    # Student status — QLFC_ACBG_NM enumerates required education levels;
    # 대학 재학/대졸 예정 vs 석·박사 are matched against the user's level.
    blocked, student_reasons, student_blockers = _evaluate_student(request, raw)
    if blocked:
        return MatchStatus.INELIGIBLE, student_blockers, []
    reasons.extend(student_reasons)

    # Income check — compare the typed 만원-unit bracket against EARN_MAX_AMT.
    earn_max = _clean_income(raw.get("EARN_MAX_AMT"))
    if earn_max:
        bracket = _INCOME_BRACKET_WON.get(request.income_bracket or "")
        if bracket is not None:
            if bracket <= int(earn_max):
                reasons.append(f"소득 조건 충족 (연소득 {int(earn_max):,}만원 이하)")
            else:
                return (
                    MatchStatus.INELIGIBLE,
                    [f"소득 초과 (연소득 {int(earn_max):,}만원 이하 대상)"],
                    [],
                )
        else:
            missing.append(f"소득 정보 (연소득 {int(earn_max):,}만원 이하)")

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
    # JSON accessor differs by dialect: PostgreSQL ->>, SQLite json_extract.
    is_sqlite = engine.dialect.name == "sqlite"

    def raw_get(key: str) -> str:
        return f"json_extract(pv.raw, '$.{key}')" if is_sqlite else f"pv.raw->>'{key}'"

    conditions = ["pv.is_valid IS NOT FALSE"]
    params: dict[str, Any] = {}

    # Business-targeted announcements (참여기업 모집, 정책자금 상품 ...) are
    # noise for individual searchers — include them only for business owners.
    if not request.is_business_owner:
        conditions.append("pv.target_type <> 'business'")

    # Exclude announcements whose application window has closed — the raw
    # APLY_PRD_END_YMD is YYYYMMDD or empty; always-open/no-date rows pass.
    conditions.append(
        f"(COALESCE(NULLIF({raw_get('APLY_PRD_END_YMD')}, ''), '99991231') >= :today)"
    )
    params["today"] = datetime.now().strftime("%Y%m%d")

    # Titles carry the region token ([서울], (광양시), 충남형 ...), and the
    # structured STDG_NM region field lists covered regions — match either so
    # 서울 policies without 서울 in the title are still found.
    if request.region:
        root = _region_root(request.region)
        if root:
            conditions.append(
                f"(pv.title LIKE :region OR {raw_get('STDG_NM')} LIKE :region_raw)"
            )
            params["region"] = f"%{root}%"
            params["region_raw"] = f"%{request.region}%"

    if request.interest_topics:
        conditions.append("(LOWER(pv.title) LIKE :topic)")
        params["topic"] = f"%{request.interest_topics[0].lower()}%"

    where = " AND ".join(conditions)

    # Cross-source dedup: the same announcement is often posted on several
    # sources (305 title-identical pairs). Keep one representative per
    # normalized title, preferring youthcenter > sbiz24 > bizinfo.
    _sqlite_norm = (
        "LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
        "pv.title, ' ', ''), '[', ''), ']', ''), '(', ''), ')', ''))"
    )
    title_norm = (
        _sqlite_norm if is_sqlite else "regexp_replace(pv.title, '[^가-힣A-Za-z0-9]', '', 'g')"
    )
    dedup_cte = f"""
        SELECT pv.id, pv.title, pv.target_type, pv.announcement_url,
               s.source_key, s.name as source_name,
               pv.body_text, pv.raw AS raw_json, pv.collected_at,
               ROW_NUMBER() OVER (
                   PARTITION BY {title_norm}
                   ORDER BY CASE s.source_key
                                WHEN 'youthcenter' THEN 0
                                WHEN 'sbiz24' THEN 1
                                ELSE 2 END,
                            pv.collected_at DESC
               ) AS rn
        FROM latest_policy_versions lpv
        JOIN policy_versions pv ON pv.id = lpv.policy_version_id
        JOIN programs p ON p.id = pv.program_id
        JOIN sources s ON s.id = p.source_id
        WHERE {where}
    """

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM ({dedup_cte}) WHERE rn = 1"), params
        ).scalar_one()

        sql = f"""
            SELECT id, title, target_type, announcement_url,
                   source_key, source_name, body_text, raw_json
            FROM ({dedup_cte})
            WHERE rn = 1
            ORDER BY collected_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = request.page_size
        params["offset"] = offset
        rows = conn.execute(text(sql), params).fetchall()

    user_token = _EMPLOYMENT_TOKEN.get(request.employment_status or "", "")
    _STATUS_ORDER = {MatchStatus.ELIGIBLE: 0, MatchStatus.POSSIBLE: 1, MatchStatus.INELIGIBLE: 2}

    def relevance(row: Any) -> tuple[int, int]:
        """Eligible first; policies targeting the user's employment status
        above status-agnostic ones (재직자 검색 시 재직자 전용 정책이 먼저)."""
        raw_fields = _as_dict(row[7])
        if body_text := row[6]:
            raw_fields.setdefault("body_text", body_text[:2000])
        raw_fields.setdefault("title", row[1])
        status, _, _ = _evaluate_eligibility(raw_fields, request)
        allowed = _employment_allowed(raw_fields)
        targets_user = 1 if (user_token and user_token in allowed) else 0
        return (_STATUS_ORDER.get(status, 3), -targets_user)

    rows.sort(key=relevance)

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
        raw_fields: dict[str, Any] = _as_dict(pv_raw)
        if body_text:
            raw_fields.setdefault("body_text", body_text[:2000])
        raw_fields.setdefault("title", title)
        status, reasons, missing_info = _evaluate_eligibility(raw_fields, request)

        results.append(
            PolicyResult(
                result_id=f"r-{pv_id}",
                policy_version_id=pv_id,
                policy_title=title,
                category=category,
                status=status,
                agency=source_name,
                topic=_topic_from_title(title),
                reasons=reasons if reasons else ["조건 확인 필요"],
                missing_info=missing_info,
                application_deadline=_norm_yyyymmdd(
                    _as_dict(pv_raw).get("APLY_PRD_END_YMD")
                ),
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


@router.get(
    "/policies/{policy_version_id}",
    response_model=PolicyDetail,
    responses={404: {"model": ErrorResponse}},
)
async def policy_detail(policy_version_id: int) -> PolicyDetail:
    """Structured eligibility conditions for a single policy version."""
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT pv.id, pv.title, pv.announcement_url, pv.raw,
                       s.name AS source_name
                FROM policy_versions pv
                JOIN programs p ON p.id = pv.program_id
                JOIN sources s ON s.id = p.source_id
                WHERE pv.id = :pid AND pv.is_valid IS NOT FALSE
            """),
            {"pid": policy_version_id},
        ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Policy version not found")

    pv_id, title, url, pv_raw, source_name = row
    raw = _as_dict(pv_raw)
    age_min, age_max = _age_bounds(raw)
    income_s = _clean_income(raw.get("EARN_MAX_AMT"))
    education = str(raw.get("QLFC_ACBG_NM", "") or "").strip()

    return PolicyDetail(
        policy_version_id=pv_id,
        policy_title=title,
        agency=source_name,
        announcement_url=url,
        apply_start=_norm_yyyymmdd(raw.get("APLY_PRD_BGNG_YMD")),
        apply_end=_norm_yyyymmdd(raw.get("APLY_PRD_END_YMD")),
        age_min=age_min,
        age_max=age_max,
        income_max=income_s,
        employment=_employment_allowed(raw),
        region=_summarize_region(str(raw.get("STDG_NM", "") or "")),
        education=education or None,
    )
