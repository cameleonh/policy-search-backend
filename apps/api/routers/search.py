"""Search API router — POST /v1/search.

Stateless: profile is used only for the request lifecycle and never
persisted to DB, cache, or logs.
"""

from __future__ import annotations

from fastapi import APIRouter

from apps.api.contracts.search import (
    ErrorResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/v1", tags=["search"])


@router.post("/search", response_model=SearchResponse, responses={400: {"model": ErrorResponse}})
async def search(request: SearchRequest) -> SearchResponse:
    """Unified policy search — individual + business in one request.

    1. Evaluate eligibility rules against the provided profile
    2. Exclude ineligible candidates
    3. Hybrid search (FTS + vector) on remaining candidates
    4. Generate evidence-grounded RAG explanations if enabled
    5. Return results without persisting the profile
    """
    # Placeholder — actual DB-backed search implemented in deployment
    return SearchResponse(
        data_version="not-configured",
        results=[],
        total=0,
        rag_enabled=False,
    )
