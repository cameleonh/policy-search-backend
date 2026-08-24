"""Tests for the search API contracts and endpoint (Issue #18).

Search endpoint tests use an in-memory SQLite DB to avoid requiring
a live PostgreSQL instance.
"""

from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from apps.api.contracts.search import (
    EvidenceRef,
    MatchStatus,
    PolicyCategory,
    PolicyResult,
    SearchRequest,
)
from apps.api.main import app
from apps.api.routers.search import (
    _age_bounds,
    _evaluate_eligibility,
    _region_root,
    _summarize_region,
)


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


class TestSearchEndpoint:
    def test_search_returns_response(self, db_client: TestClient) -> None:
        response = db_client.post("/v1/search", json={})
        assert response.status_code == 200
        data = response.json()
        assert "data_version" in data
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_search_accepts_profile(self, db_client: TestClient) -> None:
        response = db_client.post(
            "/v1/search",
            json={
                "region": "서울특별시",
                "income_bracket": "3000만원 이하",
                "is_business_owner": True,
                "industry": "소매업",
            },
        )
        assert response.status_code == 200

    def test_search_page_validation(self) -> None:
        client = TestClient(app)
        response = client.post("/v1/search", json={"page": 0})
        assert response.status_code == 422

    def test_search_page_size_limit(self) -> None:
        client = TestClient(app)
        response = client.post("/v1/search", json={"page_size": 200})
        assert response.status_code == 422

    def test_no_profile_raw_data_in_response(self, db_client: TestClient) -> None:
        response = db_client.post(
            "/v1/search",
            json={"region": "SECRET_REGION_VALUE", "industry": "SECRET_INDUSTRY"},
        )
        body = response.json()
        body_str = str(body)
        assert "SECRET_REGION_VALUE" not in body_str
        assert "SECRET_INDUSTRY" not in body_str


class TestPolicyDetailEndpoint:
    def test_detail_returns_structured_conditions(self, db_client: TestClient) -> None:
        raw = json.dumps(
            {
                "SPRT_TRGT_MIN_AGE": "19",
                "SPRT_TRGT_MAX_AGE": "39",
                "EMPM_STTS_NM": "미취업자",
                "STDG_NM": "서울특별시",
                "APLY_PRD_BGNG_YMD": "20260801",
                "APLY_PRD_END_YMD": "20260831",
                "QLFC_ACBG_NM": "대졸 이하",
            },
            ensure_ascii=False,
        )
        import apps.api.routers.search as search_router

        engine = search_router._engine
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE policy_versions SET raw = :raw WHERE id = 1"),
                {"raw": raw},
            )

        response = db_client.get("/v1/policies/1")
        assert response.status_code == 200
        d = response.json()
        assert d["policy_version_id"] == 1
        assert d["age_min"] == 19
        assert d["age_max"] == 39
        assert d["employment"] == ["미취업자"]
        assert d["apply_start"] == "2026-08-01"
        assert d["apply_end"] == "2026-08-31"
        assert d["education"] == "대졸 이하"

    def test_detail_404_for_missing(self, db_client: TestClient) -> None:
        assert db_client.get("/v1/policies/99999").status_code == 404


class TestStudentEnrollment:
    def test_scholarship_title_requires_student(self) -> None:
        raw = {"title": "국가근로장학금"}  # no structured conditions
        status, reasons, _ = _evaluate_eligibility(raw, SearchRequest(birth_date="1988-01-01"))
        assert status == MatchStatus.INELIGIBLE
        assert "재학생" in reasons[0]

    def test_scholarship_passes_for_student(self) -> None:
        raw = {"title": "국가근로장학금"}
        req = SearchRequest(birth_date="1996-05-01", is_student=True)
        status, reasons, _ = _evaluate_eligibility(raw, req)
        assert status != MatchStatus.INELIGIBLE
        assert any("학적 조건 충족" in r for r in reasons)

    def test_education_field_with_enrollment(self) -> None:
        raw = {"QLFC_ACBG_NM": "대학 재학,대졸 예정"}
        status, _, _ = _evaluate_eligibility(raw, SearchRequest(birth_date="1996-05-01"))
        assert status == MatchStatus.INELIGIBLE

    def test_education_field_unrestricted_does_not_require(self) -> None:
        raw = {"QLFC_ACBG_NM": "제한없음", "title": "청년 일자리 지원"}
        status, _, _ = _evaluate_eligibility(raw, SearchRequest(birth_date="1996-05-01"))
        assert status != MatchStatus.INELIGIBLE


class TestIncomeEvaluation:
    def test_bracket_within_cap_is_eligible(self) -> None:
        raw = {"EARN_MAX_AMT": "6000"}
        req = SearchRequest(birth_date="1996-05-01", income_bracket="5000만원 이하")
        status, reasons, _ = _evaluate_eligibility(raw, req)
        assert any("소득 조건 충족" in r for r in reasons)

    def test_bracket_over_cap_is_ineligible(self) -> None:
        raw = {"EARN_MAX_AMT": "4000"}
        req = SearchRequest(birth_date="1996-05-01", income_bracket="5000만원 이하")
        status, reasons, _ = _evaluate_eligibility(raw, req)
        assert status == MatchStatus.INELIGIBLE
        assert "소득 초과" in reasons[0]

    def test_missing_bracket_becomes_missing_info(self) -> None:
        raw = {"EARN_MAX_AMT": "5000"}
        status, _, missing = _evaluate_eligibility(raw, SearchRequest(birth_date="1996-05-01"))
        assert status == MatchStatus.POSSIBLE
        assert missing and "소득 정보" in missing[0]


class TestRegionSummary:
    def test_nationwide_enumeration_collapses_to_전국(self) -> None:
        entries = [f"서울특별시 {gu}구" for gu in ("종로", "중구", "용산")]
        entries += [f"부산광역시 {gu}구" for gu in ("서", "동", "영도")]
        assert _summarize_region(",".join(entries * 20)) == "전국"

    def test_single_province_many_districts(self) -> None:
        cities = ("청주시", "충주시", "제천시", "보은군", "옥천군", "영동군")
        stdg = ",".join(f"충청북도 {city}" for city in cities)
        assert _summarize_region(stdg) == "충청북도 청주시 외 5곳"

    def test_small_list_shows_districts(self) -> None:
        assert _summarize_region("광주광역시 동구, 광주광역시 서구") == "동구 · 서구"

    def test_multi_province_summary(self) -> None:
        stdg = "서울특별시 강남구, 서울특별시 송파구, 부산광역시 해운대구"
        assert _summarize_region(stdg) == "서울특별시 2곳 · 부산광역시 1곳"

    def test_empty(self) -> None:
        assert _summarize_region("") is None
        assert _summarize_region(" , ") is None


class TestRegionRoot:
    def test_full_administrative_names_reduce_to_root(self) -> None:
        assert _region_root("서울특별시") == "서울"
        assert _region_root("부산광역시") == "부산"
        assert _region_root("경기도") == "경기"

    def test_abbreviated_provinces_map(self) -> None:
        assert _region_root("충청북도") == "충북"
        assert _region_root("전라남도") == "전남"
        assert _region_root("경상북도") == "경북"

    def test_colloquial_variants_agree(self) -> None:
        assert (
            _region_root("서울시") == _region_root("서울특별시") == _region_root(" 서울 ") == "서울"
        )

    def test_city_suffix_stripped(self) -> None:
        assert _region_root("광양시") == "광양"
        assert _region_root("포항시") == "포항"

    def test_short_root_passthrough_and_empty(self) -> None:
        assert _region_root("충북") == "충북"
        assert _region_root("") == ""
        assert _region_root("  ") == ""


class TestAgeEvaluation:
    def test_age_range_from_body_satisfied(self) -> None:
        raw = {"body_text": "지원 대상: 만 15~39세 청년"}
        status, reasons, missing = _evaluate_eligibility(
            raw, SearchRequest(birth_date="1996-05-01")
        )
        assert status == MatchStatus.ELIGIBLE
        assert reasons and "나이 조건 충족" in reasons[0]
        assert missing == []

    def test_age_range_from_body_below_min(self) -> None:
        raw = {"body_text": "만 15~39세 대상"}
        status, reasons, _ = _evaluate_eligibility(raw, SearchRequest(birth_date="2015-01-01"))
        assert status == MatchStatus.INELIGIBLE
        assert "대상 연령" in reasons[0]  # service guard fires before range check

    def test_age_range_from_body_above_max(self) -> None:
        raw = {"body_text": "만 15~29세 대상"}
        status, reasons, _ = _evaluate_eligibility(raw, SearchRequest(birth_date="1980-01-01"))
        assert status == MatchStatus.INELIGIBLE
        assert "초과" in reasons[0]

    def test_age_constraint_without_birth_date_is_missing_info(self) -> None:
        raw = {"body_text": "만 18세 이상 신청 가능"}
        status, _, missing = _evaluate_eligibility(raw, SearchRequest())
        assert status == MatchStatus.POSSIBLE
        assert missing and "나이" in missing[0]

    def test_structured_sprt_fields_take_priority(self) -> None:
        raw = {"SPRT_TRGT_MIN_AGE": "19", "SPRT_TRGT_MAX_AGE": "39", "body_text": "만 65세 이상"}
        assert _age_bounds(raw) == (19, 39)

    def test_sentinel_age_means_no_limit(self) -> None:
        assert _age_bounds({"SPRT_TRGT_MAX_AGE": "99999"}) == (None, None)


class TestEmploymentEvaluation:
    def test_matching_status_is_eligible(self) -> None:
        raw = {"EMPM_STTS_NM": "미취업자"}
        req = SearchRequest(employment_status="미취업")
        status, reasons, missing = _evaluate_eligibility(raw, req)
        assert status == MatchStatus.ELIGIBLE
        assert "고용 상태 충족 (미취업자)" in reasons
        assert missing == []

    def test_mismatching_status_is_ineligible(self) -> None:
        raw = {"EMPM_STTS_NM": "미취업자"}
        status, reasons, _ = _evaluate_eligibility(raw, SearchRequest(employment_status="재직중"))
        assert status == MatchStatus.INELIGIBLE
        assert "고용 상태 불일치" in reasons[0]

    def test_multi_token_list_accepts_each(self) -> None:
        raw = {"EMPM_STTS_NM": "재직자,미취업자"}
        status, reasons, _ = _evaluate_eligibility(raw, SearchRequest(employment_status="미취업"))
        assert status == MatchStatus.ELIGIBLE
        assert any("고용 상태 충족" in r for r in reasons)

    def test_unrestricted_ignored_entirely(self) -> None:
        raw = {"EMPM_STTS_NM": "제한없음"}
        req = SearchRequest(employment_status="미취업")
        status, reasons, missing = _evaluate_eligibility(raw, req)
        assert status == MatchStatus.POSSIBLE  # no reasons → possible, not missing
        assert reasons == []
        assert missing == []

    def test_absent_user_status_becomes_missing_info(self) -> None:
        raw = {"EMPM_STTS_NM": "미취업자"}
        status, _, missing = _evaluate_eligibility(raw, SearchRequest())
        assert status == MatchStatus.POSSIBLE
        assert missing and "고용 상태" in missing[0]

    def test_service_age_guard_blocks_minors(self) -> None:
        raw = {"body_text": "서울 거주 청년"}  # no age condition at all
        status, reasons, _ = _evaluate_eligibility(raw, SearchRequest(birth_date="2015-01-01"))
        assert status == MatchStatus.INELIGIBLE
        assert "대상 연령" in reasons[0]

    def test_service_age_guard_blocks_seniors(self) -> None:
        status, reasons, _ = _evaluate_eligibility(
            {"body_text": "제한없음"}, SearchRequest(birth_date="1950-01-01")
        )
        assert status == MatchStatus.INELIGIBLE
        assert "대상 연령" in reasons[0]

    def test_service_age_guard_passes_working_age(self) -> None:
        raw = {"body_text": "서울 거주 청년"}
        status, _, missing = _evaluate_eligibility(raw, SearchRequest(birth_date="1996-05-01"))
        assert status != MatchStatus.INELIGIBLE

    def test_no_age_constraint_no_missing_info(self) -> None:
        status, _, missing = _evaluate_eligibility({"body_text": "서울 거주 청년"}, SearchRequest())
        assert status == MatchStatus.POSSIBLE
        assert missing == []


class TestContracts:
    def test_policy_result_serialization(self) -> None:
        result = PolicyResult(
            result_id="r-001",
            policy_version_id=1,
            policy_title="Test Policy",
            category=PolicyCategory.INDIVIDUAL,
            status=MatchStatus.ELIGIBLE,
            evidence=[EvidenceRef(evidence_id="e-1", text_snippet="test")],
        )
        assert result.status == MatchStatus.ELIGIBLE
        assert len(result.evidence) == 1

    def test_search_request_defaults(self) -> None:
        req = SearchRequest()
        assert req.page == 1
        assert req.page_size == 20
        assert req.is_business_owner is False

    def test_match_status_values(self) -> None:
        assert MatchStatus.ELIGIBLE.value == "eligible"
        assert MatchStatus.POSSIBLE.value == "possible"

    def test_policy_category_values(self) -> None:
        assert PolicyCategory.INDIVIDUAL.value == "individual"
        assert PolicyCategory.BUSINESS.value == "business"
        assert PolicyCategory.BOTH.value == "both"

    def test_openapi_schema_generation(self) -> None:
        schema = app.openapi()
        assert "/v1/search" in schema["paths"]
        assert "post" in schema["paths"]["/v1/search"]
