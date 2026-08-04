"""소상공인24(sbiz24.kr) ingestion adapter.

Implements the SourceAdapter protocol for both the 소진공 공고 (pbanc)
and 통합조회 (combine) APIs. Ports the network/parsing contract from
sole-search's sbiz_crawl.py at commit f6fd9e8.

Key safety features:
  - sbiz24 and sbiz24_combine use distinct source keys to prevent ID collision
  - PBLN_* IDs from combine are flagged for bizinfo cross-source routing
  - Detail identity mismatch (wrong announcement returned) is detected
  - Allowed hosts enforcement with no-redirect policy
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
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
from workers.ingest.source_record import (
    AttachmentMeta,
    RecordStatus,
    SourceRecord,
)

SBIZ24_BASE = "https://www.sbiz24.kr"
PBANC_LIST_URL = "/api/pbanc/sbiz24PbancList"
COMBINE_LIST_URL = "/api/combinePbanc/list"
PBANC_DETAIL_URL = "/api/pbanc/{sn}"
ATTACH_LIST_URL = "/api/cmmn/file"

ALLOWED_HOSTS = ("www.sbiz24.kr", "sbiz24.kr")
KST = timezone(timedelta(hours=9))
MAX_LIST_COUNT = 5000
DEFAULT_PAGE_SIZE = 100

_EMPTY_SEARCH: dict[str, Any] = {
    "searchValue": "",
    "rcrtTypeCdNmList": [],
    "rcrtTypeCdNmListDisplay": "",
    "regionNmList": [],
    "regionNmListDisplay": "",
    "tpbizCdList": [],
    "tpbizCdListDisplay": "",
    "bhis": {"from": None, "to": None},
    "wrkr": {"from": None, "to": None},
    "sls": {"from": None, "to": None},
    "aplySeYn": "N",
    "sbrPbancYn": "N",
    "itrstPbancYn": "N",
    "departNmList": None,
    "searchBox": None,
    "departNmListDisplay": "",
    "ptPbancSortBy": None,
    "pbancNm": None,
    "regionCdList": [],
}


def _strip_html(text: str | None) -> str:
    """Strip HTML tags, decode entities, normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(title or "")).strip()


def _period(p: Any) -> tuple[str | None, str | None]:
    if not isinstance(p, dict):
        return None, None
    return p.get("from") or None, p.get("to") or None


def _map_status(item: dict[str, Any]) -> RecordStatus:
    """Map site status expressions to RecordStatus enum.

    Never guesses — unknown → UNKNOWN, not OPEN.
    """
    aply = str(item.get("aplyPsbltySe") or "")
    if aply in ("Y", "신청가능"):
        return RecordStatus.OPEN
    if aply in ("N", "신청불가", "마감"):
        return RecordStatus.CLOSED
    if "상시" in aply:
        return RecordStatus.ALWAYS_OPEN
    if "예산" in aply or "소진" in aply:
        return RecordStatus.CLOSED

    end = _period(item.get("rcptPd"))[1] if item.get("rcptPd") else None
    if end is None and item.get("aplyPd"):
        parts = str(item.get("aplyPd")).split("~")
        end = parts[1].strip() if len(parts) == 2 and len(parts[1].strip()) >= 10 else None
    if end:
        with contextlib.suppress(ValueError):
            end_d = datetime.strptime(str(end)[:10], "%Y-%m-%d").replace(tzinfo=KST)
            now_kst = datetime.now(KST)
            return (
                RecordStatus.OPEN if end_d >= now_kst - timedelta(days=1) else RecordStatus.CLOSED
            )
    return RecordStatus.UNKNOWN


def normalize_pbanc(item: dict[str, Any]) -> SourceRecord:
    """Convert a pbanc list item to SourceRecord."""
    sn = str(item.get("pbancSn") or "")
    start, end = _period(item.get("rcptPd"))

    return SourceRecord(
        source="sbiz24",
        remote_id=sn,
        canonical_url=f"{SBIZ24_BASE}/#/pbanc/{sn}",
        title=_norm_title(item.get("pbancNm")),
        agency=item.get("departNm") or "소상공인시장진흥공단",
        status=_map_status(item),
        apply_start=_parse_iso_date(start),
        apply_end=_parse_iso_date(end),
        region=item.get("regionNmList") or "전국",
        target_category="business",
        tags=[s.strip() for s in str(item.get("hstgNm") or "").split(",") if s.strip()],
        crawled_at=datetime.now(UTC),
        raw={
            k: item[k]
            for k in ("rcrtTypeCdNm", "bizType", "pbancKindCd", "pbancGubun", "bizYr")
            if item.get(k) is not None
        },
    )


def normalize_combine(item: dict[str, Any]) -> SourceRecord:
    """Convert a combine list item to SourceRecord.

    PBLN_* IDs are flagged via announce_no for bizinfo cross-source routing.
    """
    pid = str(item.get("pbancId") or item.get("pbancSn") or "")
    gubun = str(item.get("pbancGubun") or "")
    aply_pd = str(item.get("aplyPd") or "")
    parts = [p.strip() for p in aply_pd.split("~")] if "~" in aply_pd else [None, None]

    if pid.startswith("PBLN"):
        curl = f"{SBIZ24_BASE}/#/extldPbanc/{pid}"
    elif gubun == "C":
        curl = f"{SBIZ24_BASE}/#/loanProduct/{pid}"
    else:
        curl = f"{SBIZ24_BASE}/#/pbanc/{pid}"

    record = SourceRecord(
        source="sbiz24_combine",
        remote_id=pid,
        canonical_url=curl,
        title=_norm_title(item.get("pbancNm")),
        agency=item.get("departNm") or item.get("rcrtTypeCdNm") or "미상",
        status=_map_status(item),
        apply_start=_parse_iso_date(parts[0] if len(parts) == 2 else None),
        apply_end=_parse_iso_date(parts[1] if len(parts) == 2 else None),
        region=item.get("regionNmList") or "전국",
        target_category="business",
        announce_no=pid if pid.startswith("PBLN") else None,
        tags=[s.strip() for s in str(item.get("hstgNm") or "").split(",") if s.strip()],
        crawled_at=datetime.now(UTC),
        raw={
            k: item[k]
            for k in ("rcrtTypeCdNm", "bizType", "pbancKindCd", "pbancGubun", "bizYr")
            if item.get(k) is not None
        },
    )
    return record


def _parse_iso_date(s: str | None) -> datetime | None:
    if not s or len(str(s).strip()) < 10:
        return None
    with contextlib.suppress(ValueError):
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=KST)
    return None


def content_hash_of(body_text: str, attachment_hashes: list[str]) -> str:
    """Content hash v3: body + sorted attachment SHA-256 hashes."""
    payload = body_text + "\n" + "\n".join(sorted(attachment_hashes))
    return hashlib.sha256(payload.encode()).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Sbiz24Adapter:
    """Adapter for 소상공인24 (sbiz24.kr) — pbanc + combine.

    Implements the SourceAdapter protocol. Two modes:
      - pbanc: 소진공 자체 공고
      - combine: 통합조회 (지자체·유관기관 포함)
    """

    def __init__(
        self,
        *,
        mode: str = "pbanc",
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if mode not in ("pbanc", "combine"):
            raise ValueError(f"Invalid mode '{mode}' — must be 'pbanc' or 'combine'")
        self.mode = mode
        self.source_key = "sbiz24" if mode == "pbanc" else "sbiz24_combine"
        self.definition: SourceDefinition = KNOWN_SOURCES[self.source_key]
        self._page_size = page_size
        self._cookies: dict[str, str] = {}
        self._checkpoint: str | None = None
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _host_ok(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return any(
            parsed.hostname == h or (parsed.hostname or "").endswith("." + h) for h in ALLOWED_HOSTS
        )

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST to sbiz24 API with host validation and retry."""
        url = SBIZ24_BASE + path
        if not self._host_ok(url):
            raise BlockedError(f"URL host not allowed: {url}")

        data = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin-Method": "GET",
            "User-Agent": "policy-search-backend/0.1",
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                resp = self._opener.open(req, timeout=30)
                result: dict[str, Any] = json.loads(resp.read().decode())
                if result.get("result") is False or "data" not in result:
                    raise ParseError(f"API result=false or structure changed: {str(result)[:120]}")
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise BlockedError(f"HTTP {exc.code} — blocked/auth required") from exc
                last_exc = exc
                if exc.code != 429 and exc.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_exc = exc
            time.sleep(0.5 * (attempt + 1))

        raise RetryableError(f"POST {path} failed after retries: {last_exc}")

    def _total_count(self, data: dict[str, Any]) -> int:
        return int(data["data"]["default"]["total"])

    def _parse_list_page(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = data["data"]["default"]["list"]
        return result

    def _normalize(self, item: dict[str, Any]) -> SourceRecord:
        if self.mode == "pbanc":
            return normalize_pbanc(item)
        return normalize_combine(item)

    def list_records(
        self,
        *,
        checkpoint: str | None = None,
        max_pages: int | None = None,
    ) -> Iterator[SourceRecord]:
        """Yield normalized listing records from pbanc or combine."""
        url = PBANC_LIST_URL if self.mode == "pbanc" else COMBINE_LIST_URL
        start = 0
        total: int | None = None
        seen: set[str] = set()
        pages = 0

        while True:
            body: dict[str, Any] = {
                "sortModel": [],
                "search": dict(_EMPTY_SEARCH),
                "paging": True,
                "startRow": start,
                "endRow": start + self._page_size,
            }
            data = self._post(url, body)

            if total is None:
                total = self._total_count(data)

            items = self._parse_list_page(data)
            if not items:
                break

            for item in items:
                record = self._normalize(item)
                if record.remote_id in seen:
                    continue
                seen.add(record.remote_id)
                yield record

            start += self._page_size
            pages += 1
            if max_pages and pages >= max_pages:
                break
            if total is not None and start >= total:
                break
            time.sleep(self.definition.request_delay_seconds)

    def fetch_detail(self, record: SourceRecord) -> SourceRecord:
        """Fetch detail for a pbanc record. Combine records with PBLN_*
        are routed to bizinfo and should not use this endpoint.

        Raises:
            ParseError: If detail response ID doesn't match request
                        (identity mismatch — wrong announcement).
            ValueError: If record is a PBLN_* that needs bizinfo routing.
        """
        if record.announce_no and record.announce_no.startswith("PBLN"):
            raise ValueError(
                f"PBLN record {record.remote_id} must be routed to bizinfo detail, "
                f"not sbiz24 detail API"
            )

        if record.source == "sbiz24_combine":
            gubun = record.raw.get("pbancGubun", "")
            if gubun == "C":
                raise ValueError(
                    f"Loan product (gubun=C) {record.remote_id} needs loanProduct detail, "
                    f"not sbiz24 pbanc API"
                )

        body: dict[str, Any] = {}
        sn = record.remote_id
        data = self._post(PBANC_DETAIL_URL.format(sn=sn), body)
        detail = data.get("data", {}).get("default", {})

        detail_sn = str(detail.get("pbancSn") or "")
        if detail_sn != sn:
            raise ParseError(f"Identity mismatch: requested sn={sn}, got pbancSn={detail_sn}")

        detail_title = _norm_title(detail.get("pbancNm"))
        if detail_title and _norm_title(record.title) and detail_title != _norm_title(record.title):
            raise ParseError(
                f"Title mismatch: list='{record.title[:50]}', detail='{detail_title[:50]}'"
            )

        body_text = _strip_html(detail.get("pbancDtlCn"))
        updated = record.model_copy(
            update={
                "body_text": body_text,
            }
        )
        return updated

    def list_attachments(self, record: SourceRecord) -> list[AttachmentMeta]:
        """List attachment metadata for a pbanc record."""
        try:
            data = self._post(
                ATTACH_LIST_URL,
                {"pbancSn": record.remote_id},
            )
        except (ParseError, RetryableError):
            return []

        files = data.get("data", {}).get("list", [])
        if not isinstance(files, list):
            return []

        attachments: list[AttachmentMeta] = []
        for f in files:
            attachments.append(
                AttachmentMeta(
                    filename=str(f.get("fileNm") or f.get("orgFileNm") or ""),
                    url=str(f.get("downUrl") or ""),
                    mime_type=f.get("fileExtNm"),
                    byte_size=f.get("fileSz"),
                )
            )
        return attachments

    def get_checkpoint(self) -> str | None:
        return self._checkpoint

    def collect(self) -> CollectionReport:
        """Run a full collection cycle."""
        started = datetime.now(UTC)
        expected = 0
        received = 0
        failed = 0
        error_msg: str | None = None

        try:
            records = list(self.list_records())
            received = len(records)
        except BlockedError as exc:
            error_msg = str(exc)
        except ParseError as exc:
            error_msg = str(exc)
        except RetryableError as exc:
            error_msg = str(exc)
            failed = expected

        finished = datetime.now(UTC)
        outcome = outcome_from_counts(
            expected=expected,
            received=received,
            failed=failed,
            blocked=error_msg is not None and "blocked" in (error_msg or "").lower(),
        )

        return CollectionReport(
            source=self.source_key,
            outcome=outcome,
            exit_code=exit_code_from_outcome(outcome),
            started_at=started,
            finished_at=finished,
            expected=expected,
            received_raw=received,
            received_unique=received,
            persisted=received,
            error_summary=error_msg,
        )
