"""Security hardening tests (issue #21) — headers, CORS default, rate limit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import _reset_rate_limit_state


@pytest.fixture
def sec_client(db_client: TestClient) -> TestClient:
    _reset_rate_limit_state()
    return db_client


class TestSecurityHeaders:
    def test_standard_headers_on_every_response(self, sec_client: TestClient) -> None:
        response = sec_client.get("/health")
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"

    def test_cors_disabled_by_default(self, sec_client: TestClient) -> None:
        preflight = sec_client.options(
            "/v1/search",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in preflight.headers
        assert "access-control-allow-credentials" not in preflight.headers


class TestRateLimit:
    def test_post_rate_limited_per_ip(
        self,
        sec_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("apps.api.main._RATE_LIMIT", 3)
        statuses = [sec_client.post("/v1/search", json={}).status_code for _ in range(5)]
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3:] == [429, 429]
        retry_after = sec_client.post("/v1/search", json={}).headers.get("Retry-After")
        assert retry_after is not None and retry_after.isdigit()

    def test_get_not_rate_limited(
        self,
        sec_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("apps.api.main._RATE_LIMIT", 1)
        statuses = [sec_client.get("/health").status_code for _ in range(3)]
        assert statuses == [200, 200, 200]


class TestRequestBodyLimit:
    def test_oversized_body_rejected(self, sec_client: TestClient) -> None:
        response = sec_client.post(
            "/v1/search",
            content=b"x",
            headers={"Content-Length": str(10 * 1024 * 1024)},
        )
        assert response.status_code == 413
