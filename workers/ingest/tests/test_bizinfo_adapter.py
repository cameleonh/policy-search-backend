"""Parser and contract tests for the 기업마당 (bizinfo) adapter (Issue #10).

All tests are network-free — they use HTML fixtures mirroring the
bizinfo.go.kr page structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workers.ingest.bizinfo_adapter import (
    BizinfoAdapter,
    content_hash_v2,
    content_hash_v3,
    extract_body_text,
    extract_last_page,
    normalize_bizinfo,
    parse_bizinfo_list_page,
    parse_total_count,
)
from workers.ingest.source_record import RecordStatus

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def list_html() -> str:
    return (FIXTURES / "bizinfo_list_page.html").read_text(encoding="utf-8")


# ── List page parsing ──


class TestListParsing:
    def test_parses_two_records(self, list_html: str) -> None:
        records, has_more = parse_bizinfo_list_page(list_html)
        assert len(records) == 2
        assert has_more is True

    def test_pbln_ids_extracted(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        ids = {r.remote_id for r in records}
        assert ids == {"PBLN_202600001", "PBLN_202600002"}

    def test_titles_clean(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        assert records[0].title == "소상공인 경영안정 자금 지원"
        assert records[1].title == "청년 창업 지원사업"

    def test_canonical_urls(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        assert "pblancId=PBLN_202600001" in records[0].canonical_url
        assert "pblancId=PBLN_202600002" in records[1].canonical_url

    def test_announce_no_equals_pbln_id(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        for r in records:
            assert r.announce_no == r.remote_id

    def test_agency_from_departments(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        assert "중소기업벤처기업부" in records[0].agency
        assert "소상공인시장진흥공단" in records[0].agency

    def test_apply_dates_parsed(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        assert records[0].apply_start is not None
        assert records[0].apply_end is not None

    def test_tags_from_field(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        assert "지원자금" in records[0].tags
        assert "창업지원" in records[1].tags

    def test_source_is_bizinfo(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        assert all(r.source == "bizinfo" for r in records)

    def test_raw_preserves_field_and_reg_date(self, list_html: str) -> None:
        records, _ = parse_bizinfo_list_page(list_html)
        assert records[0].raw["field"] == "지원자금"
        assert records[0].raw["reg_date"] == "2026-01-01"


# ── Total count and pagination ──


class TestTotalCount:
    def test_total_count_from_hashall(self) -> None:
        html = '분야(2,650) 공고보기" id="hashAll"'
        assert parse_total_count(html) == 2650

    def test_total_count_fallback_max(self) -> None:
        html = "분야(100) 공고보기 분야(200) 공고보기"
        assert parse_total_count(html) == 200

    def test_total_count_none_on_missing(self) -> None:
        assert parse_total_count("<html>no counts</html>") is None

    def test_last_page_extraction(self) -> None:
        html = '<a href="?cpage=1">1</a><a href="?cpage=5">5</a><a href="?cpage=3">3</a>'
        assert extract_last_page(html) == 5

    def test_last_page_zero_on_missing(self) -> None:
        assert extract_last_page("<html>no pages</html>") == 0


# ── Body extraction ──


class TestBodyExtraction:
    def test_extracts_from_view_cont(self) -> None:
        html = (
            "<html><body>"
            '<div class="view_cont">지원 내용입니다.</div>'
            '<div id="footer">footer</div>'
            "</body></html>"
        )
        text = extract_body_text(html)
        assert "지원 내용입니다." in text
        assert "footer" not in text

    def test_extracts_from_print_area(self) -> None:
        html = '<html><body><div id="print_area">내용</div><footer>foot</footer></body></html>'
        text = extract_body_text(html)
        assert "내용" in text

    def test_fallback_on_missing_markers(self) -> None:
        html = "<html><body><p>전체 본문</p></body></html>"
        text = extract_body_text(html)
        assert "전체 본문" in text


# ── Content hash ──


class TestContentHash:
    def test_v2_deterministic(self) -> None:
        assert content_hash_v2("body") == content_hash_v2("body")

    def test_v2_changes_on_body(self) -> None:
        assert content_hash_v2("A") != content_hash_v2("B")

    def test_v3_deterministic(self) -> None:
        h1 = content_hash_v3("body", ["sha1", "sha2"])
        h2 = content_hash_v3("body", ["sha1", "sha2"])
        assert h1 == h2

    def test_v3_order_independent(self) -> None:
        h1 = content_hash_v3("body", ["sha2", "sha1"])
        h2 = content_hash_v3("body", ["sha1", "sha2"])
        assert h1 == h2

    def test_v3_changes_on_attachment(self) -> None:
        h1 = content_hash_v3("body", ["sha1"])
        h2 = content_hash_v3("body", ["sha2"])
        assert h1 != h2

    def test_v2_neq_v3(self) -> None:
        assert content_hash_v2("body") != content_hash_v3("body", ["sha1"])


# ── Adapter conformance ──


class TestAdapterConformance:
    def test_has_definition(self) -> None:
        adapter = BizinfoAdapter()
        assert adapter.definition.source_key == "bizinfo"

    def test_allowed_hosts(self) -> None:
        adapter = BizinfoAdapter()
        assert adapter._host_ok("https://www.bizinfo.go.kr/test")
        assert adapter._host_ok("https://bizinfo.go.kr/test")
        assert not adapter._host_ok("https://evil.com/test")

    def test_checkpoint_none(self) -> None:
        adapter = BizinfoAdapter()
        assert adapter.get_checkpoint() is None


# ── Normalize function ──


class TestNormalize:
    def test_normalize_full_record(self) -> None:
        rec = normalize_bizinfo(
            pblanc_id="PBLN_001",
            title="Test Policy",
            agency="Test Agency",
            apply_start="2026-01-01",
            apply_end="2026-12-31",
            field="지원자금",
            reg_date="2026-01-01",
        )
        assert rec.source == "bizinfo"
        assert rec.remote_id == "PBLN_001"
        assert rec.announce_no == "PBLN_001"
        assert rec.target_category == "business"
        assert "지원자금" in rec.tags


# ── Status mapping ──


class TestStatusMapping:
    def test_open_when_future(self) -> None:
        from workers.ingest.bizinfo_adapter import _map_status

        assert _map_status("2099-12-31") == RecordStatus.OPEN

    def test_closed_when_past(self) -> None:
        from workers.ingest.bizinfo_adapter import _map_status

        assert _map_status("2020-01-01") == RecordStatus.CLOSED

    def test_unknown_when_empty(self) -> None:
        from workers.ingest.bizinfo_adapter import _map_status

        assert _map_status("") == RecordStatus.UNKNOWN


# ── Deterministic normalization ──


class TestDeterministic:
    def test_same_html_same_output(self, list_html: str) -> None:
        a, _ = parse_bizinfo_list_page(list_html)
        b, _ = parse_bizinfo_list_page(list_html)
        for ra, rb in zip(a, b, strict=True):
            assert ra.remote_id == rb.remote_id
            assert ra.title == rb.title
            assert ra.canonical_url == rb.canonical_url


# ── Cross-source dedup with sbiz24 ──


class TestCrossSourceDedup:
    def test_bizinfo_pbln_matches_combine_pbln(self) -> None:
        """bizinfo PBLN_001 and sbiz24_combine PBLN_001 should be
        detectable as cross-source duplicates via announce_no+agency."""
        from workers.ingest.dedup import find_duplicates
        from workers.ingest.sbiz24_adapter import normalize_combine

        bizinfo_rec = normalize_bizinfo(
            pblanc_id="PBLN_001",
            title="Test",
            agency="중소기업벤처기업부",
            apply_start="2026-01-01",
            apply_end="2026-06-30",
        )
        combine_data = {
            "pbancId": "PBLN_001",
            "pbancNm": "Test",
            "departNm": "중소기업벤처기업부",
            "aplyPd": "2026-01-01 ~ 2026-06-30",
            "aplyPsbltySe": "Y",
        }
        combine_rec = normalize_combine(combine_data)

        dups = find_duplicates([bizinfo_rec, combine_rec])
        assert len(dups) >= 1
        strategies = {d.strategy for d in dups}
        assert "announce_no+agency" in strategies
