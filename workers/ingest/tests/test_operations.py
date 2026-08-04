"""Tests for operations contracts (Issue #20)."""

from __future__ import annotations

from datetime import UTC, datetime

from workers.ingest.operations import (
    RunReport,
    RunStatus,
    ServiceHealth,
    StepResult,
    StepType,
    aggregate_health,
    make_run_lock_key,
    retry_delay,
    should_retry,
)


class TestRunLock:
    def test_same_source_week_same_key(self) -> None:
        k1 = make_run_lock_key("youthcenter", "ingest-2026-W32")
        k2 = make_run_lock_key("youthcenter", "ingest-2026-W32")
        assert k1 == k2

    def test_different_source_different_key(self) -> None:
        k1 = make_run_lock_key("youthcenter", "ingest-2026-W32")
        k2 = make_run_lock_key("sbiz24", "ingest-2026-W32")
        assert k1 != k2

    def test_different_week_different_key(self) -> None:
        k1 = make_run_lock_key("youthcenter", "ingest-2026-W31")
        k2 = make_run_lock_key("youthcenter", "ingest-2026-W32")
        assert k1 != k2


class TestRetry:
    def test_retry_allowed(self) -> None:
        assert should_retry(0, max_retries=3) is True
        assert should_retry(2, max_retries=3) is True

    def test_retry_exhausted(self) -> None:
        assert should_retry(3, max_retries=3) is False

    def test_blocked_no_retry(self) -> None:
        assert should_retry(0, last_error="HTTP 403 blocked") is False

    def test_delay_exponential(self) -> None:
        assert retry_delay(0) == 0.5
        assert retry_delay(1) == 1.0
        assert retry_delay(2) == 2.0


class TestHealthAggregation:
    def test_all_healthy(self) -> None:
        checks = [
            ServiceHealth(service="api", healthy=True),
            ServiceHealth(service="db", healthy=True),
        ]
        assert aggregate_health(checks) is True

    def test_one_unhealthy(self) -> None:
        checks = [
            ServiceHealth(service="api", healthy=True),
            ServiceHealth(service="db", healthy=False),
        ]
        assert aggregate_health(checks) is False


class TestRunReport:
    def test_totals(self) -> None:
        now = datetime.now(UTC)
        report = RunReport(
            run_id="run-1",
            status=RunStatus.SUCCEEDED,
            started_at=now,
            steps=[
                StepResult(
                    step=StepType.SOURCE,
                    source="youthcenter",
                    started_at=now,
                    succeeded=100,
                    failed=0,
                ),
                StepResult(
                    step=StepType.PARSE,
                    source="youthcenter",
                    started_at=now,
                    succeeded=80,
                    failed=20,
                ),
            ],
        )
        assert report.total_succeeded == 180
        assert report.total_failed == 20
