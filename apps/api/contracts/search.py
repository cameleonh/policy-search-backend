"""Search API contracts — request/response schemas for POST /v1/search.

Issue #18 — stateless unified search API with evidence-grounded RAG.
Profile is never persisted; only used for the request lifecycle.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class PolicyCategory(StrEnum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"
    BOTH = "both"


class MatchStatus(StrEnum):
    ELIGIBLE = "eligible"
    POSSIBLE = "possible"
    INELIGIBLE = "ineligible"


class EvidenceRef(BaseModel):
    """A reference to source text that supports a claim."""

    evidence_id: str
    chunk_id: int | None = None
    section: str | None = None
    location: str = ""
    text_snippet: str = Field(default="", description="Short excerpt of the evidence text")


class PolicyResult(BaseModel):
    """A single policy search result."""

    result_id: str
    policy_version_id: int
    policy_title: str
    category: PolicyCategory
    status: MatchStatus
    agency: str = ""
    topic: str = Field(
        default="기타",
        description="Display topic derived from the title (금융·자금, 주거, ...)",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Why this status was assigned",
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="Fields that caused 'possible' instead of 'eligible'",
    )
    benefits: list[str] = Field(default_factory=list)
    application_deadline: str | None = Field(
        default=None,
        description="Application deadline (ISO date), null when always open or unknown",
    )
    announcement_url: HttpUrl | None = None
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Source text references supporting this result",
    )
    rag_explanation: str | None = Field(
        default=None,
        description="LLM-generated explanation, None if RAG unavailable",
    )


class SearchRequest(BaseModel):
    """POST /v1/search request body.

    All profile fields are optional — missing fields produce 'possible'
    instead of 'eligible'. Profile is never stored.
    """

    # Individual
    birth_date: str | None = None
    region: str | None = None
    employment_status: str | None = None
    income_bracket: str | None = None
    interest_topics: list[str] = Field(default_factory=list)
    student_level: Literal["undergrad", "grad"] | None = Field(
        default=None,
        description="재학 구분 — undergrad: 대학 재학, grad: 대학원(석·박사) 재학. None이면 비재학",
    )

    # Business
    is_business_owner: bool = False
    business_start_date: str | None = None
    business_region: str | None = None
    industry: str | None = None
    annual_revenue: int | None = None
    employee_count: int | None = None

    # Options
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class SearchResponse(BaseModel):
    """POST /v1/search response."""

    data_version: str = Field(description="Ingestion run identifier")
    results: list[PolicyResult] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    rag_enabled: bool = Field(
        default=False,
        description="Whether RAG explanations were generated",
    )


class PolicyDetail(BaseModel):
    """GET /v1/policies/{policy_version_id} response — structured conditions
    from the stored source raw fields."""

    policy_version_id: int
    policy_title: str
    agency: str = ""
    announcement_url: HttpUrl | None = None
    apply_start: str | None = None
    apply_end: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    income_max: str | None = None
    employment: list[str] = Field(default_factory=list)
    region: str | None = None
    education: str | None = None


class ErrorResponse(BaseModel):
    """Standard error response — never exposes internal details."""

    detail: str
    field_errors: dict[str, str] = Field(default_factory=dict)
