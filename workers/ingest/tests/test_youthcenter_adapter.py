"""Parser and contract tests for the 온통청년 adapter (Issue #4).

All tests are network-free — they use JSON fixtures that mirror the
79-field 온통청년 response shape.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from workers.ingest.errors import BlockedError, ParseError, RetryableError
from workers.ingest.region_util import canon_region
from workers.ingest.source_record import RecordStatus
from workers.ingest.youthcenter_adapter import (
    YouthcenterAdapter,
    normalize_youthcenter,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


@pytest.fixture
def raw_open() -> dict[str, Any]:
    return _load("youthcenter_raw_open.json")


@pytest.fixture
def raw_always_open() -> dict[str, Any]:
    return _load("youthcenter_raw_always_open.json")


@pytest.fixture
def raw_closed() -> dict[str, Any]:
    return _load("youthcenter_raw_closed.json")


# ── Completion criterion: DOCID, title, agency, period, region, eligibility ──


class TestFieldMapping:
    def test_docid_mapped_to_remote_id(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.remote_id == "PLCY0001"

    def test_title_stripped_and_clean(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.title == "청년 도전 지원사업"

    def test_agency_from_supervising_inst(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.agency == "중소기업벤처기업부"

    def test_canonical_url_built_from_docid(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.canonical_url == (
            "https://www.youthcenter.go.kr/youthPolicy/ythPlcyDetail?plcyNo=PLCY0001"
        )

    def test_apply_dates_parsed(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.apply_start == datetime.fromisoformat("2026-01-15")
        assert rec.apply_end == datetime.fromisoformat("2026-12-31")

    def test_zero_dates_become_none(self, raw_always_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_always_open)
        assert rec.apply_start is None
        assert rec.apply_end is None

    def test_status_open(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.status == RecordStatus.OPEN

    def test_status_always_open(self, raw_always_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_always_open)
        assert rec.status == RecordStatus.ALWAYS_OPEN

    def test_status_closed(self, raw_closed: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_closed)
        assert rec.status == RecordStatus.CLOSED

    def test_region_canonicalized(self, raw_always_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_always_open)
        assert rec.region == "서울특별시"

    def test_eligibility_axes_preserved_in_raw(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.raw["SPRT_TRGT_MIN_AGE"] == "19"
        assert rec.raw["SPRT_TRGT_MAX_AGE"] == "39"
        assert rec.raw["EARN_MIN_AMT"] == "0"
        assert rec.raw["EARN_MAX_AMT"] == "50000000"
        assert rec.raw["MRG_STTS_NM"] == "미혼"
        assert rec.raw["QLFC_ACBG_NM"] == "대학교 재학"
        assert rec.raw["EMPM_STTS_NM"] == "미취업"

    def test_raw_preserved_with_all_fields(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.raw["DOCID"] == "PLCY0001"
        assert rec.raw["PLCY_NM"] == "청년 도전 지원사업"
        assert rec.raw["PVSN_INST_GROUP_CD"] == "0054001"

    def test_source_is_youthcenter(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.source == "youthcenter"


# ── Completion criterion: empty eligibility axes not treated as unlimited ──


class TestEligibilityHandling:
    def test_empty_axis_preserved_as_empty_string(self, raw_open: dict[str, Any]) -> None:
        """MJR_CND_NM is empty — it must NOT be inferred as 'unlimited'."""
        rec = normalize_youthcenter(raw_open)
        assert rec.raw["MJR_CND_NM"] == ""
        # The raw is preserved verbatim — no inference

    def test_income_axes_preserved_verbatim(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        assert rec.raw["EARN_MIN_AMT"] == "0"
        assert rec.raw["EARN_MAX_AMT"] == "50000000"


# ── Completion criterion: deterministic normalization ──


class TestDeterministic:
    def test_same_input_same_output(self, raw_open: dict[str, Any]) -> None:
        a = normalize_youthcenter(raw_open)
        b = normalize_youthcenter(raw_open)
        assert a.remote_id == b.remote_id
        assert a.title == b.title
        assert a.status == b.status
        assert a.canonical_url == b.canonical_url


# ── Completion criterion: open-only filter ──


class TestOpenOnlyFilter:
    def test_closed_excluded(
        self,
        raw_open: dict[str, Any],
        raw_closed: dict[str, Any],
    ) -> None:
        records = [normalize_youthcenter(raw_open), normalize_youthcenter(raw_closed)]
        open_only = [r for r in records if r.status != RecordStatus.CLOSED]
        assert len(open_only) == 1
        assert open_only[0].remote_id == "PLCY0001"


# ── Region canonicalization ──


class TestRegionCanon:
    def test_jeonnam_canonicalized(self) -> None:
        assert canon_region("전라남도") == "전남광주통합특별시"

    def test_gwangju_canonicalized(self) -> None:
        assert canon_region("광주광역시") == "전남광주통합특별시"

    def test_gangwon_canonicalized(self) -> None:
        assert canon_region("강원도") == "강원특별자치도"

    def test_jeju_canonicalized(self) -> None:
        assert canon_region("제주도") == "제주특별자치도"

    def test_seoul_stays(self) -> None:
        assert canon_region("서울특별시") == "서울특별시"

    def test_unknown_passes_through(self) -> None:
        assert canon_region("대전광역시") == "대전광역시"


# ── Adapter protocol conformance ──


class TestAdapterConformance:
    def test_adapter_has_definition(self) -> None:
        adapter = YouthcenterAdapter()
        assert adapter.definition.source_key == "youthcenter"

    def test_adapter_has_allowed_hosts(self) -> None:
        adapter = YouthcenterAdapter()
        assert "www.youthcenter.go.kr" in adapter.definition.allowed_hosts

    def test_list_attachments_returns_empty(self, raw_open: dict[str, Any]) -> None:

        rec = normalize_youthcenter(raw_open)
        adapter = YouthcenterAdapter()
        assert adapter.list_attachments(rec) == []

    def test_fetch_detail_returns_record_unchanged(self, raw_open: dict[str, Any]) -> None:
        rec = normalize_youthcenter(raw_open)
        adapter = YouthcenterAdapter()
        detail = adapter.fetch_detail(rec)
        assert detail.remote_id == rec.remote_id
        assert detail.title == rec.title


# ── Re-processing idempotency ──


class TestIdempotency:
    def test_same_raw_produces_same_content(self, raw_open: dict[str, Any]) -> None:
        """Re-processing the same response must not create a new version."""
        a = normalize_youthcenter(raw_open)
        b = normalize_youthcenter(raw_open)
        # Content is identical — no new policy version should be generated
        assert a.remote_id == b.remote_id
        assert a.title == b.title
        assert a.canonical_url == b.canonical_url
        assert a.raw == b.raw


# ── Outcome classification for total mismatch ──


class TestOutcomeOnTotalMismatch:
    def test_zero_received_when_total_positive_is_failed(self) -> None:
        from workers.ingest.collection_report import (
            CollectionOutcome,
            outcome_from_counts,
        )

        outcome = outcome_from_counts(expected=2650, received=0, failed=0)
        assert outcome == CollectionOutcome.FAILED

    def test_partial_when_received_less_than_total(self) -> None:
        from workers.ingest.collection_report import (
            CollectionOutcome,
            outcome_from_counts,
        )

        outcome = outcome_from_counts(expected=2650, received=2600, failed=50)
        assert outcome == CollectionOutcome.PARTIAL

    def test_success_when_received_equals_expected(self) -> None:
        from workers.ingest.collection_report import (
            CollectionOutcome,
            outcome_from_counts,
        )

        outcome = outcome_from_counts(expected=2650, received=2650, failed=0)
        assert outcome == CollectionOutcome.SUCCESS


# ── Error types exist and are importable ──


class TestErrorTypes:
    def test_blocked_error_importable(self) -> None:
        assert issubclass(BlockedError, Exception)

    def test_parse_error_importable(self) -> None:
        assert issubclass(ParseError, Exception)

    def test_retryable_error_importable(self) -> None:
        assert issubclass(RetryableError, Exception)


# ── HTML stripping ──


class TestHtmlStripping:
    def test_title_with_html_entities(self) -> None:
        raw = {
            "DOCID": "TEST001",
            "PLCY_NM": "<b>청년 정책</b> &amp; 지원",
            "APLY_PRD_SE_CD": "진행중",
        }
        rec = normalize_youthcenter(raw)
        assert rec.title == "청년 정책 & 지원"

    def test_agency_with_tags(self) -> None:
        raw = {
            "DOCID": "TEST002",
            "PLCY_NM": "Test",
            "SPRVSN_INST_CD_NM": "<span>기획재정부</span>",
            "APLY_PRD_SE_CD": "진행중",
        }
        rec = normalize_youthcenter(raw)
        assert rec.agency == "기획재정부"
