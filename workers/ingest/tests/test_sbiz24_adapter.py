"""Parser and contract tests for the 소상공인24 adapter (Issue #9).

All tests are network-free — they use JSON fixtures mirroring the
sbiz24.kr API response shapes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from workers.ingest.errors import BlockedError, ParseError, RetryableError
from workers.ingest.sbiz24_adapter import (
    Sbiz24Adapter,
    content_hash_of,
    normalize_combine,
    normalize_pbanc,
)
from workers.ingest.source_record import RecordStatus

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


@pytest.fixture
def pbanc_item() -> dict[str, Any]:
    return _load("sbiz24_pbanc_item.json")


@pytest.fixture
def combine_pbln_item() -> dict[str, Any]:
    return _load("sbiz24_combine_pbln_item.json")


@pytest.fixture
def combine_local_item() -> dict[str, Any]:
    return _load("sbiz24_combine_local_item.json")


# ── pbanc normalization ──


class TestPbancNormalization:
    def test_source_is_sbiz24(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.source == "sbiz24"

    def test_source_id_from_pbancSn(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.remote_id == "100001"

    def test_canonical_url(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.canonical_url == "https://www.sbiz24.kr/#/pbanc/100001"

    def test_title_normalized(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.title == "소상공인 경영안정 자금 지원"

    def test_agency_from_departNm(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.agency == "소상공인시장진흥공단"

    def test_apply_dates_parsed(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.apply_start is not None
        assert rec.apply_end is not None

    def test_status_open(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.status == RecordStatus.OPEN

    def test_tags_parsed(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert "경영안정" in rec.tags
        assert "자금지원" in rec.tags

    def test_raw_preserved(self, pbanc_item: dict[str, Any]) -> None:
        rec = normalize_pbanc(pbanc_item)
        assert rec.raw["rcrtTypeCdNm"] == "지원자금"
        assert rec.raw["pbancGubun"] == "A"


# ── combine normalization ──


class TestCombineNormalization:
    def test_source_is_sbiz24_combine(self, combine_pbln_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_pbln_item)
        assert rec.source == "sbiz24_combine"

    def test_pbln_id_in_remote_id(self, combine_pbln_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_pbln_item)
        assert rec.remote_id == "PBLN20260001"

    def test_pbln_announce_no_set(self, combine_pbln_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_pbln_item)
        assert rec.announce_no == "PBLN20260001"

    def test_pbln_canonical_url_uses_extldPbanc(self, combine_pbln_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_pbln_item)
        assert "/extldPbanc/" in rec.canonical_url

    def test_local_gov_canonical_url_uses_pbanc(self, combine_local_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_local_item)
        assert "/#/pbanc/" in rec.canonical_url

    def test_local_gov_no_announce_no(self, combine_local_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_local_item)
        assert rec.announce_no is None

    def test_combine_status_closed(self, combine_local_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_local_item)
        assert rec.status == RecordStatus.CLOSED


# ── sbiz24 vs combine ID collision prevention ──


class TestIdCollisionPrevention:
    def test_same_sn_different_source_keys(self, pbanc_item: dict[str, Any]) -> None:
        """sbiz24 and sbiz24_combine with same numeric ID must not collide."""
        pbanc_rec = normalize_pbanc(pbanc_item)

        # Simulate a combine item with same numeric sn
        combine_data = {**pbanc_item, "pbancId": "100001"}
        combine_rec = normalize_combine(combine_data)

        # Different source keys → no collision
        assert pbanc_rec.source != combine_rec.source
        assert (pbanc_rec.source, pbanc_rec.remote_id) != (
            combine_rec.source,
            combine_rec.remote_id,
        )


# ── PBLN cross-source routing ──


class TestPblnRouting:
    def test_pbln_record_has_announce_no(self, combine_pbln_item: dict[str, Any]) -> None:
        rec = normalize_combine(combine_pbln_item)
        assert rec.announce_no is not None
        assert rec.announce_no.startswith("PBLN")

    def test_pbln_detail_raises_value_error(self, combine_pbln_item: dict[str, Any]) -> None:
        """PBLN records must be routed to bizinfo, not sbiz24 detail."""
        rec = normalize_combine(combine_pbln_item)
        adapter = Sbiz24Adapter(mode="combine")
        with pytest.raises(ValueError, match="bizinfo"):
            adapter.fetch_detail(rec)


# ── Identity mismatch detection ──


class TestIdentityMismatch:
    def test_adapter_validates_mode(self) -> None:
        with pytest.raises(ValueError, match="Invalid mode"):
            Sbiz24Adapter(mode="invalid")

    def test_adapter_has_correct_definition(self) -> None:
        pbanc = Sbiz24Adapter(mode="pbanc")
        assert pbanc.definition.source_key == "sbiz24"

        combine = Sbiz24Adapter(mode="combine")
        assert combine.definition.source_key == "sbiz24_combine"

    def test_allowed_hosts_enforced(self) -> None:
        adapter = Sbiz24Adapter()
        assert adapter._host_ok("https://www.sbiz24.kr/api/test")
        assert adapter._host_ok("https://sbiz24.kr/api/test")
        assert not adapter._host_ok("https://evil.com/api/test")


# ── Content hash ──


class TestContentHash:
    def test_hash_deterministic(self) -> None:
        body = "test body"
        attachments = ["sha1", "sha2"]
        h1 = content_hash_of(body, attachments)
        h2 = content_hash_of(body, attachments)
        assert h1 == h2

    def test_hash_changes_on_attachment_change(self) -> None:
        body = "test body"
        h1 = content_hash_of(body, ["sha1", "sha2"])
        h2 = content_hash_of(body, ["sha1", "sha3"])
        assert h1 != h2

    def test_hash_independent_of_attachment_order(self) -> None:
        body = "test body"
        h1 = content_hash_of(body, ["sha2", "sha1"])
        h2 = content_hash_of(body, ["sha1", "sha2"])
        assert h1 == h2

    def test_hash_changes_on_body_change(self) -> None:
        attachments = ["sha1"]
        h1 = content_hash_of("body A", attachments)
        h2 = content_hash_of("body B", attachments)
        assert h1 != h2


# ── Deterministic normalization ──


class TestDeterministic:
    def test_pbanc_same_input_same_output(self, pbanc_item: dict[str, Any]) -> None:
        a = normalize_pbanc(pbanc_item)
        b = normalize_pbanc(dict(pbanc_item))
        assert a.remote_id == b.remote_id
        assert a.title == b.title
        assert a.canonical_url == b.canonical_url

    def test_combine_same_input_same_output(self, combine_pbln_item: dict[str, Any]) -> None:
        a = normalize_combine(combine_pbln_item)
        b = normalize_combine(dict(combine_pbln_item))
        assert a.remote_id == b.remote_id
        assert a.announce_no == b.announce_no


# ── Status mapping ──


class TestStatusMapping:
    def test_status_closed_from_aply_n(self) -> None:
        item = {"aplyPsbltySe": "N", "pbancNm": "Test"}
        from workers.ingest.sbiz24_adapter import _map_status

        assert _map_status(item) == RecordStatus.CLOSED

    def test_status_always_open(self) -> None:
        item = {"aplyPsbltySe": "상시신청", "pbancNm": "Test"}
        from workers.ingest.sbiz24_adapter import _map_status

        assert _map_status(item) == RecordStatus.ALWAYS_OPEN

    def test_status_unknown_on_empty(self) -> None:
        item = {"aplyPsbltySe": "", "pbancNm": "Test"}
        from workers.ingest.sbiz24_adapter import _map_status

        assert _map_status(item) == RecordStatus.UNKNOWN


# ── Checkpoint ──


class TestCheckpoint:
    def test_checkpoint_none_by_default(self) -> None:
        adapter = Sbiz24Adapter()
        assert adapter.get_checkpoint() is None


# ── Error types importable ──


class TestErrorTypes:
    def test_blocked_error_importable(self) -> None:
        assert issubclass(BlockedError, Exception)

    def test_parse_error_importable(self) -> None:
        assert issubclass(ParseError, Exception)

    def test_retryable_error_importable(self) -> None:
        assert issubclass(RetryableError, Exception)
