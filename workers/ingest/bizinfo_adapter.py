"""기업마당(bizinfo.go.kr) ingestion adapter.

Ports the collection contract from sole-search's sources_crawl.py at
commit f6fd9e8.  Crawls 모집중 (schEndAt=N) announcements across all
pages, parses HTML list/detail, and validates detail identity.

Key safety features:
  - Remote ID is PBLN_* format
  - Detail page self-identity verified via altUrl JS assignment
  - Host validation with no-redirect policy (bizinfo.go.kr only)
  - Body content hashed between start/end markers (hash v2/v3)
"""

from __future__ import annotations

import contextlib
import hashlib
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

BIZINFO_BASE = "https://www.bizinfo.go.kr"
LIST_URL = f"{BIZINFO_BASE}/sii/siia/selectSIIA200View.do"
KST = timezone(timedelta(hours=9))
ALLOWED_HOSTS = ("bizinfo.go.kr",)
DEFAULT_DELAY = 0.5
ROWS_PER_PAGE = 15

_BLOCK_MARKERS = ("captcha", "로그인이 필요", "접근이 차단", "비정상적인 접근")

_START_MARKERS = (
    re.compile(r'<div[^>]+class="[^"]*view_cont[^"]*"'),
    re.compile(r'<div[^>]+id="print_area"'),
)
_END_MARKERS = (
    re.compile(r'<div[^>]+id="footer"'),
    re.compile(r"<footer\b"),
    re.compile(r'<div[^>]+class="[^"]*footer'),
    re.compile(r'<div[^>]+class="[^"]*btn_area'),
    re.compile(r'<div[^>]+class="[^"]*paging'),
    re.compile(r"목록으로|이전글|다음글"),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _clean(text: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = htmllib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _split_period(s: str) -> tuple[str, str]:
    if not s:
        return "", ""
    parts = re.split(r"~|~|\b까지\b", s)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", ""


def _map_status(apply_end: str) -> RecordStatus:
    if not apply_end:
        return RecordStatus.UNKNOWN
    with contextlib.suppress(ValueError):
        end_d = datetime.strptime(apply_end[:10], "%Y-%m-%d").replace(tzinfo=KST)
        return (
            RecordStatus.OPEN
            if end_d >= datetime.now(KST) - timedelta(days=1)
            else RecordStatus.CLOSED
        )
    return RecordStatus.UNKNOWN


def _parse_iso_date(s: str | None) -> datetime | None:
    if not s or len(str(s).strip()) < 10:
        return None
    with contextlib.suppress(ValueError):
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=KST)
    return None


def normalize_bizinfo(
    pblanc_id: str,
    title: str,
    agency: str,
    apply_start: str,
    apply_end: str,
    field: str = "",
    reg_date: str = "",
) -> SourceRecord:
    """Convert parsed bizinfo list fields to a SourceRecord."""
    return SourceRecord(
        source="bizinfo",
        remote_id=pblanc_id,
        canonical_url=f"{BIZINFO_BASE}/sii/siia/selectSIIA200Detail.do?pblancId={pblanc_id}",
        title=_clean(title),
        agency=_clean(agency),
        status=_map_status(apply_end),
        apply_start=_parse_iso_date(apply_start),
        apply_end=_parse_iso_date(apply_end),
        announce_no=pblanc_id,
        tags=[field] if field else [],
        target_category="business",
        crawled_at=datetime.now(UTC),
        raw={"field": field, "reg_date": reg_date},
    )


def parse_bizinfo_list_page(html_text: str) -> tuple[list[SourceRecord], bool]:
    """Parse a bizinfo HTML list page into SourceRecords.

    Returns (records, has_more).  has_more is True if any records were
    found on this page (simple heuristic — pagination is checked by
    collect_all_pages via the caller).
    """
    records: list[SourceRecord] = []

    for row in re.findall(r"<tr>[\s\S]*?</tr>", html_text):
        m = re.search(
            r'href\s*=\s*"([^"]*pblancId=(PBLN_\d+)[^"]*)"[^>]*>\s*([\s\S]*?)</a>',
            row,
        )
        if not m:
            continue

        pblanc_id = m.group(2)
        title = _clean(m.group(3))

        tds = [
            _clean(re.sub(r"<[^>]+>", " ", td))
            for td in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)
        ]

        apply_start, apply_end = ("", "")
        if len(tds) > 3:
            apply_start, apply_end = _split_period(tds[3])

        agency = ""
        if len(tds) > 5:
            agency = " / ".join(x for x in tds[4:6] if x)

        field = tds[1] if len(tds) > 1 and tds[1] else ""
        reg_date = tds[6] if len(tds) > 6 else ""

        records.append(
            normalize_bizinfo(
                pblanc_id=pblanc_id,
                title=title,
                agency=agency,
                apply_start=apply_start,
                apply_end=apply_end,
                field=field,
                reg_date=reg_date,
            )
        )

    return records, bool(records)


def parse_total_count(html_text: str) -> int | None:
    """Extract the total count from the '분야(N) 공고보기' marker."""
    seg = re.search(r'분야\((\d[\d,]*)\) 공고보기"[^>]{0,120}id="hashAll"', html_text)
    if seg:
        return int(seg.group(1).replace(",", ""))
    counts = [
        int(c.replace(",", "")) for c in re.findall(r"분야\((\d[\d,]*)\) 공고보기", html_text)
    ]
    return max(counts) if counts else None


def extract_last_page(html_text: str) -> int:
    """Extract the maximum cpage value from pagination links."""
    pages = [int(p) for p in re.findall(r"cpage=(\d+)", html_text)]
    return max(pages) if pages else 0


def extract_body_text(html_text: str) -> str:
    """Extract body text between start and end markers (hash v2)."""
    start_match = None
    for pattern in _START_MARKERS:
        start_match = pattern.search(html_text)
        if start_match:
            break

    if not start_match:
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html_text)
        text = re.sub(r"<[^>]+>", "\n", text)
        return htmllib.unescape(re.sub(r"\n\s*\n+", "\n", text)).strip()

    body = html_text[start_match.start() :]

    for pattern in _END_MARKERS:
        end_match = pattern.search(body)
        if end_match:
            body = body[: end_match.start()]
            break

    body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", body)
    body = re.sub(r"<[^>]+>", "\n", body)
    return htmllib.unescape(re.sub(r"\n\s*\n+", "\n", body)).strip()


def content_hash_v2(body_text: str) -> str:
    return hashlib.sha256(body_text.encode()).hexdigest()


def content_hash_v3(body_text: str, attachment_hashes: list[str]) -> str:
    payload = body_text + "\n" + "\n".join(sorted(attachment_hashes))
    return hashlib.sha256(payload.encode()).hexdigest()


class BizinfoAdapter:
    """Adapter for 기업마당 (bizinfo.go.kr) 모집중 공고."""

    def __init__(
        self,
        *,
        max_pages: int | None = None,
    ) -> None:
        self.definition: SourceDefinition = KNOWN_SOURCES["bizinfo"]
        self._max_pages = max_pages
        self._checkpoint: str | None = None
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _host_ok(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return any(
            parsed.hostname == h or (parsed.hostname or "").endswith("." + h) for h in ALLOWED_HOSTS
        )

    def _fetch_html(self, url: str, retries: int = 3) -> str:
        if not self._host_ok(url):
            raise BlockedError(f"URL host not allowed: {url}")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.4 Safari/605.1.15"
            ),
        }

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                resp = self._opener.open(req, timeout=30)
                body = resp.read().decode("utf-8", errors="replace")

                low = body[:4000].lower()
                if any(marker in low for marker in _BLOCK_MARKERS):
                    raise BlockedError("Block/login page detected (HTTP 200)")
                return str(body)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise BlockedError(f"HTTP {exc.code} — blocked/auth required") from exc
                last_exc = exc
                if exc.code != 429 and exc.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
            time.sleep(self.definition.request_delay_seconds * (attempt + 1))

        raise RetryableError(f"Fetch failed after {retries} retries: {last_exc}")

    def list_records(
        self,
        *,
        checkpoint: str | None = None,
        max_pages: int | None = None,
    ) -> Iterator[SourceRecord]:
        """Yield normalized listing records from all bizinfo pages."""
        effective_max = max_pages or self._max_pages
        seen: set[str] = set()
        page = 1

        while True:
            url = f"{LIST_URL}?rows={ROWS_PER_PAGE}&cpage={page}&schEndAt=N"
            html_text = self._fetch_html(url)
            records, has_more = parse_bizinfo_list_page(html_text)

            if page == 1 and not records:
                raise ParseError("First page returned 0 records — parser regression or block")

            new_count = 0
            for record in records:
                if record.remote_id not in seen:
                    seen.add(record.remote_id)
                    yield record
                    new_count += 1

            if not has_more or new_count == 0:
                break
            if effective_max and page >= effective_max:
                break

            page += 1
            time.sleep(self.definition.request_delay_seconds)

    def fetch_detail(self, record: SourceRecord) -> SourceRecord:
        """Fetch detail HTML, extract body text, verify identity.

        Raises:
            ParseError: If the detail page identity doesn't match the request.
            BlockedError: If blocked.
        """
        url = f"{BIZINFO_BASE}/sii/siia/selectSIIA200Detail.do?pblancId={record.remote_id}"
        html_text = self._fetch_html(url)

        m = re.search(r"pblancId=(PBLN_\d+)", record.canonical_url)
        if m:
            req_pid = m.group(1)
            alturl_ids: set[str] = set()
            for script_match in re.finditer(r"<script[^>]*>([\s\S]*?)</script>", html_text):
                script_text = script_match.group(1)
                ids = set(re.findall(r"altUrl.*?pblancId=(PBLN_\d+)", script_text))
                alturl_ids |= ids

            if alturl_ids and alturl_ids != {req_pid}:
                raise ParseError(
                    f"Identity mismatch: page altUrl pblancId={alturl_ids} vs request={req_pid}"
                )

        body_text = extract_body_text(html_text)
        content_hash = content_hash_v2(body_text)

        attachments = self._extract_attachment_links(html_text)

        return record.model_copy(
            update={
                "body_text": body_text,
                "content_hash": content_hash if not attachments else None,
                "attachments_complete": not attachments,
            }
        )

    def _extract_attachment_links(self, html_text: str) -> list[str]:
        """Extract raw attachment URLs from detail page HTML."""
        raw = re.findall(r'href="(/cmm/fms/[^"]+|/uploads/[^"]+)"', html_text)
        return [BIZINFO_BASE + htmllib.unescape(u) for u in raw]

    def list_attachments(self, record: SourceRecord) -> list[AttachmentMeta]:
        """List attachment metadata by fetching the detail page."""
        url = f"{BIZINFO_BASE}/sii/siia/selectSIIA200Detail.do?pblancId={record.remote_id}"
        try:
            html_text = self._fetch_html(url)
        except (ParseError, RetryableError, BlockedError):
            return []

        attachments: list[AttachmentMeta] = []
        for link in self._extract_attachment_links(html_text):
            filename = link.rsplit("/", 1)[-1].split("?")[0]
            attachments.append(
                AttachmentMeta(
                    filename=filename,
                    url=link,
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
            failed = 1
        except RetryableError as exc:
            error_msg = str(exc)

        finished = datetime.now(UTC)
        outcome = outcome_from_counts(
            expected=expected,
            received=received,
            failed=failed,
            blocked=error_msg is not None and "blocked" in (error_msg or "").lower(),
        )

        return CollectionReport(
            source="bizinfo",
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
