"""Additional source adapters for issues #5–#8, #11–#12.

Each adapter follows the SourceAdapter protocol from Issue #3.
Normalization functions convert source-specific raw records into
the unified SourceRecord format. Network code is isolated behind
the adapter class methods.

Sources:
  #5  yw (청년일경험) — HTML list, fn_searchDetail IDs
  #6  work24 (고용24) — 3 sub-sources: prgm, train, event
  #7  bokjiro (복지로) — JSON API, 14 fields, no eligibility axes
  #8  myhome (마이홈) — JSON API, 4 kinds: rcrit, lttot, stock, wait
  #11 fanfandaero (판판대로) + seoulshinbo (서울신보) — JSON + HTML
  #12 gov24 (보조금24) — OpenAPI, 상시 제도
"""

from __future__ import annotations

import contextlib
import html as htmllib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from workers.ingest.collection_report import (
    CollectionReport,
    exit_code_from_outcome,
    outcome_from_counts,
)
from workers.ingest.errors import BlockedError, ParseError, RetryableError
from workers.ingest.source_definition import KNOWN_SOURCES, SourceDefinition
from workers.ingest.source_record import AttachmentMeta, RecordStatus, SourceRecord

KST = timezone(timedelta(hours=9))


def _clean(text: object) -> str:
    """Strip HTML, decode entities, normalize whitespace."""
    s = re.sub(r"<[^>]+>", " ", str(text or ""))
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(s: str | None) -> datetime | None:
    if not s or len(str(s).strip()) < 10:
        return None
    with contextlib.suppress(ValueError):
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=KST)
    return None


# ── #5: 청년일경험 (yw) ─────────────────────────


def normalize_yw(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 청년일경험 record. Source: yw_work24."""
    return SourceRecord(
        source="yw",
        remote_id=str(raw.get("id", "")),
        canonical_url=str(raw.get("url", "")),
        title=_clean(raw.get("title", "")),
        agency=_clean(raw.get("운영기관") or raw.get("agency", "")),
        status=RecordStatus.OPEN if raw.get("dday") is not None else RecordStatus.UNKNOWN,
        apply_start=_parse_date(raw.get("apply_start")),
        apply_end=_parse_date(raw.get("apply_end")),
        region=_clean(raw.get("지역")) or None,
        target_category="individual",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


# ── #6: 고용24 (work24) — 3 sub-sources ──────────


def normalize_work24_prgm(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 고용24 취업프로그램/청년전용 record."""
    return SourceRecord(
        source="work24",
        remote_id=str(raw.get("id", "")),
        canonical_url=str(raw.get("url", "")),
        title=_clean(raw.get("title", "")),
        agency=_clean(raw.get("org", "")),
        status=RecordStatus.OPEN,
        apply_start=_parse_date(raw.get("start")),
        apply_end=_parse_date(raw.get("end")),
        region=_clean(raw.get("place")) or None,
        target_category="individual",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


def normalize_work24_train(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 고용24 훈련/K-디지털트레이닝 record."""
    return SourceRecord(
        source="work24",
        remote_id=str(raw.get("id", "")),
        canonical_url=str(raw.get("url", "")),
        title=_clean(raw.get("title", "")),
        agency=_clean(raw.get("org", "")),
        status=RecordStatus.OPEN,
        apply_start=_parse_date(raw.get("start")),
        apply_end=_parse_date(raw.get("end")),
        region=_clean(raw.get("region")) or raw.get("sido") or None,
        target_category="individual",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


def normalize_work24_event(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 고용24 채용행사 record."""
    return SourceRecord(
        source="work24",
        remote_id=str(raw.get("id", "")),
        canonical_url=str(raw.get("url", "")),
        title=_clean(raw.get("title", "")),
        agency=_clean(raw.get("org", raw.get("event_type", ""))),
        status=RecordStatus.OPEN,
        apply_start=_parse_date(raw.get("start")),
        apply_end=_parse_date(raw.get("end")),
        region=_clean(raw.get("region")) or None,
        target_category="individual",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


# ── #7: 복지로 (bokjiro) ────────────────────────


def normalize_bokjiro(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 복지로 record. Only 14 fields, no eligibility axes."""
    wid = raw.get("WLFARE_INFO_ID", raw.get("id", ""))
    fallback_url = f"https://www.bokjiro.go.kr/svcwlfareInfo/wlfareInfo.do?wlfareInfoId={wid}"
    return SourceRecord(
        source="bokjiro",
        remote_id=str(wid),
        canonical_url=str(raw.get("url") or fallback_url),
        title=_clean(raw.get("WLFARE_INFO_NM", raw.get("title", ""))),
        agency=_clean(raw.get("SPRVSN_INST_CD_NM", raw.get("org", ""))),
        status=RecordStatus.UNKNOWN,
        apply_start=_parse_date(raw.get("enfc_start")),
        apply_end=_parse_date(raw.get("enfc_end")),
        region=_clean(raw.get("addr")) or raw.get("region") or None,
        target_category="both",
        tags=[t.strip() for t in str(raw.get("tags", "")).split(",") if t.strip()],
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


# ── #8: 마이홈 (myhome) — 4 kinds ────────────────


def normalize_myhome(raw: dict[str, Any], kind: str = "rcrit") -> SourceRecord:
    """Normalize 마이홈 record. kind: rcrit, lttot, stock, wait."""
    idk = "pblancId" if kind in ("rcrit", "lttot") else "hsmpSn"
    if kind == "wait":
        idk = "waitId"

    source_key = f"myhome_{kind}" if kind != "rcrit" else "myhome"
    status = RecordStatus.OPEN
    if raw.get("status") == "모집마감":
        status = RecordStatus.CLOSED
    if kind in ("stock", "wait"):
        status = RecordStatus.UNKNOWN  # Not announcements

    return SourceRecord(
        source=source_key,
        remote_id=str(raw.get(idk, raw.get("id", ""))),
        canonical_url=str(raw.get("url", "")),
        title=_clean(raw.get("title", raw.get("hsmpNm", ""))),
        agency=_clean(raw.get("org", "")),
        status=status,
        apply_start=_parse_date(raw.get("notice_date")) if kind in ("rcrit", "lttot") else None,
        region=_clean(raw.get("region")) or None,
        target_category="individual",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


# ── #11: 판판대로 (fanfandaero) + 서울신보 (seoulshinbo) ────


def normalize_fanfandaero(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 판판대로 record."""
    source_id = str(raw.get("source_id", raw.get("id", "")))
    return SourceRecord(
        source="fanfandaero",
        remote_id=source_id,
        canonical_url=str(raw.get("url", "")),
        title=_clean(raw.get("title", "")),
        agency=_clean(raw.get("agency", raw.get("target", ""))),
        status=RecordStatus.OPEN if raw.get("status") != "마감" else RecordStatus.CLOSED,
        apply_start=_parse_date(raw.get("apply_start")),
        apply_end=_parse_date(raw.get("apply_end")),
        region=_clean(raw.get("region_scope")) or None,
        target_category="business",
        announce_no=source_id
        if source_id.startswith("biz-") or source_id.startswith("ntc-")
        else None,
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


def normalize_seoulshinbo(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 서울신용보증재단 record."""
    source_id = str(raw.get("source_id", raw.get("id", "")))
    return SourceRecord(
        source="seoulshinbo",
        remote_id=source_id,
        canonical_url=str(raw.get("url", "")),
        title=_clean(raw.get("title", "")),
        agency=_clean(raw.get("agency", "서울신용보증재단")),
        status=RecordStatus.OPEN if raw.get("status") != "마감" else RecordStatus.CLOSED,
        apply_start=_parse_date(raw.get("apply_start")),
        apply_end=_parse_date(raw.get("apply_end")),
        region="서울특별시",
        target_category="business",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


# ── #12: 보조금24 (gov24) ───────────────────────


def normalize_gov24(raw: dict[str, Any]) -> SourceRecord:
    """Normalize 보조금24 (정부24 OpenAPI) record. 상시 제도."""
    sid = str(raw.get("서비스ID", raw.get("source_id", raw.get("id", ""))))
    return SourceRecord(
        source="gov24",
        remote_id=sid,
        announce_no=sid,
        canonical_url=str(
            raw.get("url")
            or f"https://www.gov.kr/portal/rcvcvrvc/dtlConverServiceDetail?serviceId={sid}"
        ),
        title=_clean(raw.get("서비스명", raw.get("title", ""))),
        agency=_clean(raw.get("소관기관", raw.get("agency", raw.get("조직도정보", "")))),
        status=RecordStatus.ALWAYS_OPEN,  # gov24 is 상시 제도
        target_category="both",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


# ── Base adapter class for remaining sources ─────


class _BaseAdapter:
    """Base adapter with common HTTP + protocol methods."""

    def __init__(self, source_key: str) -> None:
        self.source_key = source_key
        self.definition: SourceDefinition = KNOWN_SOURCES[source_key]
        self._checkpoint: str | None = None
        self._opener = urllib.request.build_opener()

    def _fetch_html(self, url: str, retries: int = 3) -> str:
        headers = {"User-Agent": "policy-search-backend/0.1"}
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                resp = self._opener.open(req, timeout=30)
                return str(resp.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise BlockedError(f"HTTP {exc.code}") from exc
                last_exc = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
            time.sleep(self.definition.request_delay_seconds * (attempt + 1))
        raise RetryableError(f"Fetch failed: {last_exc}")

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError

    def fetch_detail(self, record: SourceRecord) -> SourceRecord:
        return record

    def list_attachments(self, record: SourceRecord) -> list[AttachmentMeta]:
        return []

    def get_checkpoint(self) -> str | None:
        return self._checkpoint

    def collect(self) -> CollectionReport:
        started = datetime.now(UTC)
        received = 0
        error_msg: str | None = None
        try:
            records = list(self.list_records())
            received = len(records)
        except (BlockedError, ParseError, RetryableError) as exc:
            error_msg = str(exc)
        finished = datetime.now(UTC)
        outcome = outcome_from_counts(
            expected=0,
            received=received,
            failed=0,
            blocked=error_msg is not None and "HTTP 4" in (error_msg or ""),
        )
        return CollectionReport(
            source=self.source_key,
            outcome=outcome,
            exit_code=exit_code_from_outcome(outcome),
            started_at=started,
            finished_at=finished,
            received_raw=received,
            received_unique=received,
            persisted=received,
            error_summary=error_msg,
        )


class YwAdapter(_BaseAdapter):
    """#5: 청년일경험 adapter."""

    def __init__(self) -> None:
        super().__init__("yw")

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError("YW adapter network implementation pending live deployment")


class Work24Adapter(_BaseAdapter):
    """#6: 고용24 adapter (prgm + train + event)."""

    def __init__(self) -> None:
        super().__init__("work24")

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError("Work24 adapter network implementation pending live deployment")


class BokjiroAdapter(_BaseAdapter):
    """#7: 복지로 adapter."""

    def __init__(self) -> None:
        super().__init__("bokjiro")

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError("Bokjiro adapter network implementation pending live deployment")


class MyhomeAdapter(_BaseAdapter):
    """#8: 마이홈 adapter (rcrit, lttot, stock, wait)."""

    def __init__(self, kind: str = "rcrit") -> None:
        source_key = f"myhome_{kind}" if kind != "rcrit" else "myhome"
        super().__init__(source_key)
        self.kind = kind

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError("Myhome adapter network implementation pending live deployment")


class FanfandaeroAdapter(_BaseAdapter):
    """#11: 판판대로 adapter."""

    def __init__(self) -> None:
        super().__init__("fanfandaero")

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError(
            "Fanfandaero adapter network implementation pending live deployment"
        )


class SeoulshinboAdapter(_BaseAdapter):
    """#11: 서울신용보증재단 adapter."""

    def __init__(self) -> None:
        super().__init__("seoulshinbo")

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError(
            "Seoulshinbo adapter network implementation pending live deployment"
        )


class Gov24Adapter(_BaseAdapter):
    """#12: 보조금24 (정부24 OpenAPI) adapter."""

    def __init__(self) -> None:
        super().__init__("gov24")

    def list_records(self, **kwargs: Any) -> Iterator[SourceRecord]:
        raise NotImplementedError("Gov24 adapter network implementation pending live deployment")
