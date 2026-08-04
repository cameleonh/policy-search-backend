"""Cross-source duplicate detection.

Detects candidate duplicates across different sources using multiple
strategies.  These are *candidates* — final resolution happens in the
normalization pipeline (issue #15).

Strategies (in priority order):
  1. source + remote_id — exact same source and native ID
  2. announce_no + agency — same official number from same agency
  3. canonical_url — identical normalized URL
  4. title + agency + period — fuzzy title match with same agency and
     overlapping application window
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from workers.ingest.source_record import SourceRecord


@dataclass(frozen=True)
class DuplicateCandidate:
    """A pair of records that may represent the same policy."""

    record_a: SourceRecord
    record_b: SourceRecord
    strategy: str
    confidence: float


def _normalize_url(url: str) -> str:
    """Strip trailing slash and lowercase for URL comparison."""
    return url.rstrip("/").lower()


def _title_similarity(a: str, b: str) -> float:
    """Simple Jaccard similarity on whitespace-tokenized titles."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _periods_overlap(a: SourceRecord, b: SourceRecord) -> bool:
    """Check if application periods overlap (inclusive)."""
    if a.apply_start is None or a.apply_end is None:
        return False
    if b.apply_start is None or b.apply_end is None:
        return False
    return not (a.apply_end < b.apply_start or b.apply_end < a.apply_start)


def find_duplicates(records: list[SourceRecord]) -> list[DuplicateCandidate]:
    """Find all candidate duplicate pairs across sources.

    Returns a list of DuplicateCandidate pairs.  Each pair appears once
    (the pair with the lower list index is record_a).
    """
    candidates: list[DuplicateCandidate] = []

    # Strategy 1: source + remote_id
    by_source_remote: dict[tuple[str, str], SourceRecord] = {}
    for rec in records:
        key = (rec.source, rec.remote_id)
        if key in by_source_remote:
            candidates.append(
                DuplicateCandidate(
                    record_a=by_source_remote[key],
                    record_b=rec,
                    strategy="source+remote_id",
                    confidence=1.0,
                )
            )
        else:
            by_source_remote[key] = rec

    # Strategy 2: announce_no + agency
    by_announce: dict[tuple[str, str], SourceRecord] = {}
    for rec in records:
        if rec.announce_no and rec.agency:
            key = (rec.announce_no, rec.agency.lower())
            if key in by_announce:
                candidates.append(
                    DuplicateCandidate(
                        record_a=by_announce[key],
                        record_b=rec,
                        strategy="announce_no+agency",
                        confidence=0.95,
                    )
                )
            else:
                by_announce[key] = rec

    # Strategy 3: canonical_url
    by_url: dict[str, list[SourceRecord]] = defaultdict(list)
    for rec in records:
        by_url[_normalize_url(rec.canonical_url)].append(rec)
    for group in by_url.values():
        if len(group) > 1:
            for i in range(1, len(group)):
                candidates.append(
                    DuplicateCandidate(
                        record_a=group[0],
                        record_b=group[i],
                        strategy="canonical_url",
                        confidence=0.9,
                    )
                )

    # Strategy 4: title + agency + period overlap (fuzzy)
    by_agency: dict[str, list[SourceRecord]] = defaultdict(list)
    for rec in records:
        if rec.agency:
            by_agency[rec.agency.lower()].append(rec)
    for group in by_agency.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                # Skip if already matched by an exact strategy
                if a.source == b.source and a.remote_id == b.remote_id:
                    continue
                sim = _title_similarity(a.title, b.title)
                if sim >= 0.7 and _periods_overlap(a, b):
                    candidates.append(
                        DuplicateCandidate(
                            record_a=a,
                            record_b=b,
                            strategy="title+agency+period",
                            confidence=round(sim * 0.7, 2),
                        )
                    )

    return candidates
