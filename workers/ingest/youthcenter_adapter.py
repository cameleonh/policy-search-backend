"""온통청년(youthcenter.go.kr) ingestion adapter.

Implements the SourceAdapter protocol for the youth policy center.
Ports the network/parsing contract from youth-search's youthcenter_crawl.py
at commit 68a545d, adapted to the Issue #3 adapter contracts.

Flow:
  1. Bootstrap — GET search page to obtain XSRF-TOKEN + guest JWT
  2. Probe totalCount with a tiny listCount=1 request
  3. Full fetch in a single large-page request (up to MAX_LIST_COUNT)
  4. Normalize each raw record to SourceRecord
"""

from __future__ import annotations

import contextlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from typing import Any

from workers.ingest.collection_report import (
    CollectionReport,
    exit_code_from_outcome,
    outcome_from_counts,
)
from workers.ingest.errors import BlockedError, ParseError, RetryableError
from workers.ingest.region_util import _clean, canon_region
from workers.ingest.source_definition import KNOWN_SOURCES, SourceDefinition
from workers.ingest.source_record import RecordStatus, SourceRecord

BOOT_URL = "https://www.youthcenter.go.kr/youthPolicy/ythPlcyTotalSearch"
SEARCH_URL = "https://www.youthcenter.go.kr/pubot/search/portalPolicySearch"
DETAIL_URL = "https://www.youthcenter.go.kr/youthPolicy/ythPlcyDetail?plcyNo={id}"
DELAY = 0.4
MAX_LIST_COUNT = 20000

_EMPTY_PARAMS: dict[str, str] = {
    "PVSN_INST_GROUP_CD": "",
    "SPRT_TRGT_AGE": "",
    "EARN_MIN_AMT": "",
    "EARN_MAX_AMT": "",
    "QLFC_ACBG_NM": "",
    "MRG_STTS_CD": "",
    "query": "",
    "MJR_CND_NM": "",
    "EMPM_STTS_NM": "",
    "STDG_NM": "",
    "SPCL_FLD_NM": "",
    "USER_MCLSF_NO": "",
    "STDG_CTPV_NM": "",
    "PLCY_KYWD_SN": "",
    "APLY_PRD_BGNG_YMD": "",
    "APLY_PRD_END_YMD": "",
    "APLY_PRD_SE_CD": "",
    "ODTM_CD": "",
}

_DATE_SENTINELS = {"", "0", "00000000", "0000-00-00", "null", "None"}


def _norm_date(value: object) -> str:
    """Normalize YYYYMMDD or loose date → 'YYYY-MM-DD'. Empty → ''."""
    s = _clean(value)
    if s in _DATE_SENTINELS:
        return ""
    if re.fullmatch(r"0+", s):
        return ""
    if re.fullmatch(r"\d{8}", s):
        if s.startswith("0000"):
            return ""
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    return s


def _map_status(raw: str) -> RecordStatus:
    if raw == "진행중":
        return RecordStatus.OPEN
    if raw == "상시":
        return RecordStatus.ALWAYS_OPEN
    if raw == "마감":
        return RecordStatus.CLOSED
    return RecordStatus.UNKNOWN


def normalize_youthcenter(raw: dict[str, str]) -> SourceRecord:
    """Convert a 79-field 온통청년 raw record to a SourceRecord.

    Preserves all structured eligibility axes (age, income, marriage,
    education, employment, major, special_field) and descriptive fields.
    Empty eligibility axes are NOT inferred as 'unlimited' — they stay
    empty to avoid false eligibility matches.
    """
    docid = raw.get("DOCID", "")
    apply_start_str = _norm_date(raw.get("APLY_PRD_BGNG_YMD", ""))
    apply_end_str = _norm_date(raw.get("APLY_PRD_END_YMD", ""))

    return SourceRecord(
        source="youthcenter",
        remote_id=docid,
        canonical_url=DETAIL_URL.format(id=docid),
        title=_clean(raw.get("PLCY_NM", "")),
        agency=_clean(raw.get("SPRVSN_INST_CD_NM") or raw.get("RGTR_UP_INST_CD_NM", "")),
        status=_map_status(raw.get("APLY_PRD_SE_CD", "")),
        apply_start=datetime.fromisoformat(apply_start_str) if apply_start_str else None,
        apply_end=datetime.fromisoformat(apply_end_str) if apply_end_str else None,
        region=canon_region(raw.get("STDG_NM", "")) or None,
        target_category="individual",
        crawled_at=datetime.now(UTC),
        raw=dict(raw),
    )


class YouthcenterAdapter:
    """Adapter for 온통청년 policy center."""

    def __init__(
        self,
        *,
        open_only: bool = False,
        region_filter: str | None = None,
        inst_group: str | None = None,
    ) -> None:
        self.definition: SourceDefinition = KNOWN_SOURCES["youthcenter"]
        self._open_only = open_only
        self._region_filter = region_filter
        self._inst_group = inst_group
        self._cookies = CookieJar()
        self._checkpoint: str | None = None

    def _fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        timeout: int = 90,
    ) -> tuple[int, str]:
        """Perform an HTTP request and return (status_code, response_text)."""
        data: bytes | None = None
        hdrs: dict[str, str] = {"User-Agent": "policy-search-backend/0.1"}
        if headers:
            hdrs.update(headers)
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cookies))
        req = urllib.request.Request(url, data=data, headers=hdrs)
        try:
            resp = opener.open(req, timeout=timeout)
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = ""
            with contextlib.suppress(Exception):
                body = exc.read().decode("utf-8", errors="replace")
            return exc.code, body
        except (urllib.error.URLError, OSError) as exc:
            raise RetryableError(f"Network error: {exc}") from exc

    def _bootstrap(self) -> dict[str, str]:
        """GET the search page to obtain XSRF-TOKEN and guest JWT."""
        status, _ = self._fetch(BOOT_URL, timeout=30)
        if status != 200:
            raise BlockedError(f"Bootstrap failed: HTTP {status}")

        xsrf = None
        for cookie in self._cookies:
            if cookie.name == "XSRF-TOKEN":
                xsrf = cookie.value
                break

        headers: dict[str, str] = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.youthcenter.go.kr",
            "Referer": BOOT_URL,
            "user_id": "guest",
        }
        if xsrf:
            headers["X-CSRF-TOKEN"] = xsrf
        return headers

    def _search(
        self, hdr: dict[str, str], **params: object
    ) -> tuple[int, str, dict[str, object] | None]:
        """POST to the search API and return (status, text, parsed_json)."""
        body: dict[str, object] = {
            **_EMPTY_PARAMS,
            "pageNum": 1,
            "sortFields": "DATE/DESC",
            "listCount": 9,
            "searchFields": "all",
            **params,
        }
        status, text = self._fetch(SEARCH_URL, headers=hdr, json_body=body, timeout=90)
        if status != 200:
            return status, text, None
        try:
            return status, text, json.loads(text)
        except json.JSONDecodeError:
            return status, text, None

    def list_records(
        self,
        *,
        checkpoint: str | None = None,
        max_pages: int | None = None,
    ) -> Iterator[SourceRecord]:
        """Yield normalized listing records from 온통청년."""
        hdr = self._bootstrap()

        params: dict[str, object] = {}
        if self._region_filter:
            params["STDG_CTPV_NM"] = canon_region(self._region_filter)
        if self._inst_group:
            params["PVSN_INST_GROUP_CD"] = self._inst_group

        time.sleep(DELAY)
        _, _, probe_data = self._search(hdr, listCount=1, **params)
        if probe_data is None:
            raise ParseError("Probe response could not be parsed")

        total_raw = probe_data.get("totalCount", 0)
        total = int(total_raw) if isinstance(total_raw, (int, str)) else 0
        if total == 0:
            return

        want = min(total + 50, MAX_LIST_COUNT)
        time.sleep(DELAY)
        _, _, full_data = self._search(hdr, listCount=want, **params)
        if full_data is None:
            raise ParseError("Full fetch response could not be parsed")

        search_result_raw = full_data.get("searchResult")
        search_result: dict[str, Any] = (
            search_result_raw if isinstance(search_result_raw, dict) else {}
        )
        rows_raw = search_result.get("youthpolicy")
        rows: list[dict[str, str]] = rows_raw if isinstance(rows_raw, list) else []

        docids = [r.get("DOCID", "") for r in rows]
        unique_ids = set(docids)
        if len(unique_ids) < len(docids):
            raise ParseError(f"Duplicate DOCIDs: {len(docids) - len(unique_ids)} duplicates")

        for raw in rows:
            record = normalize_youthcenter(raw)
            if self._open_only and record.status == RecordStatus.CLOSED:
                continue
            yield record

    def fetch_detail(self, record: SourceRecord) -> SourceRecord:
        """The 79-field list record already contains all structured data."""
        return record

    def list_attachments(self, record: SourceRecord) -> list[Any]:
        """온통청년 does not expose downloadable attachments via the API."""
        return []

    def get_checkpoint(self) -> str | None:
        return self._checkpoint

    def collect(self) -> CollectionReport:
        """Run a full collection cycle and return a summary report."""
        started = datetime.now(UTC)
        expected = 0
        received = 0
        failed = 0
        error_msg: str | None = None

        try:
            records = list(self.list_records())
            received = len(records)

            hdr = self._bootstrap()
            _, _, probe = self._search(hdr, listCount=1)
            if probe:
                total_raw = probe.get("totalCount", 0)
                if isinstance(total_raw, (int, str)):
                    expected = int(total_raw)
        except BlockedError as exc:
            error_msg = str(exc)
            failed = expected
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
            blocked=error_msg is not None and "Bootstrap" in error_msg,
        )

        return CollectionReport(
            source="youthcenter",
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
