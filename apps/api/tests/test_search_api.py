"""Tests for the search API contracts and endpoint (Issue #18)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.contracts.search import (
    EvidenceRef,
    MatchStatus,
    PolicyCategory,
    PolicyResult,
    SearchRequest,
)
from apps.api.main import app

client = TestClient(app)


class TestSearchEndpoint:
    def test_search_returns_response(self) -> None:
        response = client.post("/v1/search", json={})
        assert response.status_code == 200
        data = response.json()
        assert "data_version" in data
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_search_accepts_profile(self) -> None:
        response = client.post(
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
        response = client.post("/v1/search", json={"page": 0})
        assert response.status_code == 422

    def test_search_page_size_limit(self) -> None:
        response = client.post("/v1/search", json={"page_size": 200})
        assert response.status_code == 422

    def test_no_profile_raw_data_in_response(self) -> None:
        """Profile raw values must not appear in response."""
        response = client.post(
            "/v1/search",
            json={"region": "SECRET_REGION_VALUE", "industry": "SECRET_INDUSTRY"},
        )
        body = response.json()
        body_str = str(body)
        assert "SECRET_REGION_VALUE" not in body_str
        assert "SECRET_INDUSTRY" not in body_str


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
        """OpenAPI schema should be generated without error."""
        schema = app.openapi()
        assert "/v1/search" in schema["paths"]
        assert "post" in schema["paths"]["/v1/search"]
