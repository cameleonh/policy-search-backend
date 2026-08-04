"""Tests for additional source adapters (Issues #5–#8, #11–#12)."""

from __future__ import annotations

from typing import Any

import pytest

from workers.ingest.additional_adapters import (
    BokjiroAdapter,
    FanfandaeroAdapter,
    Gov24Adapter,
    MyhomeAdapter,
    SeoulshinboAdapter,
    Work24Adapter,
    YwAdapter,
    normalize_bokjiro,
    normalize_fanfandaero,
    normalize_gov24,
    normalize_myhome,
    normalize_seoulshinbo,
    normalize_work24_event,
    normalize_work24_prgm,
    normalize_work24_train,
    normalize_yw,
)
from workers.ingest.source_definition import KNOWN_SOURCES
from workers.ingest.source_record import RecordStatus

# ── #5: 청년일경험 ──


class TestYw:
    def test_normalize(self) -> None:
        raw: dict[str, Any] = {
            "id": "PG001",
            "title": "청년 인턴십 프로그램",
            "url": "https://yw.work24.go.kr/d/a/selectWkexPrgmDetail.do?id=PG001",
            "운영기관": "한국산업인력공단",
            "지역": "서울특별시",
            "apply_start": "2026-01-01",
            "apply_end": "2026-06-30",
            "dday": "30",
        }
        rec = normalize_yw(raw)
        assert rec.source == "yw"
        assert rec.remote_id == "PG001"
        assert rec.title == "청년 인턴십 프로그램"
        assert rec.agency == "한국산업인력공단"
        assert rec.region == "서울특별시"

    def test_adapter_definition(self) -> None:
        adapter = YwAdapter()
        assert adapter.definition.source_key == "yw"
        assert "www.youthwork.go.kr" in adapter.definition.allowed_hosts


# ── #6: 고용24 ──


class TestWork24:
    def test_normalize_prgm(self) -> None:
        raw: dict[str, Any] = {
            "id": "ORGCD-2026-001",
            "title": "취업프로그램: 직무역량 강화",
            "url": "https://www.work24.go.kr/cm/empPrgm/detail?seq=001",
            "org": "서울고용노동청",
            "start": "2026-03-01",
            "end": "2026-03-31",
            "place": "서울특별시",
        }
        rec = normalize_work24_prgm(raw)
        assert rec.source == "work24"
        assert rec.remote_id == "ORGCD-2026-001"
        assert rec.title == "취업프로그램: 직무역량 강화"

    def test_normalize_train(self) -> None:
        raw: dict[str, Any] = {
            "id": "TRA001-TME001",
            "title": "K-디지털트레이닝: AI 개발자 양성",
            "url": "https://www.work24.go.kr/uat/kdt/detail?tracseId=TRA001",
            "org": "훈련기관",
            "start": "2026-01-15",
            "end": "2026-07-15",
            "region": "경기도",
        }
        rec = normalize_work24_train(raw)
        assert rec.remote_id == "TRA001-TME001"
        assert rec.region == "경기도"

    def test_normalize_event(self) -> None:
        raw: dict[str, Any] = {
            "id": "EVENT-001",
            "title": "2026 서울 잡페어",
            "url": "https://www.work24.go.kr/event/detail?no=001",
            "event_type": "잡페어",
            "start": "2026-04-01",
            "end": "2026-04-02",
            "region": "서울특별시",
        }
        rec = normalize_work24_event(raw)
        assert rec.remote_id == "EVENT-001"
        assert rec.title == "2026 서울 잡페어"

    def test_adapter_definition(self) -> None:
        adapter = Work24Adapter()
        assert adapter.definition.source_key == "work24"


# ── #7: 복지로 ──


class TestBokjiro:
    def test_normalize(self) -> None:
        raw: dict[str, Any] = {
            "WLFARE_INFO_ID": "WLF001",
            "WLFARE_INFO_NM": "청년 주거 지원",
            "SPRVSN_INST_CD_NM": "보건복지부",
            "enfc_start": "2026-01-01",
            "enfc_end": "2026-12-31",
            "addr": "전국",
            "tags": "주거,지원",
        }
        rec = normalize_bokjiro(raw)
        assert rec.source == "bokjiro"
        assert rec.remote_id == "WLF001"
        assert rec.title == "청년 주거 지원"
        assert rec.agency == "보건복지부"
        assert rec.target_category == "both"
        assert "주거" in rec.tags

    def test_no_eligibility_axes(self) -> None:
        """복지로 has no structured eligibility fields."""
        raw: dict[str, Any] = {"WLFARE_INFO_ID": "WLF002", "WLFARE_INFO_NM": "Test"}
        rec = normalize_bokjiro(raw)
        assert rec.raw.get("SPRT_TRGT_MIN_AGE") is None

    def test_adapter_definition(self) -> None:
        adapter = BokjiroAdapter()
        assert adapter.definition.source_key == "bokjiro"


# ── #8: 마이홈 ──


class TestMyhome:
    def test_normalize_rcrit(self) -> None:
        raw: dict[str, Any] = {
            "pblancId": "RCP001",
            "title": "2026년도 공공임대주택 입주자 모집공고",
            "url": "https://www.applyhome.co.kr/ai/aia/SEE/SelectRcritPblancDetail.do?pblancId=RCP001",
            "org": "한국토지주택공사",
            "status": "모집중",
            "region": "경기도",
        }
        rec = normalize_myhome(raw, kind="rcrit")
        assert rec.source == "myhome"
        assert rec.remote_id == "RCP001"
        assert rec.status == RecordStatus.OPEN

    def test_normalize_lttot(self) -> None:
        raw: dict[str, Any] = {
            "pblancId": "LTT001",
            "title": "2026년 분양주택 공고",
            "url": "https://example.com",
            "status": "모집중",
        }
        rec = normalize_myhome(raw, kind="lttot")
        assert rec.source == "myhome_lttot"
        assert rec.remote_id == "LTT001"

    def test_normalize_stock(self) -> None:
        raw: dict[str, Any] = {
            "hsmpSn": "STK001",
            "hsmpNm": "행복주택 임대재고",
            "url": "https://example.com",
        }
        rec = normalize_myhome(raw, kind="stock")
        assert rec.source == "myhome_stock"
        assert rec.remote_id == "STK001"
        assert rec.status == RecordStatus.UNKNOWN

    def test_normalize_wait(self) -> None:
        raw: dict[str, Any] = {
            "waitId": "WAIT001",
            "title": "입주대기 정보",
            "url": "https://example.com",
        }
        rec = normalize_myhome(raw, kind="wait")
        assert rec.source == "myhome_wait"
        assert rec.remote_id == "WAIT001"

    def test_adapter_definition(self) -> None:
        adapter = MyhomeAdapter(kind="rcrit")
        assert adapter.definition.source_key == "myhome"


# ── #11: 판판대로 ──


class TestFanfandaero:
    def test_normalize(self) -> None:
        raw: dict[str, Any] = {
            "source_id": "biz-2026-001",
            "title": "스타트업 지원사업",
            "url": "https://www.fanfandaero.kr/biz/001",
            "agency": "중소기업벤처기업부",
            "apply_start": "2026-02-01",
            "apply_end": "2026-04-30",
            "region_scope": "전국",
            "status": "접수중",
        }
        rec = normalize_fanfandaero(raw)
        assert rec.source == "fanfandaero"
        assert rec.remote_id == "biz-2026-001"
        assert rec.target_category == "business"
        assert rec.announce_no == "biz-2026-001"

    def test_adapter_definition(self) -> None:
        adapter = FanfandaeroAdapter()
        assert adapter.definition.source_key == "fanfandaero"


# ── #11: 서울신보 ──


class TestSeoulshinbo:
    def test_normalize(self) -> None:
        raw: dict[str, Any] = {
            "source_id": "SSB001",
            "title": "소상공인 특례보증",
            "url": "https://www.seoulshinbo.co.kr/board/001",
            "agency": "서울신용보증재단",
            "apply_start": "2026-03-01",
            "apply_end": "2026-06-30",
            "status": "접수중",
        }
        rec = normalize_seoulshinbo(raw)
        assert rec.source == "seoulshinbo"
        assert rec.remote_id == "SSB001"
        assert rec.region == "서울특별시"

    def test_adapter_definition(self) -> None:
        adapter = SeoulshinboAdapter()
        assert adapter.definition.source_key == "seoulshinbo"


# ── #12: 보조금24 ──


class TestGov24:
    def test_normalize(self) -> None:
        raw: dict[str, Any] = {
            "서비스ID": "SVC001",
            "서비스명": "청년 도약 계좌",
            "소관기관": "금융위원회",
            "url": "https://www.gov.kr/portal/service/SVC001",
        }
        rec = normalize_gov24(raw)
        assert rec.source == "gov24"
        assert rec.remote_id == "SVC001"
        assert rec.title == "청년 도약 계좌"
        assert rec.status == RecordStatus.ALWAYS_OPEN
        assert rec.announce_no == "SVC001"

    def test_adapter_definition(self) -> None:
        adapter = Gov24Adapter()
        assert adapter.definition.source_key == "gov24"
        assert "api.odcloud.kr" in adapter.definition.allowed_hosts


# ── Deterministic normalization ──


class TestDeterministic:
    @pytest.mark.parametrize(
        "normalize_fn,raw",
        [
            (normalize_yw, {"id": "T1", "title": "Test", "url": "https://example.com"}),
            (normalize_work24_prgm, {"id": "T1", "title": "Test", "url": "https://example.com"}),
            (normalize_bokjiro, {"WLFARE_INFO_ID": "T1", "WLFARE_INFO_NM": "Test"}),
            (normalize_fanfandaero, {"source_id": "T1", "title": "Test", "url": "https://e.com"}),
            (normalize_seoulshinbo, {"source_id": "T1", "title": "Test", "url": "https://e.com"}),
            (normalize_gov24, {"서비스ID": "T1", "서비스명": "Test"}),
        ],
        ids=["yw", "work24", "bokjiro", "fanfandaero", "seoulshinbo", "gov24"],
    )
    def test_same_input_same_output(self, normalize_fn: Any, raw: dict[str, Any]) -> None:
        a = normalize_fn(dict(raw))
        b = normalize_fn(dict(raw))
        assert a.remote_id == b.remote_id
        assert a.title == b.title
        assert a.source == b.source


# ── All source definitions exist ──


class TestSourceDefinitions:
    @pytest.mark.parametrize(
        "source_key",
        [
            "yw",
            "work24",
            "bokjiro",
            "myhome",
            "myhome_lttot",
            "myhome_stock",
            "myhome_wait",
            "fanfandaero",
            "seoulshinbo",
            "gov24",
        ],
    )
    def test_definition_exists(self, source_key: str) -> None:
        assert source_key in KNOWN_SOURCES
        src = KNOWN_SOURCES[source_key]
        assert src.allowed_hosts
        assert src.request_delay_seconds > 0
